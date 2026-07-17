"""Hook Stop: ao encerrar a sessão, avisa se há feature em progresso sem verificação.

Fase 2 do roadmap ("Execução Autônoma no Raio de Impacto"): assim como
`SessionStart` (`session_start.py`) injeta contexto no INÍCIO da sessão, este
módulo cobre o evento `Stop` — disparado quando o Claude termina de
responder. Se existe uma feature com `passes: false` em
`.harness/feature_list.json` E há trabalho não commitado tocando algum dos
`files[]` dessa feature, MAS a verificação (`harness verify <id>`) nunca
rodou ou está desatualizada em relação ao conteúdo atual dos arquivos, o
hook devolve feedback ao AGENTE via `additionalContext` — NÃO bloqueia o
encerramento do processo do Claude Code.

Schema de entrada/saída — CONFIRMADO por consulta via WebFetch à
documentação oficial do Claude Code
(https://code.claude.com/docs/en/hooks, seção "Stop Hook Event Reference"),
NÃO assumido a partir de `PreToolUse`/`SessionStart`:

- Entrada: além dos campos comuns (`session_id`, `transcript_path`, `cwd`,
  `permission_mode`, `hook_event_name`), o evento `Stop` acrescenta
  `last_assistant_message` (texto completo da resposta) e `stop_reason`
  (`"end_turn"` / `"stop_sequence"` / `"max_tokens"` / `"tool_use"`). Este
  módulo só usa `cwd` (mesmo padrão de `session_start.py`).
- Saída: `Stop` tem DUAS formas de controle, distintas de `SessionStart`:
  - Campo de TOPO `decision: "block"` (+ `reason`) — impede o Claude de
    encerrar e força a conversa a continuar. NÃO é o que este hook faz
    (o objetivo explícito é NÃO bloquear o processo).
  - `hookSpecificOutput.additionalContext` (com `hookEventName: "Stop"`) —
    injeta feedback textual para o agente SEM bloquear; a essa forma,
    idêntica em espírito à usada por `SessionStart`, é a usada aqui. A doc
    cita literalmente este exemplo para o caso "providing feedback without
    blocking":
      {"hookSpecificOutput": {"hookEventName": "Stop",
       "additionalContext": "The test suite failed with 3 errors..."}}
  - `Stop` **não suporta `matcher`** ("Stop does not support matchers and
    always fires on every occurrence") — por isso, ao contrário do registro
    em `hooks.SessionStart` (que usa `matcher: "*"`), a entrada registrada
    em `hooks.Stop` não inclui a chave `matcher`.
  - Exit code 0 com JSON válido no stdout é processado para decision
    control; exit code 2 bloquearia (não usado aqui); outros exit codes são
    erro não-bloqueante. Este hook sempre sai com 0.

Merge com `.claude/settings.json`: registra em `hooks.Stop` (mesma técnica
de merge não-destrutivo de `session_start.py`). O estado do que é
gerenciado por ESTE módulo fica em `.harness/compiled-state-session.json`
(mesmo arquivo de `session_start.py`/`session_permissions.py`/
`boundary_guard.py`), sob chave própria `stop_hook_command`, preservando
todas as outras chaves já presentes.

`is_feature_in_progress`/`needs_verification` são expostas como funções
públicas de módulo (importam `harness.verify.compute_files_hash` — nunca
reimplementam o hash) para serem reaproveitadas por uma tarefa futura
(`runtime_audit.py`). O SCRIPT STANDALONE gerado por `render_stop_hook()`
roda fora do pacote instalado (via subprocess, stdlib-only, mesmo padrão de
`session_start.py`) e por isso carrega uma cópia inline da mesma lógica —
não pode importar `harness`.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from harness.verify import EVIDENCE_DIR, compute_files_hash

HOOKS_DIR = ".harness/hooks"
HOOK_FILENAME = "stop_hook.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
SETTINGS_FILE = ".claude/settings.json"
STATE_KEY = "stop_hook_command"


# ---------------------------------------------------------------------------
# lógica pública (importável) — is_feature_in_progress / needs_verification
# ---------------------------------------------------------------------------

def is_feature_in_progress(feature: dict[str, Any], target_dir: Path) -> bool:
    """`True` se `feature` está "em progresso": `passes` é `false` E existe
    trabalho não commitado (`git diff --name-only HEAD -- <files...>`)
    tocando algum caminho de `files[]` da feature.

    Feature sem `files[]` declarado nunca é considerada "em progresso" (não
    há como detectar "trabalho tocando" sem uma lista de caminhos — evita o
    comportamento de `git diff` sem pathspec, que diffaria o repo inteiro).
    Falhas de git (não é repo, git ausente, timeout) resultam em `False` —
    mesma postura defensiva de `session_start.py::_read_git_log`.
    """
    if feature.get("passes", False):
        return False

    files = feature.get("files") or []
    if not files:
        return False

    target_dir = Path(target_dir).resolve()
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", *files],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def needs_verification(feature: dict[str, Any], target_dir: Path) -> bool:
    """`True` se `feature` está em progresso (ver `is_feature_in_progress`) E
    a verificação nunca rodou (`.harness/evidence/<id>.json` ausente) ou está
    desatualizada (`files_hash` gravado != hash atual dos `files[]`, via
    `harness.verify.compute_files_hash` — nunca reimplementado aqui).
    """
    if not is_feature_in_progress(feature, target_dir):
        return False

    target_dir = Path(target_dir).resolve()
    feature_id = feature.get("id", "")
    evidence_path = target_dir / EVIDENCE_DIR / f"{feature_id}.json"
    if not evidence_path.is_file():
        return True

    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return True

    recorded_hash = evidence.get("files_hash")
    current_hash = compute_files_hash(feature.get("files") or [], target_dir)
    return recorded_hash != current_hash


# ---------------------------------------------------------------------------
# render (puro) — conteúdo do script standalone
# ---------------------------------------------------------------------------

def render_stop_hook() -> str:
    """Retorna o código-fonte do hook `Stop` standalone (stdlib only).

    O script gerado não importa `harness` (roda fora do venv do projeto,
    igual a `session_start.py`): usa só `json`, `subprocess`, `hashlib`,
    `sys` e `pathlib`. Contém cópia inline de `is_feature_in_progress` /
    `needs_verification` / `compute_files_hash` — a versão importável fica
    em `harness.stop_hook`/`harness.verify` para reuso por outros módulos do
    pacote (ex.: `runtime_audit.py`).
    """
    return '''"""Hook Stop gerado pelo harness-creator — NAO editar a mao.

