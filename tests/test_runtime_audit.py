"""Testes do runtime_audit: mecanismo DISTINTO de audit.py — schema + frescor +
invariantes dos artefatos runtime-mutáveis (feature_list.json, evidence/*.json,
claude-progress.md). Nunca diff byte-exato."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from harness.runtime_audit import audit_runtime


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _codes(report) -> set[str]:
    return {f.code for f in report.findings}


def _feature(
    feature_id: str = "T-01",
    files: list[str] | None = None,
    passes: bool = False,
) -> dict:
    return {
        "id": feature_id,
        "desc": "Feature de teste",
        "files": files if files is not None else ["src/x.py"],
        "verify_cmd": "pytest -q",
        "depends": [],
        "passes": passes,
    }


def _write_feature_list(tmp_path: Path, features: list[dict]) -> None:
    payload = {
        "contract": "exemplo-feature",
        "compiled_at": "2026-07-16T12:00:00+00:00",
        "features": features,
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _write_evidence(
    tmp_path: Path,
    feature_id: str,
    exit_code: int = 0,
    feature_id_field: str | None = None,
    extra_fields_missing: bool = False,
) -> None:
    evidence = {
        "feature_id": feature_id_field if feature_id_field is not None else feature_id,
        "verify_cmd": "pytest -q",
        "recorded_at": "2026-07-16T12:00:00+00:00",
        "exit_code": exit_code,
        "files_hash": "sha256:deadbeef",
    }
    if extra_fields_missing:
        del evidence["files_hash"]
    _write(
        tmp_path / ".harness" / "evidence" / f"{feature_id}.json",
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
    )


def _init_git_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)


def test_missing_feature_list_is_critical(tmp_path: Path) -> None:
    report = audit_runtime(tmp_path)
    assert "missing_feature_list" in _codes(report)
    assert any(f.severity == "critical" for f in report.findings)
    assert report.score <= 60


def test_invalid_feature_list_json_is_critical(tmp_path: Path) -> None:
    _write(tmp_path / ".harness" / "feature_list.json", "{ not valid json")
    report = audit_runtime(tmp_path)
    assert "invalid_feature_list" in _codes(report)


def test_feature_list_missing_required_top_level_keys_is_critical(tmp_path: Path) -> None:
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps({"features": []}),
    )
    report = audit_runtime(tmp_path)
    assert "invalid_feature_list_schema" in _codes(report)


def test_feature_missing_required_fields_is_critical(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [{"id": "T-01", "passes": False}])
    report = audit_runtime(tmp_path)
    assert "invalid_feature_schema" in _codes(report)


def test_missing_progress_file_is_warning(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=False)])
    report = audit_runtime(tmp_path)
    assert "missing_progress_file" in _codes(report)
    assert any(f.code == "missing_progress_file" and f.severity == "warning" for f in report.findings)


def test_progress_file_present_no_finding(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=False)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    report = audit_runtime(tmp_path)
    assert "missing_progress_file" not in _codes(report)


def test_passes_true_without_evidence_is_critical(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    report = audit_runtime(tmp_path)
    assert "missing_evidence" in _codes(report)
    assert any(f.severity == "critical" and "T-01" in f.message for f in report.findings)


def test_passes_true_with_invalid_evidence_json_is_critical(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    _write(tmp_path / ".harness" / "evidence" / "T-01.json", "{ not valid json")
    report = audit_runtime(tmp_path)
    assert "invalid_evidence_json" in _codes(report)


def test_evidence_missing_required_fields_is_critical(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    _write_evidence(tmp_path, "T-01", extra_fields_missing=True)
    report = audit_runtime(tmp_path)
    assert "invalid_evidence_schema" in _codes(report)


def test_evidence_feature_id_mismatch_is_critical(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    _write_evidence(tmp_path, "T-01", feature_id_field="T-99")
    report = audit_runtime(tmp_path)
    assert "evidence_feature_id_mismatch" in _codes(report)


def test_evidence_exit_code_nonzero_is_critical(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    _write_evidence(tmp_path, "T-01", exit_code=1)
    report = audit_runtime(tmp_path)
    assert "evidence_exit_code_nonzero" in _codes(report)


def test_passes_true_with_valid_evidence_no_finding(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature(passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n")
    _write_evidence(tmp_path, "T-01", exit_code=0)
    report = audit_runtime(tmp_path)
    codes = _codes(report)
    assert "missing_evidence" not in codes
    assert "invalid_evidence_json" not in codes
    assert "invalid_evidence_schema" not in codes
    assert "evidence_feature_id_mismatch" not in codes
    assert "evidence_exit_code_nonzero" not in codes


def test_multiple_features_in_progress_is_critical(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "a = 1\n")
    _write(tmp_path / "src" / "b.py", "b = 1\n")
    _init_git_repo(tmp_path)

    # trabalho não commitado tocando os arquivos de duas features distintas
    (tmp_path / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")
    (tmp_path / "src" / "b.py").write_text("b = 2\n", encoding="utf-8")

    _write_feature_list(
        tmp_path,
        [
            _feature("T-01", files=["src/a.py"], passes=False),
            _feature("T-02", files=["src/b.py"], passes=False),
        ],
    )
    _write(tmp_path / "claude-progress.md", "# Progresso\n")

    report = audit_runtime(tmp_path)
    assert "multiple_features_in_progress" in _codes(report)
    assert any(f.severity == "critical" for f in report.findings)


def test_single_feature_in_progress_no_finding(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "a = 1\n")
    _write(tmp_path / "src" / "b.py", "b = 1\n")
    _init_git_repo(tmp_path)

    (tmp_path / "src" / "a.py").write_text("a = 2\n", encoding="utf-8")

    _write_feature_list(
        tmp_path,
        [
            _feature("T-01", files=["src/a.py"], passes=False),
            _feature("T-02", files=["src/b.py"], passes=False),
        ],
    )
    _write(tmp_path / "claude-progress.md", "# Progresso\n")

    report = audit_runtime(tmp_path)
    assert "multiple_features_in_progress" not in _codes(report)


def test_healthy_project_scores_high_with_zero_critical(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "a.py", "a = 1\n")
    _init_git_repo(tmp_path)

    _write_feature_list(tmp_path, [_feature("T-01", files=["src/a.py"], passes=True)])
    _write(tmp_path / "claude-progress.md", "# Progresso\n\nTudo certo.\n")
    _write_evidence(tmp_path, "T-01", exit_code=0)

    report = audit_runtime(tmp_path)
    assert not any(f.severity == "critical" for f in report.findings)
    assert report.score >= 85
