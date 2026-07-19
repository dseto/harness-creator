"""Compilador: `.harness/harness.yaml` -> governança NATIVA do Claude Code.

Pivot do projeto (2026-07): o harness não executa mais tarefas — ele compila
a especificação de governança para os mecanismos que o Claude Code já
enforça sozinho:

    .harness/harness.yaml  ──compile──►  .claude/settings.json   (permissions + hooks)
                                         .harness/hooks/*.py     (PreToolUse standalone)
                                         AGENTS.md               (bloco gerenciado)

Fontes de verdade reusadas da biblioteca (não duplicar tabelas):
- `_POLICY_MATRIX`/`_ALWAYS_GATED` (governance/approval.py) — quais classes
  de risco exigem humano em cada modo.
- `_glob_to_regex` (verification/tdd_loop.py) — matching de arquivos de
  teste; o regex é EMBUTIDO no hook gerado (hooks são standalone/stdlib,
  não importam a biblioteca).

Estratégia de merge do settings.json: nunca sobrescrever o que o usuário
tem lá. As entradas gerenciadas pelo harness ficam registradas em
`.harness/compiled-state.json`; recompilar remove as entradas ANTIGAS
gerenciadas e insere as novas, preservando qualquer regra/hook manual.
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
from harness.patterns import _glob_to_regex

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

    hook_files: dict[str, str] = {
        "guard_tests.py": _render_guard_tests(config.verification.test_glob),
    }
    if config.verification.enforce_tdd:
        hook_files["guard_test_runner.py"] = _render_guard_test_runner(
            config.verification.test_command
        )

    hooks_abs = (target_dir / HOOKS_DIR).resolve()
    hook_entries = [
        _hook_entry("Write|Edit", hooks_abs / "guard_tests.py"),
    ]
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
    return {
        "matcher": matcher,
        "hooks": [{"type": "command", "command": f'python "{script}"'}],
    }


def _render_guard_tests(test_glob: str) -> str:
    pattern = _glob_to_regex(test_glob).pattern
    return f'''"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Edição de arquivo de TESTE exige aprovação humana (classe de risco
edit_test do harness: nenhuma política automática aprova sozinha). Gerado
de test_glob={test_glob!r}; para mudar, edite .harness/harness.yaml e rode
`harness compile`.
"""
import json
import re
import sys

TEST_PATTERN = re.compile({pattern!r})


def main() -> None:
    data = json.load(sys.stdin)
    raw_path = (data.get("tool_input") or {{}}).get("file_path") or ""
    path = raw_path.replace("\\\\", "/")
    cwd = (data.get("cwd") or "").replace("\\\\", "/").rstrip("/")
    if cwd and path.lower().startswith(cwd.lower() + "/"):
        path = path[len(cwd) + 1:]

    if TEST_PATTERN.match(path):
        decision, reason = "ask", (
            "Arquivo de teste protegido pelo harness (edit_test): "
            "edição exige aprovação humana explícita."
        )
    else:
        decision, reason = "allow", "não é arquivo de teste"

    print(json.dumps({{
        "hookSpecificOutput": {{
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }}
    }}))


if __name__ == "__main__":
    main()
'''


def _render_guard_test_runner(test_command: str) -> str:
    # Tokens do runner (sem flags): "dotnet test -v q" -> ["dotnet", "test"].
    # Matching por SEQUÊNCIA consecutiva, não por primeiro token — senão
    # test_command "dotnet test" marcaria todo "dotnet build"/"dotnet run".
    runner_tokens = [t for t in test_command.split() if not t.startswith("-")]
    return f'''"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Rodar a suíte de teste direto exige atenção humana (disciplina TDD do
harness). Gerado de test_command={test_command!r}; para mudar, edite
.harness/harness.yaml e rode `harness compile`.
"""
import json
import re
import sys

RUNNER_TOKENS = {runner_tokens!r}
# Metacaracteres de shell contam como separador — "pytest&&true" não escapa.
SHELL_SPLIT = re.compile(r"[\\s;&|()<>`$\\"']+")


def _has_runner_sequence(tokens: list) -> bool:
    n = len(RUNNER_TOKENS)
    return n > 0 and any(
        tokens[i:i + n] == RUNNER_TOKENS for i in range(len(tokens) - n + 1)
    )


def main() -> None:
    data = json.load(sys.stdin)
    command = (data.get("tool_input") or {{}}).get("command") or ""

    tokens = [t for t in SHELL_SPLIT.split(command) if t]
    hit = _has_runner_sequence(tokens)
    if hit:
        decision, reason = "ask", (
            "Comando roda a suíte de teste — disciplina TDD do harness pede "
            "confirmação humana (escreva o teste falho antes da implementação)."
        )
    else:
        decision, reason = "allow", "comando não colide com o test runner"

    print(json.dumps({{
        "hookSpecificOutput": {{
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
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

{tdd}2. **Escopo mínimo**: modifique apenas arquivos diretamente ligados à
   tarefa; refactors oportunistas exigem tarefa própria.
3. **Sem segredos** em código, logs ou commits.
4. **Orçamento (orientação)**: alvo de ~{g.budget.max_tokens_per_task:,} tokens
   por tarefa e {g.budget.max_tool_calls_per_task} tool calls. O Claude Code não
   expõe contagem de tokens a hooks — este teto é disciplina, não enforcement;
   se a tarefa estourar muito, pare e replaneje com o humano.
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
    raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
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
    settings_path = target_dir / ".claude" / "settings.json"
    settings: dict[str, Any] = {}
    if settings_path.is_file():
        settings = json.loads(settings_path.read_text(encoding="utf-8"))

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

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
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
            text = pattern.sub(block, text, count=1)
        else:
            text = text.rstrip() + "\n\n" + block + "\n"
    else:
        text = "# AGENTS.md — Diretrizes para Agentes\n\n" + block + "\n"
    agents_path.write_text(text, encoding="utf-8")
    return agents_path
