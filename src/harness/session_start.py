"""Hook SessionStart: injeta estado da sessão anterior no início da sessão.

Fase 2 do roadmap ("Execução Autônoma no Raio de Impacto" — ver ROADMAP.md,
linhas ~193-199, "Hook SessionStart"): a sessão nasce sabendo onde parou —
resumo do progresso (`claude-progress.md`), a feature ativa/pendente
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
- O registro em `settings.json` usa `matcher` para filtrar a origem da
  sessão (`startup`/`resume`/`clear`/`compact`); `"*"` casa qualquer origem —
  usado aqui porque o objetivo (saber onde parou) vale para todo início de
  sessão, não só `startup`.

Merge com `.claude/settings.json`: registra em `hooks.SessionStart` (mesma
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

HOOKS_DIR = ".harness/hooks"
HOOK_FILENAME = "session_start.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
SETTINGS_FILE = ".claude/settings.json"
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
(claude-progress.md), a feature ativa/pendente (.harness/feature_list.json)
e o `git log` recente, para o agente nascer sabendo onde parou.

Schema de saida: hookSpecificOutput.additionalContext (SessionStart nao
bloqueia nada, ao contrario de PreToolUse que usa permissionDecision).
"""
import json
import subprocess
import sys
from pathlib import Path


def _read_feature_summary(cwd: Path) -> str:
    path = cwd / ".harness" / "feature_list.json"
    if not path.is_file():
        return "Nenhum contrato ativo (.harness/feature_list.json nao encontrado)."
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
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
    path = cwd / "claude-progress.md"
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


def build_context(cwd: Path) -> str:
    parts = ["## Estado da sessao anterior (injetado pelo harness)"]
    parts.append(_read_feature_summary(cwd))

    progress = _read_progress(cwd)
    if progress:
        parts.append("### Progresso recente (claude-progress.md)\\n" + progress)

    git_log = _read_git_log(cwd)
    if git_log:
        parts.append("### git log -n 5 --oneline\\n" + git_log)

    return "\\n\\n".join(parts)


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or ".")
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

    command = f'python "{hook_path}"'

    state_path = target_dir / SESSION_STATE_FILE
    state = _load_json(state_path)
    prev_command = state.get(STATE_KEY)

    settings_path = target_dir / SETTINGS_FILE
    settings = _load_json(settings_path)

    hooks = settings.setdefault("hooks", {})
    entries: list[dict[str, Any]] = hooks.get("SessionStart", [])

    def _is_managed(entry: dict[str, Any]) -> bool:
        return any(
            h.get("command") in (prev_command, command)
            for h in entry.get("hooks", [])
        )

    kept_entries = [e for e in entries if not _is_managed(e)]
    kept_entries.append({
        "matcher": "*",
        "hooks": [{"type": "command", "command": command}],
    })
    hooks["SessionStart"] = kept_entries

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Preserva quaisquer outras chaves já presentes (ex.: escritas por
    # session_permissions.py/boundary_guard.py) — só atualiza a nossa.
    state[STATE_KEY] = command
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return hook_path