Ao encerrar a sessao, verifica se ha alguma feature "em progresso" (passes
false + trabalho nao commitado tocando os files da feature) cuja
verificacao nunca rodou ou esta desatualizada, e devolve feedback ao agente
pedindo para rodar `harness verify <id>` antes de encerrar.

Schema de saida: hookSpecificOutput.additionalContext (Stop NAO bloqueia
via este caminho - o campo de bloqueio seria o `decision: "block"` de topo,
nao usado aqui de proposito).
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

FEATURE_LIST_FILE = ".harness/feature_list.json"
EVIDENCE_DIR = ".harness/evidence"


def compute_files_hash(files, target_dir):
    digest = hashlib.sha256()
    for rel_path in sorted(files):
        digest.update(rel_path.encode("utf-8"))
        digest.update(b"\\n")
        file_path = target_dir / rel_path
        if file_path.is_file():
            digest.update(file_path.read_bytes())
        else:
            digest.update(b"<missing>\\n")
        digest.update(b"\\n")
    return "sha256:" + digest.hexdigest()


def is_feature_in_progress(feature, target_dir):
    if feature.get("passes", False):
        return False

    files = feature.get("files") or []
    if not files:
        return False

    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only", "HEAD", "--", *files],
            cwd=str(target_dir),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def needs_verification(feature, target_dir):
    if not is_feature_in_progress(feature, target_dir):
        return False

    feature_id = feature.get("id", "")
    evidence_path = target_dir / EVIDENCE_DIR / (feature_id + ".json")
    if not evidence_path.is_file():
        return True

    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return True

    recorded_hash = evidence.get("files_hash")
    current_hash = compute_files_hash(feature.get("files") or [], target_dir)
    return recorded_hash != current_hash


def _load_features(cwd):
    path = cwd / FEATURE_LIST_FILE
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return []
    return data.get("features") or []


def build_feedback(cwd):
    pending_ids = []
    for feature in _load_features(cwd):
        if needs_verification(feature, cwd):
            pending_ids.append(feature.get("id", "?"))

    if not pending_ids:
        return None

    ids = ", ".join(pending_ids)
    return (
        "Feature(s) em progresso sem verificacao atualizada: " + ids + ". "
        "Rode `harness verify <id>` antes de encerrar a sessao para gravar "
        "a evidencia em .harness/evidence/<id>.json."
    )


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    cwd = Path(payload.get("cwd") or ".")
    message = build_feedback(cwd)
    if message is None:
        return

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "Stop",
            "additionalContext": message,
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
        return json.loads(path.read_text(encoding="utf-8-sig"))
    return {}


def install_stop_hook(target_dir: Path) -> Path:
    """Grava o hook `Stop` e registra em `.claude/settings.json`.

    Idempotente: rodar duas vezes não duplica a entrada em `hooks.Stop` (a
    entrada anterior gerenciada por este módulo é removida antes de inserir
    a nova, via `.harness/compiled-state-session.json` / chave
    `stop_hook_command`). Ao contrário de `install_session_start`, a
    entrada registrada NÃO leva `matcher` — `Stop` não suporta matcher.
    """
    target_dir = target_dir.resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook_path = hooks_dir / HOOK_FILENAME
    hook_path.write_text(render_stop_hook(), encoding="utf-8")

    command = f'python "{hook_path}"'

    state_path = target_dir / SESSION_STATE_FILE
    state = _load_json(state_path)
    prev_command = state.get(STATE_KEY)

    settings_path = target_dir / SETTINGS_FILE
    settings = _load_json(settings_path)

    hooks = settings.setdefault("hooks", {})
    entries: list[dict[str, Any]] = hooks.get("Stop", [])

    def _is_managed(entry: dict[str, Any]) -> bool:
        return any(
            h.get("command") in (prev_command, command)
            for h in entry.get("hooks", [])
        )

    kept_entries = [e for e in entries if not _is_managed(e)]
    kept_entries.append({
        "hooks": [{"type": "command", "command": command}],
    })
    hooks["Stop"] = kept_entries

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Preserva quaisquer outras chaves já presentes (ex.: escritas por
    # session_start.py/session_permissions.py/boundary_guard.py) — só
    # atualiza a nossa.
    state[STATE_KEY] = command
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return hook_path
