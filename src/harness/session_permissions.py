"""Sessão de trabalho: contrato compilado -> superfície ENUMERADA de permissions.

Fase 2 do roadmap ("Execução Autônoma no Raio de Impacto" — ver docs/project/ROADMAP.md):
a aprovação do contrato (`.harness/feature_list.json`, produzido por
`contract.py`) recompila `.claude/settings.json` com `allow` para a
**superfície completa que o lifecycle usa — enumerada, nunca genérica**.
Qualquer passo do ciclo que caísse no prompt default do Claude Code
quebraria o zero-prompts na prática; por isso a lista é derivada
deterministicamente do contrato e do `.harness/repo-profile.json`
(produzido por `analyzer.py`), nunca de um wildcard como `Bash` puro.

A superfície gerada cobre:
    1. `Edit(<file>)`/`Write(<file>)` para cada arquivo em `files[]` de
       TODAS as features do contrato (união, sem duplicar).
    2. `Bash(<verify_cmd>)` literal para cada `verify_cmd` distinto.
    3. `Bash(<lint/typecheck/build>)` do `repo-profile.json` (`extras`),
       quando o profile os observou.
    4. `Bash(<comando de instalação>)` derivado do `package_manager` do
       profile (ex.: `npm` -> `npm ci`) — a instalação de dependências
       pertence à aprovação do contrato, não ao meio da sessão.
    5. Git local fixo do ritual de handoff: `git status/log/diff/add/commit`.

O que NUNCA entra nesta superfície — o "runtime floor" do ROADMAP — fica de
fora tanto por omissão (a função nunca gera essas regras a partir da lista
fixa acima) quanto por checagem EXPLÍCITA: um filtro final
(`_passes_runtime_floor_filter`) remove do `allow` qualquer entrada que
corresponda ao floor mesmo que tenha vindo do contrato/profile (`verify_cmd`
ou `files[]` maliciosos/mal-formados) — `git push`, rede (curl/wget/npm
publish/pip upload/twine upload/gh release) e arquivo de segredo (`.env`,
`.pem`, `id_rsa`, `*credentials*`). Mesmos critérios de
`harness.boundary_guard` (`is_floor_bash_command`/`is_floor_secret_path`),
importados de lá para as duas camadas nunca divergirem.

Merge com `.claude/settings.json`: este módulo espelha o padrão não-
destrutivo de `compiler.py::_merge_settings`, mas em trilha própria — só
mexe no bucket `permissions.allow` (nunca em `ask`/`deny`) e registra o que
gerenciou em `.harness/compiled-state-session.json`, sob a chave
`managed_session_permissions` — NUNCA em `.harness/compiled-state.json`
(esse arquivo é reconstruído do zero por `compiler.py::_write_state` a cada
`harness compile`, o que apagaria silenciosamente qualquer chave estranha
a `managed_permissions`/`managed_hook_commands`). Outras chaves que já
existirem em `compiled-state-session.json` (escritas por outros
mecanismos, ex.: `boundary_guard.py`/`session_start.py`) são preservadas
intactas — este módulo só lê/escreve a sua própria chave.

Exemplo de saída de `render_session_permissions`:

    {
      "allow": [
        "Edit(src/harness/config.py)",
        "Write(src/harness/config.py)",
        "Bash(pytest tests/test_config.py -q)",
        "Bash(ruff check .)",
        "Bash(npm ci)",
        "Bash(git status)",
        "Bash(git log*)",
        "Bash(git diff*)",
        "Bash(git add*)",
        "Bash(git commit*)",
        "Bash(harness analyze*)",
        "Bash(python -m harness.cli verify*)"
      ]
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness.boundary_guard import (
    is_floor_bash_command,
    is_floor_secret_path,
    load_extra_allowed_commands,
)

FEATURE_LIST_FILE = ".harness/feature_list.json"
REPO_PROFILE_FILE = ".harness/repo-profile.json"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
SETTINGS_FILE = ".claude/settings.json"

# Runtime floor local do ritual de handoff (passos 5/15 do lifecycle) — fixo,
# nunca derivado do contrato/profile. `git push` fica de fora por omissão.
_GIT_LOCAL_ALLOW: list[str] = [
    "Bash(git status)",
    "Bash(git log*)",
    "Bash(git diff*)",
    "Bash(git add*)",
    "Bash(git commit*)",
]

# Subcomandos do proprio harness: mesma liberacao do boundary_guard
# (FIXED_HARNESS_SEQUENCES), espelhada aqui pra settings.json nao mentir
# sobre a superficie (mesmo motivo do _GIT_LOCAL_ALLOW acima).
_HARNESS_SUBCOMMANDS = [
    "compile", "audit", "audit-runtime", "analyze", "preflight",
    "compile-contract", "compile-session", "verify", "team", "review",
    "supervise", "audit-team",
]
_HARNESS_CLI_ALLOW: list[str] = (
    [f"Bash(harness {sub}*)" for sub in _HARNESS_SUBCOMMANDS]
    + [f"Bash(python -m harness.cli {sub}*)" for sub in _HARNESS_SUBCOMMANDS]
)

# package_manager.value (analyzer.py) -> comando de instalação real.
_INSTALL_COMMAND_BY_PACKAGE_MANAGER: dict[str, str] = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
    "pip": "pip install -e .",
}

_EXTRAS_KEYS = ("lint_command", "typecheck_command", "build_command")


def _passes_runtime_floor_filter(entry: str) -> bool:
    """True se `entry` (uma regra já formatada, ex.: "Bash(git push)" ou
    "Edit(.env)") NÃO corresponde ao runtime floor.

    Defesa em profundidade: um contrato malicioso/mal-formado pode ter
    `verify_cmd`/`files[]` que caem no runtime floor (`git push`, rede não
    planejada, arquivo de segredo). O `boundary_guard.py` já nega essas ações
    em runtime, mas sem este filtro o `settings.json` compilado mentiria
    sobre o que é permitido — a primeira camada (permissions nativas do
    Claude Code) ecoaria literalmente `Bash(git push origin main)` ou
    `Edit(.env)` em `allow`. Usa exatamente os mesmos critérios de
    `harness.boundary_guard` (`is_floor_bash_command`/`is_floor_secret_path`),
    para as duas camadas nunca divergirem sobre o que é o floor.
    """
    if entry.startswith("Bash(") and entry.endswith(")"):
        command = entry[len("Bash("):-1]
        # Regras prefixadas (git local, harness CLI, extra_allowed_commands)
        # terminam em "*" — strip antes de checar o floor, senão a tokenização
        # de is_floor_bash_command vê "push*" != "push" e o floor não casa.
        if command.endswith("*"):
            command = command[:-1]
        return not is_floor_bash_command(command)
    if (entry.startswith("Edit(") or entry.startswith("Write(")) and entry.endswith(")"):
        path = entry[entry.index("(") + 1:-1]
        return not is_floor_secret_path(path)
    return True


# ---------------------------------------------------------------------------
# render (puro)
# ---------------------------------------------------------------------------

def render_session_permissions(
    feature_list: dict[str, Any],
    profile: dict[str, Any] | None,
    extra_allowed_commands: list[str] | None = None,
) -> dict[str, list[str]]:
    """Deriva `{"allow": [...]}` do contrato compilado e do repo-profile.

    `feature_list` é o dict já carregado de `.harness/feature_list.json`
    (formato de `contract.py`: `{"features": [{"files", "verify_cmd", ...}]}`).
    `profile` é o dict de `.harness/repo-profile.json` (formato de
    `analyzer.py`) ou `None` quando o profile ainda não foi gerado.
    `extra_allowed_commands` é `governance.extra_allowed_commands` de
    `.harness/harness.yaml` (via `load_extra_allowed_commands`) — cada
    entrada vira `Bash(<comando>*)`, mesmo estilo prefixado de
    `_HARNESS_CLI_ALLOW`/`_GIT_LOCAL_ALLOW`, sujeito ao MESMO
    `_passes_runtime_floor_filter` abaixo (uma entrada de floor declarada
    aqui nunca aparece no `allow` compilado).
    """
    files: list[str] = []
    seen_files: set[str] = set()
    verify_cmds: list[str] = []
    seen_verify: set[str] = set()

    for feature in feature_list.get("features", []):
        for path in feature.get("files", []):
            if path not in seen_files:
                seen_files.add(path)
                files.append(path)

        verify_cmd = feature.get("verify_cmd")
        if verify_cmd and verify_cmd not in seen_verify:
            seen_verify.add(verify_cmd)
            verify_cmds.append(verify_cmd)

    allow: list[str] = []
    for path in files:
        allow.append(f"Edit({path})")
        allow.append(f"Write({path})")
    for verify_cmd in verify_cmds:
        allow.append(f"Bash({verify_cmd})")

    if profile is not None:
        # Nunca `profile.get('extras', {})` sozinho: a chave pode existir
        # com valor `None` explícito, não só estar ausente.
        extras = profile.get("extras") or {}
        for key in _EXTRAS_KEYS:
            entry = extras.get(key)
            if not entry:
                continue
            value = entry.get("value")
            if value:
                allow.append(f"Bash({value})")

        package_manager_entry = profile.get("package_manager") or {}
        package_manager_value = package_manager_entry.get("value")
        install_cmd = (
            _INSTALL_COMMAND_BY_PACKAGE_MANAGER.get(package_manager_value)
            if package_manager_value
            else None
        )
        if install_cmd:
            allow.append(f"Bash({install_cmd})")

    for cmd in extra_allowed_commands or []:
        allow.append(f"Bash({cmd}*)")

    allow.extend(_GIT_LOCAL_ALLOW)
    allow.extend(_HARNESS_CLI_ALLOW)

    # Filtro final: nenhuma entrada do runtime floor sobrevive, não importa
    # de onde veio (verify_cmd, extras do profile, comando de instalação,
    # files[]) — silencioso, sem erro (o contrato pode ter chegado assim por
    # engano; o filtro é defensivo, não deve quebrar o compile).
    allow = [entry for entry in allow if _passes_runtime_floor_filter(entry)]

    return {"allow": allow}


# ---------------------------------------------------------------------------
# compile (escreve no projeto-alvo)
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def compile_session_permissions(target_dir: Path) -> Path:
    """Lê contrato + profile do `target_dir` e mescla `allow` em `.claude/settings.json`.

    Levanta `FileNotFoundError` se `.harness/feature_list.json` não existir
    (pede para rodar `compile-contract` primeiro). A ausência de
    `.harness/repo-profile.json` NÃO é erro — trata como `profile=None`.
    """
    target_dir = target_dir.resolve()

    feature_list_path = target_dir / FEATURE_LIST_FILE
    if not feature_list_path.is_file():
        raise FileNotFoundError(
            f"{feature_list_path} não encontrado — rode 'harness compile-contract' "
            "primeiro para gerar o contrato compilado."
        )
    feature_list = _load_json(feature_list_path)

    profile_path = target_dir / REPO_PROFILE_FILE
    profile = _load_json(profile_path) if profile_path.is_file() else None

    extra_allowed_commands = load_extra_allowed_commands(target_dir)
    rules = render_session_permissions(feature_list, profile, extra_allowed_commands)
    new_allow = rules.get("allow", [])

    state_path = target_dir / SESSION_STATE_FILE
    state = _load_json(state_path) if state_path.is_file() else {}
    prev_allow: set[str] = set(state.get("managed_session_permissions", []))

    settings_path = target_dir / SETTINGS_FILE
    settings: dict[str, Any] = _load_json(settings_path) if settings_path.is_file() else {}

    # --- merge não-destrutivo: remove só o que ERA gerenciado por esta
    # trilha, preserva regras manuais/de outros mecanismos, injeta o novo ---
    permissions = settings.setdefault("permissions", {})
    existing_allow = permissions.get("allow", [])
    kept = [rule for rule in existing_allow if rule not in prev_allow]
    permissions["allow"] = kept + [rule for rule in new_allow if rule not in kept]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    # Preserva quaisquer outras chaves já presentes (ex.: escritas por
    # boundary_guard.py/session_start.py) — só atualiza a nossa.
    state["managed_session_permissions"] = new_allow
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return settings_path
