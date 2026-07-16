"""Testes de CLI: subcomandos `harness analyze` e `harness compile-contract`.

Arquivo dedicado (não anexado a test_analyzer.py/test_contract.py) para não
colidir com tarefas concorrentes que editam analyzer.py/contract.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


APPROVED_SPEC = """---
slug: exemplo-feature
approved_by: alice
approved_at: 2026-07-15T10:00:00Z
---

# Spec: Exemplo de Feature
"""

UNAPPROVED_SPEC = """---
slug: exemplo-feature
approved_by:
approved_at:
---

# Spec sem aprovacao
"""

BASIC_PLANS = """## [T-01] Criar modulo de configuracao
- files: `src/harness/config.py`
- verify: `pytest tests/test_config.py -q`
"""


def test_analyze_subcommand_prints_profile_json_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample"\ndependencies = ["pytest>=8.0"]\n')
    _write(tmp_path / "uv.lock", "# lockfile fake\n")
    _write(tmp_path / "tests" / "test_sample.py", "def test_ok():\n    assert True\n")

    monkeypatch.setattr(sys, "argv", ["harness", "analyze", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "languages" in data
    assert any(f["value"] == "python" for f in data["languages"])

    profile_path = tmp_path / ".harness" / "repo-profile.json"
    assert profile_path.is_file()


def test_analyze_subcommand_exits_zero_even_with_unknowns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Diretório vazio: nenhum manifest reconhecido -> só unknowns, não é erro.
    monkeypatch.setattr(sys, "argv", ["harness", "analyze", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["unknowns"]


def test_compile_contract_subcommand_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-contract", "--dir", str(tmp_path), "--slug", "exemplo-feature"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["contract"] == "exemplo-feature"
    assert data["features"] == 1
    assert data["feature_list"].endswith("feature_list.json")

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    assert feature_list_path.is_file()


def test_compile_contract_subcommand_not_approved_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", UNAPPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-contract", "--dir", str(tmp_path), "--slug", "exemplo-feature"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_compile_contract_subcommand_missing_spec_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-contract", "--dir", str(tmp_path), "--slug", "inexistente"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_compile_session_subcommand_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.analyzer import analyze_project, write_profile
    from harness.contract import compile_contract

    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample"\ndependencies = ["pytest>=8.0"]\n')
    _write(tmp_path / "uv.lock", "# lockfile fake\n")
    _write(tmp_path / "tests" / "test_config.py", "def test_ok():\n    assert True\n")

    compile_contract(tmp_path, "exemplo-feature")
    profile = analyze_project(tmp_path)
    write_profile(profile, tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["settings"].endswith("settings.json")
    assert data["boundary_guard"].endswith("boundary_guard.py")
    assert data["agents_md"].endswith("AGENTS.md")
    assert data["lifecycle_detail"].endswith("LIFECYCLE.md")
    assert data["session_start_hook"].endswith("session_start.py")
    assert data["stop_hook"].endswith("stop_hook.py")
    assert any(p.endswith("init.sh") for p in data["templates"])
    assert any(p.endswith("init.ps1") for p in data["templates"])

    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert (tmp_path / ".harness" / "hooks" / "boundary_guard.py").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".harness" / "LIFECYCLE.md").is_file()
    assert (tmp_path / "claude-progress.md").is_file()
    assert (tmp_path / "init.sh").is_file()
    assert (tmp_path / "init.ps1").is_file()
    assert (tmp_path / ".harness" / "hooks" / "session_start.py").is_file()
    assert (tmp_path / ".harness" / "hooks" / "stop_hook.py").is_file()


def test_compile_session_subcommand_missing_feature_list_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def _write_feature_list(tmp_path: Path, verify_cmd: str) -> None:
    payload = {
        "contract": "exemplo-feature",
        "compiled_at": "2026-07-16T12:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "Criar modulo de configuracao",
                "files": [],
                "verify_cmd": verify_cmd,
                "depends": [],
                "passes": False,
            }
        ],
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _true_cmd() -> str:
    return "exit 0" if sys.platform.startswith("win") else "true"


def _exit_code_cmd(code: int) -> str:
    return f"exit {code}" if sys.platform.startswith("win") else f"exit {code}"


def test_verify_subcommand_success_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["feature_id"] == "T-01"
    assert data["exit_code"] == 0

    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
    assert evidence_path.is_file()


def test_verify_subcommand_failure_propagates_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _exit_code_cmd(3))

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
    assert not evidence_path.is_file()


def test_verify_subcommand_missing_feature_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-99", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_audit_runtime_subcommand_exits_one_when_score_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # nenhum feature_list.json -> critical -> score baixo -> exit 1
    monkeypatch.setattr(sys, "argv", ["harness", "audit-runtime", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    data = json.loads(capsys.readouterr().out)
    assert "missing_feature_list" in {f["code"] for f in data["findings"]}
    assert data["score"] <= 60


def test_audit_runtime_subcommand_exits_zero_when_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())
    _write(tmp_path / "claude-progress.md", "# Progresso\n")

    monkeypatch.setattr(sys, "argv", ["harness", "audit-runtime", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert not any(f["severity"] == "critical" for f in data["findings"])
    assert data["score"] >= 60
