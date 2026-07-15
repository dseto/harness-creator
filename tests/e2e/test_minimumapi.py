"""E2E: harness-creator aplicado a uma API .NET real (cópia da MinimumAPI).

Simula o ciclo de vida completo que um usuário teria: init (yaml) → compile →
hooks respondendo a payloads reais do Claude Code → drift → recompile →
merge não-destrutivo. Roda a CLI e os hooks em subprocess, como na vida real.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from harness.audit import audit_project
from harness.compiler import compile_project

HARNESS_YAML = """\
governance:
  approval_policy: balanced
  budget:
    max_tokens_per_task: 500000
    max_tool_calls_per_task: 120
verification:
  enforce_tdd: true
  test_command: "dotnet test"
  test_glob: "MinimumAPI.Tests/**/*.cs"
"""


def _init(project: Path, yaml_content: str = HARNESS_YAML) -> None:
    path = project / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content, encoding="utf-8")


def _run_hook(script: Path, payload: dict) -> str:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


def _edit(project: Path, file_path: str) -> dict:
    return {"tool_name": "Edit", "cwd": str(project), "tool_input": {"file_path": file_path}}


def _bash(command: str) -> dict:
    return {"tool_name": "Bash", "tool_input": {"command": command}}


# ---------------- pipeline completo ----------------

def test_full_pipeline_compile_then_audit_100(api_project: Path) -> None:
    _init(api_project)
    result = compile_project(api_project)

    assert result.warnings == []
    settings = json.loads(result.settings_path.read_text(encoding="utf-8"))
    assert "Bash" in settings["permissions"]["ask"]          # balanced gateia execute
    assert "Read" in settings["permissions"]["allow"]
    assert len(settings["hooks"]["PreToolUse"]) == 2

    report = audit_project(api_project)
    assert report.score == 100, report.to_json()


def test_cli_compile_and_audit_subprocess(api_project: Path) -> None:
    """CLI real via subprocess — mesmo caminho que a skill usa."""
    import os

    _init(api_project)
    env = os.environ | {"PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")}

    compile_proc = subprocess.run(
        [sys.executable, "-m", "harness.cli", "compile", "--dir", str(api_project)],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(api_project),
    )
    assert compile_proc.returncode == 0, compile_proc.stderr
    out = json.loads(compile_proc.stdout)
    assert len(out["hooks"]) == 2

    audit_proc = subprocess.run(
        [sys.executable, "-m", "harness.cli", "audit", "--dir", str(api_project)],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(api_project),
    )
    assert audit_proc.returncode == 0, audit_proc.stderr
    assert json.loads(audit_proc.stdout)["score"] == 100


# ---------------- matriz de hooks com payloads .NET reais ----------------

def test_hook_matrix_dotnet(api_project: Path) -> None:
    _init(api_project)
    compile_project(api_project)
    guard_tests = api_project / ".harness" / "hooks" / "guard_tests.py"
    guard_runner = api_project / ".harness" / "hooks" / "guard_test_runner.py"

    # fonte da API: livre (permission ask cuida do resto)
    assert _run_hook(guard_tests, _edit(api_project, "MinimumAPI/Endpoints/CustomerEndpoints.cs")) == "allow"
    assert _run_hook(guard_tests, _edit(api_project, "MinimumAPI/Program.cs")) == "allow"
    # arquivo de teste: aprovação humana, path relativo E absoluto
    assert _run_hook(guard_tests, _edit(api_project, "MinimumAPI.Tests/CustomerValidatorTests.cs")) == "ask"
    abs_test = str(api_project / "MinimumAPI.Tests" / "CustomerValidatorTests.cs")
    assert _run_hook(guard_tests, _edit(api_project, abs_test)) == "ask"

    # runner de 2 palavras: 'dotnet test' pede humano, resto do dotnet NÃO
    for cmd in ("dotnet test", "dotnet test --filter Customer",
                "cd MinimumAPI.Tests && dotnet test", "dotnet build && dotnet test"):
        assert _run_hook(guard_runner, _bash(cmd)) == "ask", cmd
    for cmd in ("dotnet build", "dotnet run --project MinimumAPI",
                "dotnet restore", "git status", "dotnet ef migrations add X"):
        assert _run_hook(guard_runner, _bash(cmd)) == "allow", cmd


# ---------------- drift e recuperação ----------------

def test_drift_hook_edited_then_recompile_restores(api_project: Path) -> None:
    _init(api_project)
    compile_project(api_project)
    hook = api_project / ".harness" / "hooks" / "guard_tests.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# sabotagem\n", encoding="utf-8")

    drifted = audit_project(api_project)
    assert "hook_drift" in {f.code for f in drifted.findings}
    assert drifted.score < 100

    compile_project(api_project)
    assert audit_project(api_project).score == 100


def test_policy_change_without_recompile_is_drift(api_project: Path) -> None:
    _init(api_project)
    compile_project(api_project)
    _init(api_project, HARNESS_YAML.replace("balanced", "auto"))

    report = audit_project(api_project)
    codes = {f.code for f in report.findings}
    assert "permissions_drift" in codes
    assert "auto_policy" in codes  # warning de política arriscada

    compile_project(api_project)
    settings = json.loads(
        (api_project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "Bash" in settings["permissions"]["allow"]   # auto libera execute
    assert "WebFetch" in settings["permissions"]["ask"] # rede segue gateada


# ---------------- merge não-destrutivo com settings reais ----------------

def test_user_deny_rule_protecting_connection_string_survives(api_project: Path) -> None:
    """Cenário real: usuário nega leitura do appsettings com connection string."""
    _init(api_project)
    claude_dir = api_project / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "permissions": {"deny": ["Read(MinimumAPI/appsettings.Development.json)"]},
        "model": "opus",
    }), encoding="utf-8")

    compile_project(api_project)
    compile_project(api_project)  # idempotência

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert "Read(MinimumAPI/appsettings.Development.json)" in settings["permissions"]["deny"]
    assert settings["model"] == "opus"
    assert settings["permissions"]["ask"].count("Bash") == 1


def test_agents_md_manual_sections_survive_recompile(api_project: Path) -> None:
    _init(api_project)
    (api_project / "AGENTS.md").write_text(
        "# MinimumAPI\n\nSempre use FluentValidation para entrada de dados.\n",
        encoding="utf-8",
    )
    compile_project(api_project)
    _init(api_project, HARNESS_YAML.replace('"dotnet test"', '"dotnet test -v q"'))
    compile_project(api_project)

    text = (api_project / "AGENTS.md").read_text(encoding="utf-8")
    assert "Sempre use FluentValidation" in text
    assert text.count("<!-- harness:begin -->") == 1
    assert "dotnet test -v q" in text  # bloco regenerado reflete o yaml novo


def test_disable_tdd_removes_runner_hook_everywhere(api_project: Path) -> None:
    _init(api_project)
    compile_project(api_project)
    assert (api_project / ".harness" / "hooks" / "guard_test_runner.py").is_file()

    _init(api_project, HARNESS_YAML.replace("enforce_tdd: true", "enforce_tdd: false"))
    compile_project(api_project)

    assert not (api_project / ".harness" / "hooks" / "guard_test_runner.py").exists()
    settings = json.loads(
        (api_project / ".claude" / "settings.json").read_text(encoding="utf-8"))
    assert "guard_test_runner" not in json.dumps(settings)
    assert audit_project(api_project).score == 100
