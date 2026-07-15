"""Testes do audit (pivot plugin): score + findings + detecção de drift."""

from __future__ import annotations

import json
from pathlib import Path

from harness.audit import audit_project
from harness.compiler import compile_project

BASIC_YAML = """
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "pytest -x --tb=short"
  test_glob: "tests/**/*.py"
"""


def _bootstrap(target: Path, yaml_content: str = BASIC_YAML) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content, encoding="utf-8")
    # arquivo de teste real para o check no_test_files não disparar
    tests_dir = target / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _codes(report) -> set[str]:
    return {f.code for f in report.findings}


def test_freshly_compiled_project_scores_high(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)

    report = audit_project(tmp_path)

    assert report.score >= 85
    assert not any(f.severity == "critical" for f in report.findings)


def test_missing_yaml_is_critical(tmp_path: Path) -> None:
    report = audit_project(tmp_path)
    assert "missing_harness_yaml" in _codes(report)
    assert report.score <= 60


def test_invalid_yaml_is_critical(tmp_path: Path) -> None:
    path = tmp_path / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("governance:\n  approval_policy: modo_inexistente\n", encoding="utf-8")

    report = audit_project(tmp_path)
    assert "invalid_harness_yaml" in _codes(report)


def test_missing_hooks_and_settings_detected(tmp_path: Path) -> None:
    _bootstrap(tmp_path)  # yaml presente, mas nunca compilou

    report = audit_project(tmp_path)
    codes = _codes(report)
    assert "missing_hook" in codes
    assert "missing_settings" in codes


def test_hook_drift_detected_after_manual_edit(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)
    hook = tmp_path / ".harness" / "hooks" / "guard_tests.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# editado à mão\n", encoding="utf-8")

    report = audit_project(tmp_path)
    assert "hook_drift" in _codes(report)


def test_settings_drift_detected_when_rule_removed(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["permissions"]["ask"].remove("Bash")
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    report = audit_project(tmp_path)
    assert "permissions_drift" in _codes(report)


def test_yaml_change_without_recompile_is_drift(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)
    # muda a política no yaml sem recompilar -> settings antigo diverge
    (tmp_path / ".harness" / "harness.yaml").write_text(
        BASIC_YAML.replace("balanced", "paranoid"), encoding="utf-8"
    )

    report = audit_project(tmp_path)
    assert "permissions_drift" in _codes(report)  # paranoid exige Read em ask


def test_auto_policy_flagged_as_warning(tmp_path: Path) -> None:
    _bootstrap(tmp_path, BASIC_YAML.replace("balanced", "auto"))
    compile_project(tmp_path)

    report = audit_project(tmp_path)
    assert "auto_policy" in _codes(report)


def test_no_test_files_is_info_finding(tmp_path: Path) -> None:
    path = tmp_path / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(BASIC_YAML, encoding="utf-8")  # sem criar tests/
    compile_project(tmp_path)

    report = audit_project(tmp_path)
    assert "no_test_files" in _codes(report)
