"""Testes do compilador (pivot plugin): harness.yaml -> governança nativa."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness import __version__ as _HARNESS_VERSION
from harness.compiler import AGENTS_BEGIN, AGENTS_END, STATE_FILE, compile_project, render
from harness.config import HarnessConfig


def _write_yaml(target: Path, content: str) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


BASIC_YAML = """
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "pytest -x --tb=short"
  test_glob: "tests/**/*.py"
"""


# ---------------- render: mapeamento de permissions por política ----------------

def _rules_for(policy: str, tmp_path: Path) -> dict[str, list[str]]:
    config = HarnessConfig.model_validate({"governance": {"approval_policy": policy}})
    return render(config, tmp_path).permission_rules


def test_balanced_asks_for_all_state_changes(tmp_path: Path) -> None:
    rules = _rules_for("balanced", tmp_path)
    assert "Bash" in rules["ask"]
    assert "Edit" in rules["ask"] and "Write" in rules["ask"]
    assert "WebFetch" in rules["ask"]
    assert "Read" in rules["allow"]


def test_paranoid_asks_even_for_reads(tmp_path: Path) -> None:
    rules = _rules_for("paranoid", tmp_path)
    assert "Read" in rules["ask"]
    assert rules["allow"] == []


def test_auto_still_gates_network(tmp_path: Path) -> None:
    rules = _rules_for("auto", tmp_path)
    assert "WebFetch" in rules["ask"] and "WebSearch" in rules["ask"]
    assert "Bash(curl *)" in rules["ask"]
    assert "Bash" in rules["allow"]          # auto libera execute...
    assert "Bash" not in rules["ask"]
    # ...mas rede nunca vai para allow
    assert all("curl" not in r and "WebFetch" not in r for r in rules["allow"])


def test_enforce_tdd_false_drops_runner_hook(tmp_path: Path) -> None:
    config = HarnessConfig.model_validate({"verification": {"enforce_tdd": False}})
    artifacts = render(config, tmp_path)
    assert "guard_test_runner.py" not in artifacts.hook_files
    assert "guard_tests.py" in artifacts.hook_files  # edit_test sempre protegido


def test_ignored_sections_generate_warning(tmp_path: Path) -> None:
    config = HarnessConfig.model_validate({})
    artifacts = render(config, tmp_path, raw_keys={"governance", "sandbox", "routing"})
    assert any("sandbox" in w for w in artifacts.warnings)


# ---------------- compile_project: escrita e merge ----------------

def test_compile_writes_all_artifacts(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    result = compile_project(tmp_path)

    settings = json.loads(result.settings_path.read_text(encoding="utf-8"))
    assert "Bash" in settings["permissions"]["ask"]
    hook_cmds = json.dumps(settings["hooks"]["PreToolUse"])
    assert "guard_tests.py" in hook_cmds and "guard_test_runner.py" in hook_cmds

    assert (tmp_path / ".harness" / "hooks" / "guard_tests.py").is_file()
    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert AGENTS_BEGIN in agents and AGENTS_END in agents


def test_compile_stamps_plugin_version_in_state_file(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)

    state = json.loads((tmp_path / STATE_FILE).read_text(encoding="utf-8"))
    assert state["plugin_version"] == _HARNESS_VERSION


def test_merge_preserves_user_settings_and_is_idempotent(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(npm run *)"], "deny": ["Read(.env)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-hook.sh"}]}
        ]},
    }), encoding="utf-8")

    compile_project(tmp_path)
    compile_project(tmp_path)  # segunda rodada: idempotente, sem duplicar

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert settings["model"] == "opus"                                  # chave alheia intacta
    assert "Bash(npm run *)" in settings["permissions"]["allow"]        # regra do usuário intacta
    assert "Read(.env)" in settings["permissions"]["deny"]
    assert settings["permissions"]["ask"].count("Bash") == 1            # sem duplicata
    user_hooks = [e for e in settings["hooks"]["PreToolUse"]
                  if "meu-hook.sh" in json.dumps(e)]
    assert len(user_hooks) == 1                                         # hook do usuário intacto
    guard_entries = [e for e in settings["hooks"]["PreToolUse"]
                     if "guard_tests.py" in json.dumps(e)]
    assert len(guard_entries) == 1                                      # sem duplicar o nosso


def test_recompile_after_policy_change_swaps_rules(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    _write_yaml(tmp_path, BASIC_YAML.replace("balanced", "auto"))
    compile_project(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Bash" in settings["permissions"]["allow"]   # auto libera execute
    assert "Bash" not in settings["permissions"]["ask"] # regra antiga removida


def test_agents_block_regenerates_without_destroying_manual_text(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    (tmp_path / "AGENTS.md").write_text(
        f"# Meu projeto\n\nRegra manual minha.\n\n{AGENTS_BEGIN}\nvelho\n{AGENTS_END}\n",
        encoding="utf-8",
    )
    compile_project(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Regra manual minha." in text
    assert "velho" not in text
    assert text.count(AGENTS_BEGIN) == 1


def test_compile_without_yaml_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="harness-creator:init"):
        compile_project(tmp_path)


# ---------------- hooks gerados: standalone, executados de verdade ----------------

def _run_hook(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def test_guard_tests_hook_asks_for_test_and_allows_source(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    asks = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "tests/test_x.py"}})
    assert asks["permissionDecision"] == "ask"

    allows = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                                "tool_input": {"file_path": "src/main.py"}})
    assert allows["permissionDecision"] == "allow"

    # Path absoluto (forma que o Claude Code envia) também é reconhecido.
    abs_asks = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                                  "tool_input": {"file_path": str(tmp_path / "tests" / "test_y.py")}})
    assert abs_asks["permissionDecision"] == "ask"


def test_guard_tests_recursive_glob_does_not_overblock(tmp_path: Path) -> None:
    """Regressão do bug is_test_path: '**/test_*.py' não pode marcar todo .py."""
    _write_yaml(tmp_path, BASIC_YAML.replace("tests/**/*.py", "**/test_*.py"))
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    allows = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                                "tool_input": {"file_path": "src/orchestrator.py"}})
    assert allows["permissionDecision"] == "allow"

    asks = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "pkg/test_core.py"}})
    assert asks["permissionDecision"] == "ask"


def test_guard_test_runner_hook_catches_metachar_bypass(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_test_runner.py"

    for cmd in ("pytest -x", "pytest&&true", "(pytest)", "true|pytest"):
        out = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "ask", cmd

    out = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": "git status"}})
    assert out["permissionDecision"] == "allow"


def test_guard_test_runner_multiword_command_does_not_overblock(tmp_path: Path) -> None:
    """Regressão: test_command 'dotnet test' não pode marcar todo 'dotnet'."""
    _write_yaml(tmp_path, BASIC_YAML.replace("pytest -x --tb=short", "dotnet test"))
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_test_runner.py"

    for cmd in ("dotnet test", "dotnet test --filter Foo", "cd api && dotnet test",
                "dotnet build && dotnet test"):
        out = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "ask", cmd

    for cmd in ("dotnet build", "dotnet run", "dotnet restore", "git status"):
        out = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "allow", cmd


def test_guard_test_runner_strips_flags_from_test_command(tmp_path: Path) -> None:
    """test_command com flags ('pytest -x --tb=short') casa 'pytest' pelado."""
    _write_yaml(tmp_path, BASIC_YAML)  # test_command: "pytest -x --tb=short"
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_test_runner.py"

    out = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": "pytest"}})
    assert out["permissionDecision"] == "ask"
