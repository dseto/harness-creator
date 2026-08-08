"""Hook SessionStart: injeta estado da sessão anterior no início da sessão.

Fase 2 do roadmap ("Execução Autônoma no Raio de Impacto" — ver docs/project/ROADMAP.md,
linhas ~193-199, "Hook SessionStart"): a sessão nasce sabendo onde parou —
resumo do progresso (`.harness/progress.md`), a feature ativa/pendente
(`.harness/feature_list.json`) e o `git log` recente — sem o humano precisar
recontar contexto a cada handoff.

Schema de saída — CONFIRMADO por consulta à documentação oficial do Claude
Code (https://code.claude.com/docs/en/hooks, seção SessionStart), não
assumido a partir do formato de `PreToolUse`:

- `PreToolUse` usa `hookSpecificOutput.permissionDecision` /
  `permissionDecisionReason` (bloqueia ou libera a tool call).
- `SessionStart` **não bloqueia nada** — só injeta contexto. O campo
  documentado é `hookSpecificOutput.additionalContext` (a doc também aceita
  texto puro no stdout como via mais simples, mas o formato JSON dá controle
  explícito e evita ambiguidade de parsing pelo host, então é o usado aqui).
  `hookEventName` deve ser `"SessionStart"`, não `"PreToolUse"`.
- O registro em settings usa `matcher` para filtrar a origem da sessão
  (`startup`/`resume`/`clear`/`compact`): `"startup|resume|clear"` — cobre
  todo início real de sessão, mas NÃO `compact` (Onda 2/T-03: com `"*"`, o
  mesmo contexto reinjetava a cada compactação da conversa, não só no
  início — 3 compacts repetiam ~600 tokens cada, achado #5 do laudo de
  simplificação 2026-07-30).

Merge com `.claude/settings.local.json` (machine-local: o comando registrado
leva path absoluto — ver `harness.settings_paths`): registra em
`hooks.SessionStart` (mesma
estrutura de `hooks.PreToolUse` de `compiler.py`, trocando só a chave do
evento). O estado do que é gerenciado por ESTE módulo fica em
`.harness/compiled-state-session.json` — MESMO arquivo usado por
`session_permissions.py`/`boundary_guard.py` (tarefas irmãs) — sob a chave
própria `session_start_hook_command`, nunca em `.harness/compiled-state.json`
(esse é reconstruído do zero por `compiler.py::_write_state` a cada
`harness compile`). Outras chaves já presentes em
`compiled-state-session.json` são preservadas intactas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.hook_launcher import hook_command
from harness.killswitch import DISABLED_CHECK_SRC
from harness.settings_paths import (
    MANAGED_SETTINGS_FILE,
    prepare_managed_settings,
    write_managed_settings,
)

HOOKS_DIR = ".harness/hooks"
HOOK_FILENAME = "session_start.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
SETTINGS_FILE = MANAGED_SETTINGS_FILE
STATE_KEY = "session_start_hook_command"


# ---------------------------------------------------------------------------
# render (puro) — conteúdo do script standalone
# ---------------------------------------------------------------------------

def render_session_start_hook() -> str:
    """Retorna o código-fonte do hook `SessionStart` standalone (stdlib only).

    O script gerado não importa `harness` (roda fora do venv do projeto,
    igual aos hooks `PreToolUse` de `compiler.py`): usa só `json`,
    `subprocess`, `sys` e `pathlib`.
    """
    return '''"""Hook SessionStart gerado pelo harness-creator — NAO editar a mao.

Injeta contexto no inicio da sessao: resumo do progresso
(.harness/progress.md), a feature ativa/pendente (.harness/feature_list.json)
e o `git log` recente, para o agente nascer sabendo onde parou.

Schema de saida: hookSpecificOutput.additionalContext (SessionStart nao
bloqueia nada, ao contrario de PreToolUse que usa permissionDecision).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path


''' + DISABLED_CHECK_SRC + '''


