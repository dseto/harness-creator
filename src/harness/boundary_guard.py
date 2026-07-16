"""Dispatcher único de fronteira: `boundary_guard.py` — Fase 2 do ROADMAP.

Substitui o padrão de N guards por ação (um hook por matcher) por UM único
hook `PreToolUse` que cobre `Edit`, `Write` e `Bash` ao mesmo tempo,
decidindo `allow`/`deny` a partir da superfície do contrato ATIVO
(`.harness/feature_list.json`, compilado por `contract.py`). Resolve a
latência de N subprocessos por tool call que o design anterior (um guard
por ação, em `compiler.py`) pagava.

Duas garantias, nesta ordem, sempre:

1. **Runtime floor** — roda incondicionalmente ANTES de qualquer outra
   verificação, inclusive antes de checar se existe contrato ativo:
   `git push`, publicação/rede não planejada (`curl`, `wget`, `npm publish`,
   `pip upload`, `twine upload`, `gh release`) e escrita em arquivo de
   segredo (`.env`, `.pem`, `id_rsa`, `*credentials*`) NUNCA viram `allow`,
   com ou sem contrato ativo. Não é um guard a mais na cascata — é avaliado
   primeiro, sem exceção, porque "sem contrato → allow" avaliado antes do
   floor abriria uma falha real de segurança (push/segredos liberados em
   qualquer repo sem `feature_list.json`).
2. **Proteção contra enfraquecimento de teste** — arquivo que casa
   `test_glob` (do `repo-profile.json`) só é editável se alguma tarefa do
   contrato ativo o declarar em `files[]`; substitui o `guard_tests.py`
   estático (sempre-`ask`) do `compiler.py` por uma decisão por-tarefa.

O script gerado por `render_boundary_guard()` é standalone (stdlib apenas:
`json`, `re`, `sys` — nada de `import harness`), porque hooks do Claude
Code rodam fora do pacote instalado. `install_boundary_guard()` é quem
escreve esse script em disco e registra o hook em `.claude/settings.json`,
com merge não-destrutivo via `.harness/compiled-state-session.json` — um
arquivo PRÓPRIO deste mecanismo, distinto de `.harness/compiled-state.json`
(que `compiler.py::_write_state` continua reconstruindo do zero a cada
`harness compile`; escrever a chave nova ali seria apagada na próxima
compilação do mecanismo antigo). `compiled-state-session.json` é
COMPARTILHADO com os hooks irmãos de sessão (`session_permissions.py`,
`session_start.py`): cada um grava sob sua própria chave, sempre
preservando as chaves alheias já presentes no arquivo.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HOOKS_DIR = ".harness/hooks"
BOUNDARY_HOOK_FILENAME = "boundary_guard.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
BOUNDARY_STATE_KEY = "boundary_guard_hook_command"
LEGACY_GUARD_TESTS_MARKER = "guard_tests.py"


# ---------------------------------------------------------------------------
# Runtime floor (Python real, IMPORTÁVEL) — mesmos padrões usados dentro do
# script standalone gerado por `render_boundary_guard()` mais abaixo. O hook
# standalone não pode importar `harness.*` (roda fora do pacote instalado via
# subprocess), por isso mantém sua PRÓPRIA cópia inline dos mesmos critérios;
# esta versão importável existe para que outros módulos do pacote (hoje,
# `session_permissions.py`) apliquem exatamente o mesmo critério em vez de
# divergir com uma segunda implementação. Se um dos dois lados mudar, o outro
# tem que acompanhar.
_SHELL_SPLIT = re.compile(r"[\s;&|()<>`$\"']+")

FLOOR_BASH_SEQUENCES: list[list[str]] = [
    ["git", "push"],
    ["curl"],
    ["wget"],
    ["npm", "publish"],
    ["pip", "upload"],
    ["twine", "upload"],
    ["gh", "release"],
]


def _tokenize_command(command: str) -> list[str]:
    return [t for t in _SHELL_SPLIT.split(command or "") if t]


def _has_sequence(tokens: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


def is_floor_bash_command(command: str) -> bool:
    """True se `command` casa alguma sequência do runtime floor (git push,
    curl, wget, npm publish, pip upload, twine upload, gh release)."""
    tokens = _tokenize_command(command)
    return any(_has_sequence(tokens, seq) for seq in FLOOR_BASH_SEQUENCES)


def is_floor_secret_path(path: str) -> bool:
    """True se `path` é um arquivo de segredo do runtime floor (.env, .pem,
    id_rsa, ou nome contendo 'credentials')."""
    lower = (path or "").replace("\\", "/").lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.endswith(".env")
        or lower.endswith(".pem")
        or lower.endswith("id_rsa")
        or "credentials" in basename
    )


# ---------------------------------------------------------------------------
# Render (puro) — devolve o CÓDIGO-FONTE do hook standalone
# ---------------------------------------------------------------------------

def render_boundary_guard() -> str:
    """Devolve o código-fonte (string) do hook `PreToolUse` standalone.

    O script gerado lê o payload JSON do stdin e decide `allow`/`deny` para
    os matchers `Edit`, `Write` e `Bash`, na ORDEM descrita no docstring do
    módulo. Não importa nada de `harness.*` — stdlib apenas.
    """
    return '''"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Dispatcher único de fronteira (Edit/Write/Bash) para a superfície do
contrato ativo (.harness/feature_list.json). Gerado por
harness.boundary_guard.render_boundary_guard(); para mudar o
comportamento, edite o contrato/profile e rode a instalação novamente —
não edite este arquivo diretamente.

ORDEM DE AVALIAÇÃO (não reordenar): o runtime floor roda incondicionalmente
antes de qualquer checagem de contrato — mesmo sem .harness/feature_list.json
no repo, git push e escrita em arquivo de segredo continuam DENY.
"""
import json
import re
import sys

