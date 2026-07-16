"""Testes do hook Stop: aviso de feature em progresso sem verificação atualizada."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.stop_hook import (
    HOOK_FILENAME,
    HOOKS_DIR,
    STATE_KEY,
    install_stop_hook,
    is_feature_in_progress,
    needs_verification,
    render_stop_hook,
)
from harness.verify import compute_files_hash


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "a@b.com"], cwd=str(tmp_path), capture_output=True, text=True, check=True
    )
    subprocess.run(["git", "config", "user.name", "a"], cwd=str(tmp_path), capture_output=True, text=True, check=True)


def _commit_all(tmp_path: Path, message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), capture_output=True, text=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", message], cwd=str(tmp_path), capture_output=True, text=True, check=True
    )


def _write_feature_list(tmp_path: Path, features: list[dict]) -> None:
    path = tmp_path / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"contract": "exemplo", "features": features}), encoding="utf-8")


def _write_hook_script(tmp_path: Path) -> Path:
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / "stop_hook.py"
    script_path.write_text(render_stop_hook(), encoding="utf-8")
    return script_path


def _run_hook(script_path: Path, cwd: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(script_path)],
        input=json.dumps({"cwd": str(cwd)}),
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def _make_feature_with_uncommitted_diff(tmp_path: Path, feature_id: str = "T-01") -> dict:
    """Cria um repo git com um arquivo commitado e depois modificado (diff não commitado)."""
    _init_git_repo(tmp_path)
    target_file = tmp_path / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("value = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "commit inicial")

    target_file.write_text("value = 2\n", encoding="utf-8")  # não commitado

    return {
        "id": feature_id,
        "desc": "feature em progresso",
        "files": ["src/example.py"],
        "verify_cmd": "pytest",
        "passes": False,
    }


# ---------------- render_stop_hook / execução do script (comportamento fim-a-fim) ----------------

def test_no_feature_list_signals_nothing(tmp_path: Path) -> None:
    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_all_features_passing_signals_nothing(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    _write_feature_list(tmp_path, [{"id": "T-01", "files": [], "verify_cmd": "pytest", "passes": True}])
    _commit_all(tmp_path, "commit inicial")

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_feature_pending_without_uncommitted_diff_signals_nothing(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    target_file = tmp_path / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("value = 1\n", encoding="utf-8")
    _write_feature_list(
        tmp_path, [{"id": "T-01", "files": ["src/example.py"], "verify_cmd": "pytest", "passes": False}]
    )
    _commit_all(tmp_path, "commit inicial")  # nada fica não commitado depois disso

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_feature_in_progress_without_evidence_signals(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)

    assert output != ""
    payload = json.loads(output)
    context = payload["hookSpecificOutput"]["additionalContext"]
    assert payload["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "T-01" in context
    assert "harness verify" in context


def test_feature_in_progress_with_up_to_date_evidence_signals_nothing(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    evidence_dir = tmp_path / ".harness" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    current_hash = compute_files_hash(feature["files"], tmp_path)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({
            "feature_id": "T-01",
            "verify_cmd": "pytest",
            "recorded_at": "2026-07-16T12:00:00+00:00",
            "exit_code": 0,
            "files_hash": current_hash,
        }),
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output == ""


def test_feature_in_progress_with_stale_evidence_signals(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    _write_feature_list(tmp_path, [feature])

    evidence_dir = tmp_path / ".harness" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({
            "feature_id": "T-01",
            "verify_cmd": "pytest",
            "recorded_at": "2026-07-16T12:00:00+00:00",
            "exit_code": 0,
            "files_hash": "sha256:desatualizado",
        }),
        encoding="utf-8",
    )

    script_path = _write_hook_script(tmp_path)
    output = _run_hook(script_path, tmp_path)
    assert output != ""
    context = json.loads(output)["hookSpecificOutput"]["additionalContext"]
    assert "T-01" in context


# ---------------- is_feature_in_progress / needs_verification (chamadas diretas) ----------------

def test_is_feature_in_progress_true_when_passes_false_and_uncommitted_diff(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    assert is_feature_in_progress(feature, tmp_path) is True


def test_is_feature_in_progress_false_when_passes_true(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    feature["passes"] = True
    assert is_feature_in_progress(feature, tmp_path) is False


def test_is_feature_in_progress_false_when_no_files_declared(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    (tmp_path / "a.txt").write_text("x", encoding="utf-8")
    _commit_all(tmp_path, "inicial")
    (tmp_path / "a.txt").write_text("y", encoding="utf-8")

    feature = {"id": "T-01", "files": [], "verify_cmd": "pytest", "passes": False}
    assert is_feature_in_progress(feature, tmp_path) is False


def test_is_feature_in_progress_false_when_no_uncommitted_diff(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    target_file = tmp_path / "src" / "example.py"
    target_file.parent.mkdir(parents=True, exist_ok=True)
    target_file.write_text("value = 1\n", encoding="utf-8")
    _commit_all(tmp_path, "inicial")

    feature = {"id": "T-01", "files": ["src/example.py"], "verify_cmd": "pytest", "passes": False}
    assert is_feature_in_progress(feature, tmp_path) is False


def test_needs_verification_true_when_evidence_missing(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    assert needs_verification(feature, tmp_path) is True


def test_needs_verification_false_when_evidence_hash_matches(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    evidence_dir = tmp_path / ".harness" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    current_hash = compute_files_hash(feature["files"], tmp_path)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({"feature_id": "T-01", "files_hash": current_hash}), encoding="utf-8"
    )
    assert needs_verification(feature, tmp_path) is False


def test_needs_verification_true_when_evidence_hash_stale(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    evidence_dir = tmp_path / ".harness" / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "T-01.json").write_text(
        json.dumps({"feature_id": "T-01", "files_hash": "sha256:desatualizado"}), encoding="utf-8"
    )
    assert needs_verification(feature, tmp_path) is True


def test_needs_verification_false_when_not_in_progress(tmp_path: Path) -> None:
    feature = _make_feature_with_uncommitted_diff(tmp_path)
    feature["passes"] = True
    assert needs_verification(feature, tmp_path) is False


# ---------------- install_stop_hook ----------------

def test_install_writes_hook_file(tmp_path: Path) -> None:
    hook_path = install_stop_hook(tmp_path)
    assert hook_path.is_file()
    assert hook_path == tmp_path / HOOKS_DIR / HOOK_FILENAME
    assert "Stop" in hook_path.read_text(encoding="utf-8")


def test_install_registers_hook_under_stop_event_without_matcher(tmp_path: Path) -> None:
    install_stop_hook(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Stop" in settings["hooks"]
    assert "PreToolUse" not in settings["hooks"]
    entry = settings["hooks"]["Stop"][0]
    assert "matcher" not in entry
    assert "stop_hook.py" in entry["hooks"][0]["command"]


def test_install_is_idempotent_no_duplicate_entries(tmp_path: Path) -> None:
    install_stop_hook(tmp_path)
    install_stop_hook(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert len(settings["hooks"]["Stop"]) == 1


def test_install_records_state_under_own_key(tmp_path: Path) -> None:
    install_stop_hook(tmp_path)
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert STATE_KEY in state
    assert "stop_hook.py" in state[STATE_KEY]


def test_install_preserves_sibling_state_keys(tmp_path: Path) -> None:
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "managed_session_permissions": ["Bash(git status)"],
        "session_start_hook_command": "python .harness/hooks/session_start.py",
        "boundary_guard_hook_command": "python .harness/hooks/boundary_guard.py",
    }), encoding="utf-8")

    install_stop_hook(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["managed_session_permissions"] == ["Bash(git status)"]
    assert state["session_start_hook_command"] == "python .harness/hooks/session_start.py"
    assert state["boundary_guard_hook_command"] == "python .harness/hooks/boundary_guard.py"
    assert STATE_KEY in state


def test_install_preserves_manual_settings_and_other_hook_events(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    (claude_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(git status)"]},
        "hooks": {
            "SessionStart": [{"matcher": "*", "hooks": [{"type": "command", "command": "python session_start.py"}]}],
        },
    }), encoding="utf-8")

    install_stop_hook(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["permissions"]["allow"] == ["Bash(git status)"]
    assert len(settings["hooks"]["SessionStart"]) == 1
    assert "Stop" in settings["hooks"]
