"""Compilador: `.harness/harness.yaml` -> governança NATIVA do Claude Code.

Pivot do projeto (2026-07): o harness não executa mais tarefas — ele compila
a especificação de governança para os mecanismos que o Claude Code já
enforça sozinho:

    .harness/harness.yaml  ──compile──►  .claude/settings.local.json  (permissions + hooks)
                                         .harness/hooks/*.py          (PreToolUse standalone)
                                         AGENTS.md                    (bloco gerenciado)

Fontes de verdade reusadas da biblioteca (não duplicar tabelas):
- `_POLICY_MATRIX`/`_ALWAYS_GATED` (governance/approval.py) — quais classes
  de risco exigem humano em cada modo.

O destino é `settings.local.json`, não `settings.json`: o comando de hook
compilado leva path ABSOLUTO (ver `_hook_entry`), então é dado desta máquina
e nunca pode viajar no git — ver `harness.settings_paths` para a política e
para a migração do alvo já instalado.

Estratégia de merge: nunca sobrescrever o que o usuário tem lá. As entradas
gerenciadas pelo harness ficam registradas em `.harness/compiled-state.json`;
recompilar remove as entradas ANTIGAS gerenciadas e insere as novas,
preservando qualquer regra/hook manual.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from harness import __version__ as _HARNESS_VERSION
from harness.config import HarnessConfig
from harness.governance.approval import _ALWAYS_GATED, _POLICY_MATRIX
from harness.hook_launcher import hook_command
from harness.killswitch import DISABLED_CHECK_SRC
from harness.settings_paths import prepare_managed_settings, write_managed_settings

HARNESS_YAML = ".harness/harness.yaml"
STATE_FILE = ".harness/compiled-state.json"
HOOKS_DIR = ".harness/hooks"
AGENTS_BEGIN = "<!-- harness:begin -->"
AGENTS_END = "<!-- harness:end -->"

# Classe de risco -> regras de permissão do Claude Code. Espelha o
# vocabulário do ToolSpec.risk_class; a decisão de QUAIS classes gatear vem
# de _POLICY_MATRIX/_ALWAYS_GATED, nunca daqui.
_RISK_TO_RULES: dict[str, list[str]] = {
    "read": ["Read", "Grep", "Glob"],
    "edit": ["Edit", "Write"],
    "execute": ["Bash"],
    "network": ["WebFetch", "WebSearch", "Bash(curl *)", "Bash(wget *)"],
}
# Seções do harness.yaml que a compilação usa; as demais (sandbox, routing,
# eet...) pertencem ao modo de execução congelado e geram aviso.
_COMPILED_SECTIONS = {"governance", "verification"}

@dataclass
class Artifacts:
    """Saída pura do compilador (nada escrito em disco) — o audit compara
    isto com o que está no projeto para detectar drift."""

    permission_rules: dict[str, list[str]]      # {"allow": [...], "ask": [...]}
    hook_entries: list[dict[str, Any]]          # entradas PreToolUse p/ settings
    hook_files: dict[str, str]                  # nome do arquivo -> conteúdo
    agents_block: str                           # bloco gerenciado do AGENTS.md
    warnings: list[str] = field(default_factory=list)


@dataclass
class CompileResult:
    settings_path: Path
    agents_path: Path
    hooks_written: list[Path]
    warnings: list[str]


# ---------------------------------------------------------------------------
# Render (puro)
# ---------------------------------------------------------------------------

def render(config: HarnessConfig, target_dir: Path, raw_keys: set[str] | None = None) -> Artifacts:
    warnings: list[str] = []
    if raw_keys:
        ignored = sorted(raw_keys - _COMPILED_SECTIONS)
        if ignored:
            warnings.append(
                f"Seções ignoradas na compilação (modo execução congelado): {', '.join(ignored)}"
            )

    mode = config.governance.approval_policy
    gated = _ALWAYS_GATED | _POLICY_MATRIX[mode]

    ask: list[str] = []
    allow: list[str] = []
    for risk_class, rules in _RISK_TO_RULES.items():
        if risk_class in gated:
            ask.extend(rules)
        elif risk_class != "network":  # network nunca vai para allow
            allow.extend(rules)

    # `guard_tests.py` (mecanismo estático sempre-`ask`) não é mais gerado —
    # T-04/onda-1. O `boundary_guard.py` (instalado por `install_boundary_guard`
    # no mesmo comando que `compile_project`) cobre a mesma proteção de
    # enfraquecimento de teste por decisão POR-TAREFA desde a Fase 2; gerar um
    # script que nenhuma instalação registra (issue #61) era peso morto puro.
    # Histórico completo: docs/project/HISTORICO-boundary_guard-2026-07-30.md.
    hook_files: dict[str, str] = {}
    if config.verification.enforce_tdd:
        hook_files["guard_test_runner.py"] = _render_guard_test_runner(
            config.verification.test_command
        )

    hooks_abs = (target_dir / HOOKS_DIR).resolve()
    hook_entries: list[dict[str, Any]] = []
    if config.verification.enforce_tdd:
        hook_entries.append(_hook_entry("Bash", hooks_abs / "guard_test_runner.py"))

    agents_block = _render_agents_block(config)

    return Artifacts(
        permission_rules={"allow": allow, "ask": ask},
        hook_entries=hook_entries,
        hook_files=hook_files,
        agents_block=agents_block,
        warnings=warnings,
    )


def _hook_entry(matcher: str, script: Path) -> dict[str, Any]:
    # Path absoluto embutido na compilação: portátil entre shells (cmd não
    # expande $VAR); se o repo mudar de lugar, `harness audit` acusa o drift.
    #
    # `hook_command()` é o MESMO ponto único dos três hooks de sessão
    # (`boundary_guard`, `session_start`, `stop_hook`): interpretador absoluto
    # + sufixo `|| exit 2`. Este aqui ficou para trás quando o Item 1/1b
    # entrou, e o achado F8 do dogfood venv-Windows mostrou o custo: um
    # repo que rodou só `harness compile` — estado por onde TODA instalação
    # passa, antes de existir contrato — ficava com os guards de TDD lançados
    # por `python` nu. Interpretador irresolúvel ⇒ processo morre com código
    # != 2 ⇒ a doc do Claude Code manda a tool call PASSAR. Ver
    # `harness.hook_launcher` para o mecanismo inteiro.
    return {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": hook_command(script)}],
    }


def _render_guard_test_runner(test_command: str) -> str:
    # A disciplina TDD gateia a ESCRITA de teste (boundary_guard, por-tarefa),
    # não a execução — pedir aprovação a cada `pytest` rodado é fricção pura
    # depois que o teste já foi aprovado na escrita (issue: dezenas de asks
    # repetidos para o mesmo comando dentro de uma única tarefa). Este hook
    # fica registrado (matcher Bash) só para permitir reativar a checagem no
    # futuro sem recompilar do zero; hoje sempre allow.
    return f'''"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Rodar a suíte de teste NÃO exige aprovação humana — a disciplina TDD do
harness gateia a ESCRITA do arquivo de teste (boundary_guard, decisão
por-tarefa), não a sua execução repetida. Gerado de
test_command={test_command!r}; para mudar, edite .harness/harness.yaml e
rode `harness compile`.
"""
import json
import sys


