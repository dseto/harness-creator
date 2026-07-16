"""Testes do hook SessionStart: injeção de estado (progress + feature + git log)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.session_start import (
    HOOK_FILENAME,
    HOOKS_DIR,
    STATE_KEY,
    install_session_start,
    render_session_start_hook,
)

FEATURE_LIST_PENDING = {
    "contract": "exemplo-feature",
    "features": [
        {"id": "T-01", "desc": "Ja concluida", "files": [], "verify_cmd": "pytest", "passes": True},
        {"id": "T-02", "desc": "Ainda pendente", "files": [], "verify_cmd": "pytest", "passes": False},
    ],
}


def _write_hook_script(tmp_path: Path) -> Path:
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / "session_start.py"
    script_path.write_text(render_session_start_hook(), encoding="utf-8")
    return script_path


def _run_hook(script_path: Path, cwd: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _context(payload: dict) -> str:
    return payload["hookSpecificOutput"]["additionalContext"]


# ---------------- render_session_start_hook / execução do script ----------------

def test_no_feature_list_mentions_no_active_contract(tmp_path: Path) -> None:
    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)

    assert payload["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "Nenhum contrato ativo" in _context(payload)


def test_feature_list_with_pending_feature_cites_it(tmp_path: Path) -> None:
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps(FEATURE_LIST_PENDING), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    context = _context(payload)

    assert "T-02" in context
    assert "Ainda pendente" in context
    assert "Feature ativa/pendente: T-01" not in context


def test_feature_list_all_passing_says_no_pending_feature(tmp_path: Path) -> None:
    all_pass = {
        "features": [
            {"id": "T-01", "desc": "ok", "files": [], "verify_cmd": "pytest", "passes": True},
        ]
    }
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps(all_pass), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "Nenhuma feature pendente" in _context(payload)


def test_empty_feature_list_says_no_pending_feature(tmp_path: Path) -> None:
    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_list_path.parent.mkdir(parents=True, exist_ok=True)
    feature_list_path.write_text(json.dumps({"features": []}), encoding="utf-8")

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "Nenhuma feature pendente" in _context(payload)


def test_progress_file_content_appears_in_context(tmp_path: Path) -> None:
    progress_path = tmp_path / "claude-progress.md"
    progress_path.write_text(
        "# Progresso\n" + "\n".join(f"linha {i}" for i in range(30)) + "\nMARCA-UNICA-XYZ",
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "MARCA-UNICA-XYZ" in _context(payload)


def test_no_progress_file_does_not_break(tmp_path: Path) -> None:
    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "Nenhum contrato ativo" in _context(payload)


def test_git_log_appears_when_repo_has_commits(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(["git", "commit", "-m", "commit inicial unico"], cwd=str(tmp_path), capture_output=True, text=True, check=True)

    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    assert "commit inicial unico" in _context(payload)


def test_no_git_repo_does_not_break_session(tmp_path: Path) -> None:
    script_path = _write_hook_script(tmp_path)
    payload = _run_hook(script_path, tmp_path)
    # Não quebra: ainda retorna JSON válido com o resto do contexto.
    assert "Nenhum contrato ativo" in _context(payload)


# ---------------- install_session_start ----------------

def test_install_writes_hook_file(tmp_path: Path) -> None:
    hook_path = install_session_start(tmp_path)
    assert hook_path.is_file()
    assert hook_path == tmp_path / HOOKS_DIR / HOOK_FILENAME
    assert "SessionStart" in hook_path.read_text(encoding="utf-8")


def test_install_registers_hook_under_session_start_event(tmp_path: Path) -> None:
    install_session_start(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "SessionStart" in settings["hooks"]
    assert "PreToolUse" not in settings["hooks"]
    entry = settings["hooks"]["SessionStart"][0]
    assert "session_start.py" in entry["hooks"][0]["command"]


def test_install_is_idempotent_no_duplicate_entries(tmp_path: Path) -> None:
    install_session_start(tmp_path)
    install_session_start(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["SessionStart"]) == 1


def test_install_records_state_under_own_key(tmp_path: Path) -> None:
    install_session_start(tmp_path)
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert STATE_KEY in state
    assert "session_start.py" in state[STATE_KEY]


def test_install_preserves_sibling_state_keys(tmp_path: Path) -> None:
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "managed_session_permissions": ["Bash(git status)"],
        "boundary_guard_hook_command": "python .harness/hooks/boundary_guard.py",
    }), encoding="utf-8")

    install_session_start(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["managed_session_permissions"] == ["Bash(git status)"]
    assert state["boundary_guard_hook_command"] == "python .harness/hooks/boundary_guard.py"
    assert STATE_KEY in state


def test_install_preserves_manual_settings_and_other_hook_events(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Write", "hooks": [{"type": "command", "command": "python x.py"}]}],
        },
    }), encoding="utf-8")

    install_session_start(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(git status)"]
    assert len(settings["hooks"]["PreToolUse"]) == 1
    assert "SessionStart" in settings["hooks"]
