"""Testes de `harness.verify`: `run_verify` e `compute_files_hash`.

Arquivo dedicado (não anexado a test_contract.py/test_cli.py) para não
colidir com tarefas concorrentes que editam contract.py/cli.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.verify import (
    VerifyError,
    VerifyFailedError,
    compute_files_hash,
    run_verify,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


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


def _is_windows() -> bool:
    return sys.platform.startswith("win")


def _true_cmd() -> str:
    return "exit 0" if _is_windows() else "true"


def _false_cmd() -> str:
    return "exit 1" if _is_windows() else "false"


def test_run_verify_success_writes_evidence_with_correct_schema(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "Criar x",
                "files": ["src/x.py"],
                "verify_cmd": _true_cmd(),
                "depends": [],
                "passes": False,
            }
        ],
    )

    evidence_path = run_verify(tmp_path, "T-01")

    assert evidence_path == tmp_path / ".harness" / "evidence" / "T-01.json"
    assert evidence_path.is_file()

    data = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert data["feature_id"] == "T-01"
    assert data["verify_cmd"] == _true_cmd()
    assert data["exit_code"] == 0
    assert "recorded_at" in data
    assert data["files_hash"] == compute_files_hash(["src/x.py"], tmp_path)
    assert set(data.keys()) == {"feature_id", "verify_cmd", "recorded_at", "exit_code", "files_hash"}


def test_run_verify_failure_does_not_write_evidence_and_propagates_exit_code(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "Falha",
                "files": [],
                "verify_cmd": _false_cmd(),
                "depends": [],
                "passes": False,
            }
        ],
    )

    with pytest.raises(VerifyFailedError) as exc_info:
        run_verify(tmp_path, "T-01")

    assert exc_info.value.exit_code == 1
    assert exc_info.value.feature_id == "T-01"
    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
    assert not evidence_path.is_file()


def test_run_verify_nonexistent_feature_raises_verify_error_naming_id(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            {
                "id": "T-01",
                "desc": "Existe",
                "files": [],
                "verify_cmd": _true_cmd(),
                "depends": [],
                "passes": False,
            }
        ],
    )

    with pytest.raises(VerifyError, match="T-99"):
        run_verify(tmp_path, "T-99")


def test_run_verify_missing_feature_list_raises_verify_error(tmp_path: Path) -> None:
    with pytest.raises(VerifyError):
        run_verify(tmp_path, "T-01")


def test_compute_files_hash_changes_when_file_content_changes(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "conteudo 1")
    hash_before = compute_files_hash(["a.txt"], tmp_path)

    _write(tmp_path / "a.txt", "conteudo 2")
    hash_after = compute_files_hash(["a.txt"], tmp_path)

    assert hash_before != hash_after
    assert hash_before.startswith("sha256:")
    assert hash_after.startswith("sha256:")


def test_compute_files_hash_is_deterministic_for_same_input(tmp_path: Path) -> None:
    _write(tmp_path / "a.txt", "conteudo")
    _write(tmp_path / "b.txt", "outro conteudo")

    hash1 = compute_files_hash(["b.txt", "a.txt"], tmp_path)
    hash2 = compute_files_hash(["a.txt", "b.txt"], tmp_path)

    assert hash1 == hash2


def test_compute_files_hash_does_not_raise_for_missing_file(tmp_path: Path) -> None:
    result = compute_files_hash(["nao-existe.txt"], tmp_path)
    assert result.startswith("sha256:")