# Metacaracteres de shell contam como separador — "git push&&true" não escapa.
SHELL_SPLIT = re.compile(r"[\\s;&|()<>`$\\"']+")

# --- runtime floor: nunca vira allow, com ou sem contrato ativo ---
FLOOR_BASH_SEQUENCES = [
    ["git", "push"],
    ["curl"],
    ["wget"],
    ["npm", "publish"],
    ["pip", "upload"],
    ["twine", "upload"],
    ["gh", "release"],
]

# --- comandos git locais sempre liberados quando há contrato ativo ---
FIXED_GIT_SEQUENCES = [
    ["git", "status"],
    ["git", "log"],
    ["git", "diff"],
    ["git", "add"],
    ["git", "commit"],
]

FEATURE_LIST_PATH = ".harness/feature_list.json"
PROFILE_PATH = ".harness/repo-profile.json"

# package_manager.value (analyzer.py) -> comando de instalação EXATO. Mesmo
# mapeamento de harness.session_permissions/harness.templates: o valor bruto
# do profile (ex.: "npm") NUNCA vira um comando permitido por si só - isso
# liberaria qualquer subcomando ("npm run x", "npm exec"), nao so a instalacao.
INSTALL_COMMAND_BY_PACKAGE_MANAGER = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
}


def _glob_to_regex(glob):
    """Mesmo algoritmo de harness.verification.tdd_loop._glob_to_regex,
    copiado inline (o hook não pode importar a lib)."""
    escaped = re.escape(glob.replace("\\\\", "/"))
    escaped = escaped.replace(r"\\*\\*/", "(?:.*/)?")
    escaped = escaped.replace(r"\\*\\*", ".*")
    escaped = escaped.replace(r"\\*", "[^/]*")
    escaped = escaped.replace(r"\\?", "[^/]")
    return re.compile("^" + escaped + "$")


def _resolve_path(raw_path, cwd):
    path = (raw_path or "").replace("\\\\", "/")
    cwd_norm = (cwd or "").replace("\\\\", "/").rstrip("/")
    if cwd_norm and path.lower().startswith(cwd_norm.lower() + "/"):
        path = path[len(cwd_norm) + 1:]
    return path


def _is_secret_path(path):
    lower = path.lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.endswith(".env")
        or lower.endswith(".pem")
        or lower.endswith("id_rsa")
        or "credentials" in basename
    )


def _tokenize(command):
    return [t for t in SHELL_SPLIT.split(command or "") if t]


def _has_sequence(tokens, seq):
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


def _matches_any_sequence(tokens, sequences):
    return any(_has_sequence(tokens, seq) for seq in sequences)