{DISABLED_CHECK_SRC}


def main() -> None:
    if _harness_disabled():
        reason = (
            "harness desativado pelo usuario (.harness/harness.disabled) - "
            "kill-switch externo ativo"
        )
    else:
        json.load(sys.stdin)
        reason = (
            "execução da suíte de teste não exige aprovação — a disciplina "
            "TDD gateia a escrita do teste, não sua execução repetida"
        )

    print(json.dumps({{
        "hookSpecificOutput": {{
            "hookEventName": "PreToolUse",
            "permissionDecision": "allow",
            "permissionDecisionReason": reason,
        }}
    }}))


if __name__ == "__main__":
    main()
'''


def _render_agents_block(config: HarnessConfig) -> str:
    g = config.governance
    v = config.verification
    tdd = (
        "1. **TDD obrigatório**: escreva o teste falho antes da implementação. "
        f"Suíte: `{v.test_command}`. Arquivos de teste (`{v.test_glob}`) são "
        "protegidos — editá-los dispara aprovação humana (hook do harness).\n"
        if v.enforce_tdd
        else "1. TDD recomendado (enforcement desligado nesta configuração).\n"
    )
    return f"""{AGENTS_BEGIN}
## Governança do Harness (gerado — edite .harness/harness.yaml e rode `harness compile`)

Política de aprovação: **{g.approval_policy}**. Rede (WebFetch/WebSearch/curl)
sempre exige aprovação humana.

{tdd}2. **Orçamento (orientação)**: alvo de ~{g.budget.max_tokens_per_task:,} tokens
   por tarefa e {g.budget.max_tool_calls_per_task} tool calls. O Claude Code não
   expõe contagem de tokens a hooks — este teto é disciplina, não enforcement;
   se a tarefa estourar muito, pare e replaneje com o humano.
3. **Artefatos temporários de verificação** (screenshots, dumps de rede,
   HTML de debug, JSON de resposta de API): salve SEMPRE em
   `.harness/scratch/` — única área liberada para arquivos que não pertencem
   a nenhuma tarefa do contrato. A pasta é auto-ignorada pelo git e apagável
   a qualquer momento; nunca referencie nada dela em código e nunca salve
   esses artefatos na raiz do repositório.
{AGENTS_END}"""


# ---------------------------------------------------------------------------
# Apply (escreve no projeto-alvo)
# ---------------------------------------------------------------------------

def compile_project(target_dir: Path) -> CompileResult:
    target_dir = target_dir.resolve()
    yaml_path = target_dir / HARNESS_YAML
    if not yaml_path.is_file():
        raise FileNotFoundError(
            f"{yaml_path} não existe — rode a skill /harness-creator:init primeiro."
        )
    try:
        loaded = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, ValueError) as exc:
        # Único caminho do CLI que vazava traceback do PyYAML. `ValueError`
        # entra junto porque o resolver de data levanta ValueError CRU (não
        # YAMLError) quando os componentes não formam data real.
        raise ValueError(
            f"{yaml_path}: YAML inválido — {exc}\n"
            "       corrija a sintaxe ou rode a skill /harness-creator:init "
            "para regenerar o arquivo."
        ) from exc

    if loaded is None:
        # `harness.yaml` vazio caía em `{}` e compilava os defaults do
        # `HarnessConfig` — que são Python (`pytest`, `tests/**/*.py`). Num
        # repo Angular/.NET isso protege um diretório inexistente e DEIXA DE
        # proteger os testes reais: governança degradada em silêncio, com
        # exit 0. A spec é a entrada do compilador; vazia, não há o que
        # compilar.
        raise ValueError(
            f"{yaml_path} está vazio — não há governança para compilar. "
            "Rode a skill /harness-creator:init para preencher a spec "
            "(os defaults do schema são Python e não servem para todo repo)."
        )
    if not isinstance(loaded, dict):
        raise ValueError(
            f"{yaml_path}: o topo do YAML precisa ser um mapeamento "
            f"(chaves `governance:`/`verification:`), não {type(loaded).__name__}."
        )

    raw: dict[str, Any] = loaded
    config = HarnessConfig.model_validate(raw)
    artifacts = render(config, target_dir, raw_keys=set(raw))

    hooks_written = _write_hooks(target_dir, artifacts)
    settings_path = _merge_settings(target_dir, artifacts)
    agents_path = _write_agents_block(target_dir, artifacts)
    _write_state(target_dir, artifacts)

    return CompileResult(
        settings_path=settings_path,
        agents_path=agents_path,
        hooks_written=hooks_written,
        warnings=artifacts.warnings,
    )


def _write_hooks(target_dir: Path, artifacts: Artifacts) -> list[Path]:
    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for name, content in artifacts.hook_files.items():
        path = hooks_dir / name
        path.write_text(content, encoding="utf-8")
        written.append(path)
    # Hook obsoleto (ex.: enforce_tdd desligado depois): remover para não
    # sobrar guard morto referenciado por settings antigo.
    for stale in hooks_dir.glob("guard_*.py"):
        if stale.name not in artifacts.hook_files:
            stale.unlink()
    return written


def _load_state(target_dir: Path) -> dict[str, Any]:
    path = target_dir / STATE_FILE
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


def _write_state(target_dir: Path, artifacts: Artifacts) -> None:
    path = target_dir / STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "plugin_version": _HARNESS_VERSION,
        "managed_permissions": artifacts.permission_rules,
        "managed_hook_commands": [
            h["hooks"][0]["command"] for h in artifacts.hook_entries
        ],
    }
    path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def _merge_settings(target_dir: Path, artifacts: Artifacts) -> Path:
    # Destino machine-local (`.claude/settings.local.json`): as entradas
    # abaixo carregam o path ABSOLUTO desta máquina no comando do hook, então
    # não podem nascer no `settings.json` que o time versiona. `prepare_*`
    # também garante os .gitignore tool-owned — ver `harness.settings_paths`.
    settings_path, settings = prepare_managed_settings(target_dir)

    previous = _load_state(target_dir)
    prev_perms: dict[str, list[str]] = previous.get("managed_permissions", {})
    prev_hook_cmds: set[str] = set(previous.get("managed_hook_commands", []))

    # --- permissions: remove o que ERA gerenciado, injeta o novo ---
    permissions = settings.setdefault("permissions", {})
    for bucket in ("allow", "ask", "deny"):
        existing = permissions.get(bucket, [])
        managed_old = set(prev_perms.get(bucket, []))
        kept = [rule for rule in existing if rule not in managed_old]
        new_rules = artifacts.permission_rules.get(bucket, [])
        permissions[bucket] = kept + [r for r in new_rules if r not in kept]
    if not permissions.get("deny"):
        permissions.pop("deny", None)

    # --- hooks PreToolUse: substitui entradas cujo command era gerenciado ---
    hooks = settings.setdefault("hooks", {})
    pre = hooks.get("PreToolUse", [])
    is_managed = lambda entry: any(  # noqa: E731
        h.get("command") in prev_hook_cmds
        or "guard_tests.py" in h.get("command", "")
        or "guard_test_runner.py" in h.get("command", "")
        for h in entry.get("hooks", [])
    )
    kept_entries = [e for e in pre if not is_managed(e)]
    hooks["PreToolUse"] = kept_entries + artifacts.hook_entries

    write_managed_settings(settings_path, settings)
    return settings_path


def _write_agents_block(target_dir: Path, artifacts: Artifacts) -> Path:
    agents_path = target_dir / "AGENTS.md"
    block = artifacts.agents_block
    if agents_path.is_file():
        text = agents_path.read_text(encoding="utf-8")
        if AGENTS_BEGIN in text and AGENTS_END in text:
            pattern = re.compile(
                re.escape(AGENTS_BEGIN) + ".*?" + re.escape(AGENTS_END), re.DOTALL
            )
            text = pattern.sub(lambda _: block, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = "# AGENTS.md — Diretrizes para Agentes\n\n" + block + "\n"
    agents_path.write_text(text, encoding="utf-8")
    return agents_path
