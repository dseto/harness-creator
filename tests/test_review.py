"""Testes de `harness.review`: state machine de revisão do Produtor-Revisor.

Arquivo dedicado (não anexado a outros test_*.py) para não colidir com
tarefas concorrentes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.review import (
    ReviewError,
    ReviewResult,
    is_test_diff,
    load_review,
    record_decision,
    submit_for_review,
)


def _write_repo_profile(tmp_path: Path, test_glob: str) -> None:
    payload = {
        "languages": [],
        "package_manager": None,
        "test_command": None,
        "test_glob": {"value": test_glob, "evidence": "tests/", "confidence": 1.0},
        "extras": {},
        "unknowns": [],
        "analyzed_at": "2026-07-16T12:00:00+00:00",
        "manifest_snapshot": {},
    }
    path = tmp_path / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _feature(files: list[str]) -> dict:
    return {
        "id": "T-01",
        "desc": "Feature de exemplo",
        "files": files,
        "verify_cmd": "pytest -q",
        "depends": [],
        "passes": False,
    }


# ---------------------------------------------------------------------------
# load_review
# ---------------------------------------------------------------------------

def test_load_review_default_without_file(tmp_path: Path) -> None:
    record = load_review(tmp_path, "T-01")

    assert record["feature_id"] == "T-01"
    assert record["status"] == "pending"
    assert record["iteration"] == 0
    assert record["max_iterations"] == 3
    assert record["history"] == []
    assert record["justification"] is None
    assert not (tmp_path / ".harness" / "review" / "T-01.json").exists()


# ---------------------------------------------------------------------------
# submit_for_review
# ---------------------------------------------------------------------------

def test_submit_for_review_pending_to_in_review(tmp_path: Path) -> None:
    record = submit_for_review(tmp_path, "T-01")

    assert record["status"] == "in_review"
    assert record["iteration"] == 1
    assert (tmp_path / ".harness" / "review" / "T-01.json").is_file()


def test_submit_for_review_from_in_review_raises(tmp_path: Path) -> None:
    submit_for_review(tmp_path, "T-01")

    with pytest.raises(ReviewError):
        submit_for_review(tmp_path, "T-01")


def test_submit_for_review_from_approved_raises(tmp_path: Path) -> None:
    submit_for_review(tmp_path, "T-01")
    record_decision(tmp_path, "T-01", _feature([]), "approved", "ok")

    with pytest.raises(ReviewError):
        submit_for_review(tmp_path, "T-01")


# ---------------------------------------------------------------------------
# record_decision
# ---------------------------------------------------------------------------

def test_record_decision_approved_from_in_review(tmp_path: Path) -> None:
    submit_for_review(tmp_path, "T-01")

    result = record_decision(tmp_path, "T-01", _feature([]), "approved", "parece ótimo")

    assert isinstance(result, ReviewResult)
    assert result.status == "approved"
    assert result.escalate is False
    assert "aprovado na iteração 1" in result.message

    record = load_review(tmp_path, "T-01")
    assert record["status"] == "approved"
    assert record["history"] == [
        {"iteration": 1, "decision": "approved", "note": "parece ótimo", "at": record["history"][0]["at"]}
    ]


def test_record_decision_rejected_below_max_no_escalate(tmp_path: Path) -> None:
    submit_for_review(tmp_path, "T-01", max_iterations=3)

    result = record_decision(tmp_path, "T-01", _feature([]), "rejected", "faltou X")

    assert result.status == "rejected"
    assert result.escalate is False
    assert "refaça e resubmeta" in result.message


def test_reject_cycle_until_max_iterations_escalates_and_status_stays_rejected(tmp_path: Path) -> None:
    max_iterations = 2

    # iteração 1: submete e rejeita — ainda abaixo do teto.
    submit_for_review(tmp_path, "T-01", max_iterations=max_iterations)
    result = record_decision(tmp_path, "T-01", _feature([]), "rejected", "n1")
    assert result.iteration == 1
    assert result.escalate is False
    assert result.status == "rejected"

    # iteração 2: resubmete (parâmetro max_iterations ignorado — usa o gravado)
    # e rejeita de novo — agora estoura o teto.
    submit_for_review(tmp_path, "T-01", max_iterations=999)
    result = record_decision(tmp_path, "T-01", _feature([]), "rejected", "n2")
    assert result.iteration == 2
    assert result.escalate is True
    assert result.status == "rejected"
    assert "ESCALE ao humano" in result.message

    record = load_review(tmp_path, "T-01")
    assert record["max_iterations"] == max_iterations
    assert record["status"] == "rejected"


def test_resubmit_after_escalation_raises_hard_cap(tmp_path: Path) -> None:
    max_iterations = 2
    submit_for_review(tmp_path, "T-01", max_iterations=max_iterations)
    record_decision(tmp_path, "T-01", _feature([]), "rejected", "n1")
    submit_for_review(tmp_path, "T-01")
    record_decision(tmp_path, "T-01", _feature([]), "rejected", "n2")

    with pytest.raises(ReviewError):
        submit_for_review(tmp_path, "T-01")


def test_record_decision_from_pending_raises(tmp_path: Path) -> None:
    with pytest.raises(ReviewError):
        record_decision(tmp_path, "T-01", _feature([]), "approved", "ok")


def test_record_decision_from_approved_raises(tmp_path: Path) -> None:
    submit_for_review(tmp_path, "T-01")
    record_decision(tmp_path, "T-01", _feature([]), "approved", "ok")

    with pytest.raises(ReviewError):
        record_decision(tmp_path, "T-01", _feature([]), "approved", "de novo")


def test_record_decision_invalid_decision_raises(tmp_path: Path) -> None:
    submit_for_review(tmp_path, "T-01")

    with pytest.raises(ReviewError):
        record_decision(tmp_path, "T-01", _feature([]), "maybe", "ok")


# ---------------------------------------------------------------------------
# gate de diff de teste
# ---------------------------------------------------------------------------

def test_approve_test_diff_without_justification_raises(tmp_path: Path) -> None:
    _write_repo_profile(tmp_path, "tests/**/*.py")
    submit_for_review(tmp_path, "T-01")

    with pytest.raises(ReviewError):
        record_decision(
            tmp_path, "T-01", _feature(["tests/test_x.py"]), "approved", "ok"
        )


def test_approve_test_diff_with_justification_succeeds(tmp_path: Path) -> None:
    _write_repo_profile(tmp_path, "tests/**/*.py")
    submit_for_review(tmp_path, "T-01")

    result = record_decision(
        tmp_path,
        "T-01",
        _feature(["tests/test_x.py"]),
        "approved",
        "ok",
        justification="mudou o contrato de retorno da API, teste atualizado de propósito",
    )

    assert result.status == "approved"
    record = load_review(tmp_path, "T-01")
    assert record["justification"] == (
        "mudou o contrato de retorno da API, teste atualizado de propósito"
    )


# ---------------------------------------------------------------------------
# is_test_diff
# ---------------------------------------------------------------------------

def test_is_test_diff_true_when_file_matches_glob(tmp_path: Path) -> None:
    _write_repo_profile(tmp_path, "tests/**/*.py")

    assert is_test_diff(_feature(["tests/test_x.py"]), tmp_path) is True


def test_is_test_diff_false_when_file_does_not_match_glob(tmp_path: Path) -> None:
    _write_repo_profile(tmp_path, "tests/**/*.py")

    assert is_test_diff(_feature(["src/harness/x.py"]), tmp_path) is False


def test_is_test_diff_false_without_repo_profile(tmp_path: Path) -> None:
    assert is_test_diff(_feature(["tests/test_x.py"]), tmp_path) is False