def _load_json(cwd, relative):
    base = cwd or "."
    path_str = relative
    try:
        import os
        full = os.path.join(base, relative)
        with open(full, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _profile_entry_value(profile, key):
    if not isinstance(profile, dict):
        return None
    entry = profile.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _profile_extra_value(profile, key):
    if not isinstance(profile, dict):
        return None
    extras = profile.get("extras")
    if not isinstance(extras, dict):
        return None
    entry = extras.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _collect_allowed_files(feature_list):
    allowed = set()
    for feat in (feature_list or {}).get("features", []) or []:
        for f in feat.get("files") or []:
            allowed.add(str(f).replace("\\\\", "/"))
    return allowed


def _collect_allowed_bash_commands(feature_list, profile):
    commands = []
    for feat in (feature_list or {}).get("features", []) or []:
        vc = feat.get("verify_cmd")
        if vc:
            commands.append(vc)
    for key in ("lint_command", "typecheck_command", "build_command"):
        value = _profile_extra_value(profile, key)
        if value:
            commands.append(value)
    package_manager_value = _profile_entry_value(profile, "package_manager")
    install_cmd = (
        INSTALL_COMMAND_BY_PACKAGE_MANAGER.get(package_manager_value)
        if package_manager_value
        else None
    )
    if install_cmd:
        commands.append(install_cmd)
    return commands


def _evaluate_file(path, cwd):
    if _is_secret_path(path):
        return "deny", (
            "runtime floor: escrita em arquivo de segredo (.env/.pem/id_rsa/"
            "credentials) e bloqueio incondicional, independente de contrato ativo"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    allowed_files = _collect_allowed_files(feature_list)
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")

    if test_glob:
        pattern = _glob_to_regex(test_glob)
        if pattern.match(path):
            if path in allowed_files:
                return "allow", "arquivo de teste declarado em files[] de uma tarefa do contrato ativo"
            return "deny", (
                "arquivo de teste protegido: nenhuma tarefa do contrato ativo declara "
                "este arquivo em files[] - enfraquecimento de teste fora do escopo aprovado"
            )

    if path in allowed_files:
        return "allow", "arquivo declarado em files[] de uma tarefa do contrato ativo"
    return "deny", (
        "arquivo fora da superficie do contrato ativo (nenhuma tarefa declara este "
        "path em files[]); replaneje via /harness-creator:plan se o escopo mudou"
    )


def _evaluate_bash(command, cwd):
    tokens = _tokenize(command)

    if _matches_any_sequence(tokens, FLOOR_BASH_SEQUENCES):
        return "deny", (
            "runtime floor: comando de push/publicacao/rede nao planejado - "
            "bloqueio incondicional, independente de contrato ativo"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"

    profile = _load_json(cwd, PROFILE_PATH)
    allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    allowed_sequences = FIXED_GIT_SEQUENCES + [_tokenize(c) for c in allowed_commands]

    if _matches_any_sequence(tokens, allowed_sequences):
        return "allow", (
            "comando declarado na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local)"
        )
    return "deny", (
        "comando fora da superficie compilada do contrato "
        "(verify_cmd/lint/typecheck/build/install/git local); replaneje via "
        "/harness-creator:plan se precisar de outro comando"
    )


def main() -> None:
    data = json.load(sys.stdin)
    tool_name = data.get("tool_name") or ""
    tool_input = data.get("tool_input") or {}
    cwd = data.get("cwd") or ""

    if tool_name in ("Edit", "Write"):
        path = _resolve_path(tool_input.get("file_path") or "", cwd)
        decision, reason = _evaluate_file(path, cwd)
    elif tool_name == "Bash":
        command = tool_input.get("command") or ""
        decision, reason = _evaluate_bash(command, cwd)
    else:
        decision, reason = "allow", "ferramenta fora do escopo do boundary_guard"

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
'''


# ---------------------------------------------------------------------------
# Apply (escreve no projeto-alvo) — sem importar compiler.py
# ---------------------------------------------------------------------------

def _load_json_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def install_boundary_guard(target_dir: Path) -> Path:
    """Instala `boundary_guard.py` como o único hook `PreToolUse` de
    Edit/Write/Bash em `target_dir`.

    Escreve `target_dir/.harness/hooks/boundary_guard.py` e registra o hook
    em `target_dir/.claude/settings.json` (matcher `"Edit|Write|Bash"`).
    Merge não-destrutivo via `target_dir/.harness/compiled-state-session.json`
    (chave própria `boundary_guard_hook_command`, preservando outras chaves
    já presentes — o arquivo é compartilhado com hooks irmãos de sessão).

    Também remove, de `hooks.PreToolUse`, qualquer entrada legada cujo
    `command` referencie o `guard_tests.py` gerado pelo `compiler.py`
    (mecanismo antigo, v0.10.0): o `boundary_guard.py` já cobre a proteção
    de teste (por tarefa do contrato), e manter os dois ativos faria o hook
    antigo disparar `ask` (auto-negado em modo headless) para o mesmo Edit
    que este já libera por `allow`. Nenhuma outra entrada de
    `hooks.PreToolUse` é tocada (ex.: `guard_test_runner.py`).
    """
    target_dir = target_dir.resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / BOUNDARY_HOOK_FILENAME
    script_path.write_text(render_boundary_guard(), encoding="utf-8")

    command = f'python "{script_path}"'

    settings_path = target_dir / ".claude" / "settings.json"
    settings: dict[str, Any] = _load_json_state(settings_path)

    state_path = target_dir / SESSION_STATE_FILE
    state: dict[str, Any] = _load_json_state(state_path)
    old_command = state.get(BOUNDARY_STATE_KEY)

    hooks = settings.setdefault("hooks", {})
    pre = hooks.get("PreToolUse", [])

    def _is_old_managed(entry: dict[str, Any]) -> bool:
        return old_command is not None and any(
            h.get("command") == old_command for h in entry.get("hooks", [])
        )

    def _is_legacy_guard_tests(entry: dict[str, Any]) -> bool:
        return any(
            LEGACY_GUARD_TESTS_MARKER in (h.get("command") or "")
            for h in entry.get("hooks", [])
        )

    kept_entries = [
        e for e in pre if not _is_old_managed(e) and not _is_legacy_guard_tests(e)
    ]
    new_entry = {
        "matcher": "Edit|Write|Bash",
        "hooks": [{"type": "command", "command": command}],
    }
    hooks["PreToolUse"] = kept_entries + [new_entry]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    state[BOUNDARY_STATE_KEY] = command
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return script_path
