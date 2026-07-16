"""Testes do boundary_guard (Fase 2): dispatcher único de fronteira
(Edit/Write/Bash) a partir da superfície do contrato ativo."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.boundary_guard import (
    BOUNDARY_STATE_KEY,
    SESSION_STATE_FILE,
    install_boundary_guard,
)


def _run_hook(script: Path, payload: dict, cwd: Path | None = None) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def _write_feature_list(target: Path, features: list[dict]) -> None:
    path = target / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"contract": "test", "compiled_at": "now", "features": features}),
        encoding="utf-8",
    )


def _write_profile(target: Path, **overrides) -> None:
    path = target / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "languages": [{"value": "python", "evidence": "x", "confidence": 1.0}],
        "package_manager": None,
        "test_command": {"value": "pytest", "evidence": "x", "confidence": 1.0},
        "test_glob": {"value": "tests/**/*.py", "evidence": "x", "confidence": 1.0},
        "extras": {},
    }
    data.update(overrides)
    path.write_text(json.dumps(data), encoding="utf-8")


def _script(target: Path) -> Path:
    return install_boundary_guard(target)


# ---------------- sem contrato ativo ----------------

def test_no_feature_list_allows_edit(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow"


# ---------------- superfície do contrato: Edit/Write ----------------

def test_edit_file_declared_in_contract_allows(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow"


def test_edit_file_not_declared_denies(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/other.py"}})
    assert out["permissionDecision"] == "deny"


# ---------------- superfície do contrato: Bash ----------------

def test_bash_exact_verify_cmd_allows(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -x --tb=short",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -x --tb=short"}})
    assert out["permissionDecision"] == "allow"


def test_bash_git_local_commands_allow(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    for cmd in ("git status", "git add .", 'git commit -m x'):
        out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "allow", cmd


def test_bash_unrelated_command_denies(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "echo oi"}})
    assert out["permissionDecision"] == "deny"


# ---------------- runtime floor: nunca vira allow ----------------

def test_floor_git_push_denies_even_with_full_contract(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py", ".env"],
         "verify_cmd": "git push", "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    for cmd in ("git push", "git push origin main", "git push && true"):
        out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "deny", cmd
        assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_curl_denies(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "curl https://x"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_env_file_denies_even_if_declared_in_contract(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": [".env"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".env"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_git_push_denies_without_any_contract(tmp_path: Path) -> None:
    """CRÍTICO: sem feature_list.json (nenhum contrato ativo), git push
    AINDA é deny — o floor roda antes do 'sem contrato -> allow'."""
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "git push origin main"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


def test_floor_env_file_denies_without_any_contract(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": ".env"}})
    assert out["permissionDecision"] == "deny"
    assert "runtime floor" in out["permissionDecisionReason"]


# ---------------- proteção contra enfraquecimento de teste ----------------

def test_test_file_declared_in_contract_allows(tmp_path: Path) -> None:
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["tests/test_x.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "allow"


def test_test_file_not_declared_denies_with_weakening_reason(tmp_path: Path) -> None:
    _write_profile(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "deny"
    assert "enfraquecimento" in out["permissionDecisionReason"]


# ---------------- package_manager derivando install command ----------------

def test_package_manager_install_command_is_allowed(tmp_path: Path) -> None:
    _write_profile(tmp_path, package_manager={"value": "npm", "evidence": "x", "confidence": 1.0})
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "npm ci"}})
    assert out["permissionDecision"] == "allow"


def test_package_manager_value_alone_is_not_a_free_pass_for_any_subcommand(tmp_path: Path) -> None:
    """Gap 2 (hardening): `package_manager.value == "npm"` deve liberar
    EXATAMENTE `npm ci` (o comando de instalação), não o nome do package
    manager inteiro — `npm run build-malicioso` (um comando `npm ...`
    qualquer, mas não `npm ci` exato) continua deny."""
    _write_profile(tmp_path, package_manager={"value": "npm", "evidence": "x", "confidence": 1.0})
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)

    allowed = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                  "tool_input": {"command": "npm ci"}})
    assert allowed["permissionDecision"] == "allow"

    denied = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                                 "tool_input": {"command": "npm run build-malicioso"}})
    assert denied["permissionDecision"] == "deny", denied


def test_package_manager_none_does_not_break_allowed_bash(tmp_path: Path) -> None:
    _write_profile(tmp_path, package_manager=None)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "x", "files": ["src/main.py"], "verify_cmd": "pytest -q",
         "depends": [], "passes": False}
    ])
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                              "tool_input": {"command": "pytest -q"}})
    assert out["permissionDecision"] == "allow"
    out2 = _run_hook(script, {"tool_name": "Bash", "cwd": str(tmp_path),
                               "tool_input": {"command": "echo oi"}})
    assert out2["permissionDecision"] == "deny"


# ---------------- ferramenta fora do escopo ----------------

def test_other_tool_allows_by_default(tmp_path: Path) -> None:
    script = _script(tmp_path)
    out = _run_hook(script, {"tool_name": "Read", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "src/main.py"}})
    assert out["permissionDecision"] == "allow"


# ---------------- install_boundary_guard: settings.json + estado ----------------

def test_install_registers_hook_in_settings(tmp_path: Path) -> None:
    script = install_boundary_guard(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    matching = [e for e in entries if e.get("matcher") == "Edit|Write|Bash"]
    assert len(matching) == 1
    assert str(script) in matching[0]["hooks"][0]["command"]


def test_install_is_idempotent(tmp_path: Path) -> None:
    install_boundary_guard(tmp_path)
    install_boundary_guard(tmp_path)
    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    entries = settings["hooks"]["PreToolUse"]
    matching = [e for e in entries if e.get("matcher") == "Edit|Write|Bash"]
    assert len(matching) == 1


def test_install_preserves_unrelated_settings_and_hooks(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(npm run *)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-hook.sh"}]},
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "python .harness/hooks/guard_test_runner.py"}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "opus"
    assert "Bash(npm run *)" in settings["permissions"]["allow"]
    user_hooks = [e for e in settings["hooks"]["PreToolUse"] if "meu-hook.sh" in json.dumps(e)]
    assert len(user_hooks) == 1
    runner_hooks = [e for e in settings["hooks"]["PreToolUse"] if "guard_test_runner.py" in json.dumps(e)]
    assert len(runner_hooks) == 1


def test_install_removes_legacy_guard_tests_hook(tmp_path: Path) -> None:
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "hooks": {"PreToolUse": [
            {"matcher": "Write|Edit",
             "hooks": [{"type": "command", "command": 'python ".harness/hooks/guard_tests.py"'}]},
        ]},
    }), encoding="utf-8")

    install_boundary_guard(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    legacy = [e for e in settings["hooks"]["PreToolUse"] if "guard_tests.py" in json.dumps(e)]
    assert legacy == []
    new_entries = [e for e in settings["hooks"]["PreToolUse"] if e.get("matcher") == "Edit|Write|Bash"]
    assert len(new_entries) == 1


def test_install_writes_state_key_preserving_siblings(tmp_path: Path) -> None:
    state_path = tmp_path / SESSION_STATE_FILE
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({"session_permissions_hook_command": "sibling"}), encoding="utf-8")

    install_boundary_guard(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["session_permissions_hook_command"] == "sibling"
    assert BOUNDARY_STATE_KEY in state
