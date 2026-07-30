"""Testes da fronteira machine-local do output compilado (P0 do laudo
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`).

Destino único do output gerenciado (`.claude/settings.local.json`) e
`.gitignore` tool-owned em `.claude/` e `.harness/`. O `.claude/settings.json`
do time nunca é lido nem escrito — o produto é pré-produção, a instalação é
sempre do zero, e não existe base instalada para migrar.
"""

from __future__ import annotations

import json
from pathlib import Path

from harness.settings_paths import (
    CLAUDE_GITIGNORE_LINES,
    HARNESS_GITIGNORE_LINES,
    MANAGED_SETTINGS_FILE,
    TEAM_SETTINGS_FILE,
    ensure_machine_local_gitignores,
    managed_settings_path,
    prepare_managed_settings,
    team_settings_path,
    write_managed_settings,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _managed_hook_command(target: Path, name: str = "boundary_guard.py") -> str:
    return f'python "{target / ".harness" / "hooks" / name}"'


# ---------------- destino do output gerenciado ----------------

def test_managed_destination_is_the_machine_local_file() -> None:
    """F1 do laudo: o output do harness carrega path absoluto desta máquina —
    tem que nascer no arquivo que o Claude Code já trata como machine-local,
    nunca no `settings.json` que o time versiona."""
    assert MANAGED_SETTINGS_FILE == ".claude/settings.local.json"
    assert TEAM_SETTINGS_FILE == ".claude/settings.json"


def test_managed_and_team_paths_are_distinct(tmp_path: Path) -> None:
    assert managed_settings_path(tmp_path) == tmp_path / ".claude" / "settings.local.json"
    assert team_settings_path(tmp_path) == tmp_path / ".claude" / "settings.json"


def test_prepare_returns_empty_dict_when_nothing_compiled_yet(tmp_path: Path) -> None:
    path, settings = prepare_managed_settings(tmp_path)
    assert path == managed_settings_path(tmp_path)
    assert settings == {}


def test_prepare_reads_back_what_write_wrote(tmp_path: Path) -> None:
    path, _ = prepare_managed_settings(tmp_path)
    write_managed_settings(path, {"hooks": {"Stop": []}, "model": "opus"})

    _, settings = prepare_managed_settings(tmp_path)
    assert settings["model"] == "opus"


# ---------------- .gitignore tool-owned ----------------

def test_ensure_creates_both_tool_owned_gitignores(tmp_path: Path) -> None:
    """Itens 2 e 3: o ignore vem do produto, não do gitignore global da
    máquina do usuário (hoje o único motivo de o dogfood parecer limpo)."""
    written = ensure_machine_local_gitignores(tmp_path)

    claude_ignore = tmp_path / ".claude" / ".gitignore"
    harness_ignore = tmp_path / ".harness" / ".gitignore"
    assert set(written) == {claude_ignore, harness_ignore}

    claude_lines = claude_ignore.read_text(encoding="utf-8").split()
    assert "settings.local.json" in claude_lines

    harness_lines = harness_ignore.read_text(encoding="utf-8").split()
    for expected in ("harness.disabled", "compiled-state.json",
                     "compiled-state-session.json", "hooks/"):
        assert expected in harness_lines


def test_ensure_is_idempotent(tmp_path: Path) -> None:
    ensure_machine_local_gitignores(tmp_path)
    before = (tmp_path / ".harness" / ".gitignore").read_text(encoding="utf-8")

    assert ensure_machine_local_gitignores(tmp_path) == []
    assert (tmp_path / ".harness" / ".gitignore").read_text(encoding="utf-8") == before


def test_ensure_preserves_lines_the_user_already_had(tmp_path: Path) -> None:
    harness_ignore = tmp_path / ".harness" / ".gitignore"
    harness_ignore.parent.mkdir(parents=True, exist_ok=True)
    harness_ignore.write_text("minha-regra.txt\nharness.disabled\n", encoding="utf-8")

    ensure_machine_local_gitignores(tmp_path)

    lines = harness_ignore.read_text(encoding="utf-8").split()
    assert "minha-regra.txt" in lines
    assert lines.count("harness.disabled") == 1          # não duplica o que já existia
    assert "compiled-state.json" in lines                # e acrescenta o que faltava


def test_gitignore_line_sets_are_exposed_for_audit() -> None:
    assert "settings.local.json" in CLAUDE_GITIGNORE_LINES
    assert "hooks/" in HARNESS_GITIGNORE_LINES


# ---------------- T-07/onda-1: poda de allow sombreado por regra nua ----------------

def test_write_prunes_bash_pattern_entries_shadowed_by_bare_bash(tmp_path: Path) -> None:
    """Duas rotinas de merge independentes (compiler.py/session_permissions.py)
    escrevem `allow` sem se enxergar — nenhuma reconhece uma entrada da outra
    como 'gerenciada', então `Bash(git status)` nunca era reconhecida como
    redundante quando `Bash` nu já cobre qualquer comando. O sink único
    (`write_managed_settings`) poda isso independente de quem escreveu o quê."""
    path = tmp_path / ".claude" / "settings.local.json"
    write_managed_settings(path, {
        "permissions": {"allow": [
            "Bash", "Bash(git status)", "Bash(git log*)", "Read", "Grep",
        ]},
    })

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash", "Read", "Grep"]


def test_write_keeps_manual_entry_without_a_bare_rule_present(tmp_path: Path) -> None:
    """Sem `Bash` nu na lista, uma entrada específica é regra MANUAL genuína
    — nunca podada. A poda só reconhece redundância estrita, não decide por
    inferência o que o usuário quis dizer."""
    path = tmp_path / ".claude" / "settings.local.json"
    write_managed_settings(path, {
        "permissions": {"allow": ["Bash(npm run build)", "Edit(src/main.py)"]},
    })

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(npm run build)", "Edit(src/main.py)"]


def test_write_does_not_touch_ask_or_deny_lists(tmp_path: Path) -> None:
    """A poda é escopada a `allow` — `ask`/`deny` não têm o mesmo conceito de
    'regra nua cobre tudo' (WebFetch/WebSearch continuam sempre `ask`)."""
    path = tmp_path / ".claude" / "settings.local.json"
    write_managed_settings(path, {
        "permissions": {
            "allow": ["Bash", "Bash(pytest -q)"],
            "ask": ["WebFetch", "Bash(curl *)"],
        },
    })

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash"]
    assert settings["permissions"]["ask"] == ["WebFetch", "Bash(curl *)"]


def test_write_is_a_noop_when_there_is_nothing_to_prune(tmp_path: Path) -> None:
    path = tmp_path / ".claude" / "settings.local.json"
    write_managed_settings(path, {"permissions": {"allow": ["Read", "Grep", "Glob"]}})

    settings = json.loads(path.read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Read", "Grep", "Glob"]