def _read_feature_summary(cwd: Path) -> str:
    path = cwd / ".harness" / "feature_list.json"
    if not path.is_file():
        return "Nenhum contrato ativo (.harness/feature_list.json nao encontrado)."
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return "Nenhum contrato ativo (.harness/feature_list.json invalido)."

    features = data.get("features") or []
    if not features:
        return "Nenhuma feature pendente (contrato sem features)."

    for feature in features:
        if not feature.get("passes", False):
            fid = feature.get("id", "?")
            desc = feature.get("desc") or feature.get("description") or feature.get("title") or ""
            label = f"Feature ativa/pendente: {fid}"
            if desc:
                label += f" - {desc}"
            return label

    return "Nenhuma feature pendente (todas as features do contrato ja passam)."


def _read_progress(cwd: Path) -> str | None:
    path = cwd / ".harness" / "progress.md"
    if not path.is_file():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    lines = text.splitlines()
    tail = lines[-20:]
    joined = "\\n".join(tail).strip()
    return joined or None


def _read_git_log(cwd: Path) -> str | None:
    try:
        proc = subprocess.run(
            ["git", "log", "-n", "5", "--oneline"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = proc.stdout.strip()
    return output or None


def _boundary_guard_drift_warning(cwd: Path) -> str | None:
    """T-03/onda-3 (item 10 restante do laudo): sem isto, o boundary_guard.py
    instalado podia divergir do que a última instalação gravou (edicao a
    mao, ou codigo-fonte mudou sem recompilar) e ninguem percebia ate rodar
    `harness audit` de proposito -- mesma classe de blind-spot do
    kill-switch invisivel (issue #52). So um sinal barato (hash), nao a
    checagem completa: `harness audit` recompila e compara o conteudo
    inteiro; aqui nao da pra fazer isso (dependeria de HarnessConfig/
    pydantic/yaml, e este hook e stdlib-only por design)."""
    state_path = cwd / ".harness" / "compiled-state-session.json"
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    expected_hash = state.get("boundary_guard_content_hash")
    if not expected_hash:
        return None
    hook_path = cwd / ".harness" / "hooks" / "boundary_guard.py"
    try:
        content = hook_path.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(content).hexdigest() == expected_hash:
        return None
    return (
        "## AVISO: boundary_guard.py pode estar desatualizado\\n\\n"
        "O hook instalado em .harness/hooks/boundary_guard.py nao bate com "
        "o hash registrado na ultima instalacao (compile/compile-session) "
        "-- foi editado a mao, ou o codigo-fonte mudou sem recompilar.\\n\\n"
        "Rode `harness audit` para confirmar o drift exato, ou "
        "`harness compile-session` para reinstalar."
    )


def _auto_update(cwd: Path) -> str | None:
    """Sincroniza os artefatos compilados com o pacote instalado e devolve o
    aviso a injetar, ou None quando nada mudou.

    A DECISAO nao mora aqui: este script e stdlib-only e roda com -S (sem
    site-packages), entao nao consegue importar `harness` para saber a versao
    instalada. Ele delega a `python -m harness.autoupdate`, que roda num
    interpretador NOVO -- sem as flags -S/-E com que este hook foi lancado --
    e devolve o veredito em JSON. Duplicar a comparacao aqui dentro deixaria
    a logica fora do alcance da suite.

    Qualquer falha vira None: perder o contexto da sessao anterior e um dano
    maior do que ficar uma versao atras."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "harness.autoupdate", "--dir", str(cwd)],
            capture_output=True,
            text=True,
            timeout=150,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or not data.get("recompiled"):
        return None
    return (
        "## Artefatos do harness atualizados automaticamente\\n\\n"
        "O .harness/ deste projeto tinha sido compilado com a versao "
        + str(data.get("compiled_version")) + " e acabou de ser recompilado para "
        + str(data.get("installed_version")) + ", a versao instalada nesta maquina.\\n\\n"
        "ATENCAO: esta sessao ja carregou os hooks e o settings.local.json "
        "ANTERIORES -- os arquivos novos passam a valer na PROXIMA sessao."
    )


def build_context(cwd: Path) -> str:
    parts = ["## Estado da sessao anterior (injetado pelo harness)"]

    update_notice = _auto_update(cwd)
    if update_notice:
        parts.append(update_notice)

    parts.append(_read_feature_summary(cwd))

    progress = _read_progress(cwd)
    if progress:
        parts.append("### Progresso recente (.harness/progress.md)\\n" + progress)

    git_log = _read_git_log(cwd)
    if git_log:
        parts.append("### git log -n 5 --oneline\\n" + git_log)

    drift_warning = _boundary_guard_drift_warning(cwd)
    if drift_warning:
        parts.append(drift_warning)

    return "\\n\\n".join(parts)


def _read_disabled_info(cwd: Path) -> dict:
    path = cwd / ".harness" / "harness.disabled"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def build_disabled_context(cwd: Path) -> str:
    """US-1: aviso visivel de kill-switch desligado -- antes disso o hook
    retornava sem imprimir nada, e ninguem percebia ate rodar `harness
    status` de proposito (issue #52, 4 dias de no-op silencioso)."""
    info = _read_disabled_info(cwd)
    disabled_at = info.get("disabled_at") or "data desconhecida"
    note = info.get("note") or ""
    note_line = "\\nMotivo registrado: " + note if note else ""
    return (
        "## AVISO: harness desativado (kill-switch)\\n\\n"
        "O harness esta desativado desde " + disabled_at + "." + note_line + "\\n"
        "Enquanto desativado, os hooks de protecao (PreToolUse) fazem no-op "
        "-- nenhuma edicao esta sendo bloqueada.\\n\\n"
        "Para reativar: `harness enable --dir .`\\n\\n"
        "`harness status` continua sendo a fonte de verdade estruturada "
        "deste estado."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or ".")
    if _harness_disabled():
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": build_disabled_context(cwd),
            }
        }))
        return
    context = build_context(cwd)

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }))


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# install (escreve no projeto-alvo)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def install_session_start(target_dir: Path) -> Path:
    """Grava o hook `SessionStart` e registra em `.claude/settings.json`.

    Idempotente: rodar duas vezes não duplica a entrada em
    `hooks.SessionStart` (a entrada anterior gerenciada por este módulo é
    removida antes de inserir a nova, via `.harness/compiled-state-session.json`
    / chave `session_start_hook_command`).
    """
    target_dir = target_dir.resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / HOOK_FILENAME
    hook_path.write_text(render_session_start_hook(), encoding="utf-8")

    # Item 1 do backlog do dogfood venv-Windows: interpretador ABSOLUTO
    # bakeado — ver `harness.hook_launcher`.
    command = hook_command(hook_path)

    state_path = target_dir / SESSION_STATE_FILE
    state = _load_json(state_path)
    prev_command = state.get(STATE_KEY)

    settings_path, settings = prepare_managed_settings(target_dir)

    hooks = settings.setdefault("hooks", {})
    entries: list[dict[str, Any]] = hooks.get("SessionStart", [])

    def _is_managed(entry: dict[str, Any]) -> bool:
        # Casa também por NOME DE ARQUIVO, não só pelo comando exato: desde
        # que o formato do `command` mudou (Item 1 do backlog do dogfood
        # venv-Windows), uma entrada antiga ausente do
        # `compiled-state-session.json` sobreviveria ao merge e o hook
        # rodaria duas vezes por sessão.
        return any(
            h.get("command") in (prev_command, command)
            or HOOK_FILENAME in (h.get("command") or "")
            for h in entry.get("hooks", [])
        )

    kept_entries = [e for e in entries if not _is_managed(e)]
    kept_entries.append({
        "matcher": "startup|resume|clear",
        "hooks": [{"type": "command", "command": command}],
    })
    hooks["SessionStart"] = kept_entries

    write_managed_settings(settings_path, settings)

    # Preserva quaisquer outras chaves já presentes (ex.: escritas por
    # session_permissions.py/boundary_guard.py) — só atualiza a nossa.
    state[STATE_KEY] = command
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return hook_path
