"""Testes de `harness.supervisor`: `ready_features`, `dispatch_next`,
`on_feature_verified`.

Arquivo dedicado (não anexado a test_contract.py/test_review.py) para não
colidir com tarefas concorrentes que editam esses módulos."""

from __future__ import annotations

import json
from pathlib import Path

from harness.supervisor import dispatch_next, on_feature_verified, ready_features


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _feature(
    feature_id: str,
    passes: bool = False,
    depends: list[str] | None = None,
) -> dict:
    return {
        "id": feature_id,
        "desc": f"feature {feature_id}",
        "files": [f"src/{feature_id}.py"],
        "verify_cmd": "pytest",
        "depends": depends or [],
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


def _write_manifest(tmp_path: Path, roles: list[str], max_review_iterations: int = 3) -> None:
    payload = {
        "pattern": "producer-reviewer",
        "mode": "subagents",
        "roles": roles,
        "max_review_iterations": max_review_iterations,
        "generated_at": "2026-07-16T12:00:00+00:00",
    }
    _write(
        tmp_path / ".harness" / "team" / "manifest.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


# ---------------------------------------------------------------------------
# ready_features
# ---------------------------------------------------------------------------

def test_ready_features_no_dependencies_always_ready_if_not_passing() -> None:
    feature_list = {"features": [_feature("T-01")]}
    assert ready_features(feature_list) == [_feature("T-01")]


def test_ready_features_excludes_features_already_passing() -> None:
    feature_list = {"features": [_feature("T-01", passes=True)]}
    assert ready_features(feature_list) == []


def test_ready_features_dependency_satisfied() -> None:
    feature_list = {
        "features": [
            _feature("T-01", passes=True),
            _feature("T-02", depends=["T-01"]),
        ]
    }
    result = ready_features(feature_list)
    assert [f["id"] for f in result] == ["T-02"]


def test_ready_features_dependency_not_satisfied() -> None:
    feature_list = {
        "features": [
            _feature("T-01", passes=False),
            _feature("T-02", depends=["T-01"]),
        ]
    }
    result = ready_features(feature_list)
    assert [f["id"] for f in result] == ["T-01"]


def test_ready_features_dependency_on_nonexistent_id_never_ready() -> None:
    feature_list = {
        "features": [
            _feature("T-01", depends=["T-99"]),
        ]
    }
    assert ready_features(feature_list) == []


def test_ready_features_preserves_order_when_multiple_ready() -> None:
    feature_list = {
        "features": [
            _feature("T-03"),
            _feature("T-01"),
            _feature("T-02"),
        ]
    }
    result = ready_features(feature_list)
    assert [f["id"] for f in result] == ["T-03", "T-01", "T-02"]


# ---------------------------------------------------------------------------
# dispatch_next
# ---------------------------------------------------------------------------

def test_dispatch_next_no_feature_list_returns_none(tmp_path: Path) -> None:
    assert dispatch_next(tmp_path) is None


def test_dispatch_next_returns_first_ready_feature(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature("T-01"), _feature("T-02")])
    result = dispatch_next(tmp_path)
    assert result is not None
    assert result["id"] == "T-01"


def test_dispatch_next_all_done_returns_none(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, [_feature("T-01", passes=True)])
    assert dispatch_next(tmp_path) is None


def test_dispatch_next_none_ready_returns_none(tmp_path: Path) -> None:
    _write_feature_list(
        tmp_path,
        [
            _feature("T-01", depends=["T-99"]),
            _feature("T-02", depends=["T-99"]),
        ],
    )
    assert dispatch_next(tmp_path) is None


def test_dispatch_next_invalid_json_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / ".harness" / "feature_list.json", "{ nao e json valido")
    assert dispatch_next(tmp_path) is None


# ---------------------------------------------------------------------------
# on_feature_verified
# ---------------------------------------------------------------------------

def test_on_feature_verified_no_manifest_returns_none(tmp_path: Path) -> None:
    assert on_feature_verified(tmp_path, "T-01") is None
    assert not (tmp_path / ".harness" / "review" / "T-01.json").exists()


def test_on_feature_verified_manifest_without_both_roles_returns_none(tmp_path: Path) -> None:
    _write_manifest(tmp_path, roles=["producer"])
    assert on_feature_verified(tmp_path, "T-01") is None
    assert not (tmp_path / ".harness" / "review" / "T-01.json").exists()


def test_on_feature_verified_full_manifest_submits_for_review(tmp_path: Path) -> None:
    _write_manifest(tmp_path, roles=["producer", "reviewer"])
    result = on_feature_verified(tmp_path, "T-01")

    assert result is not None
    assert result["status"] == "in_review"

    review_path = tmp_path / ".harness" / "review" / "T-01.json"
    assert review_path.is_file()
    data = json.loads(review_path.read_text(encoding="utf-8"))
    assert data["status"] == "in_review"


def test_on_feature_verified_invalid_manifest_json_returns_none(tmp_path: Path) -> None:
    _write(tmp_path / ".harness" / "team" / "manifest.json", "{ nao e json valido")
    assert on_feature_verified(tmp_path, "T-01") is None
