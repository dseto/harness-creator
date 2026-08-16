"""Testes de `harness.supervisor`: `ready_features`, `dispatch_next`,
`on_feature_verified`.

Arquivo dedicado (não anexado a test_contract.py/test_review.py) para não
colidir com tarefas concorrentes que editam esses módulos."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

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


# ---------------------------------------------------------------------------
# enforcement_gate (T-03, contrato setup-fail-closed-sem-init): `harness
# supervise` para com exit 1 quando há contrato ativo mas o enforcement não
# está de pé NESTA máquina -- mesmo gate de `harness verify`
# (ver tests/test_verify.py e harness.health.require_enforcement_installed).
# `dispatch_next` (testado acima) continua roda com contrato ativo e sem
# hooks/settings instalados -- o gate mora só em cli.py, este módulo não
# precisa saber que ele existe.
# ---------------------------------------------------------------------------

def _write_hooks_installed(tmp_path: Path) -> None:
    settings = {
        "hooks": {
            "PreToolUse": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": '"python" ".harness/hooks/boundary_guard.py" || exit 2',
                        }
                    ]
                }
            ]
        }
    }
    _write(
        tmp_path / ".claude" / "settings.local.json",
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n",
    )


def _write_harness_yaml(tmp_path: Path) -> None:
    # O gate (T-03) pressupõe um repositório GOVERNADO (já rodou
    # /harness-creator:init) clonado sem o output machine-local -- sem
    # harness.yaml é outro furo (T-01/T-02), fora do escopo deste gate.
    _write(tmp_path / ".harness" / "harness.yaml", "governance:\n  approval_policy: default\n")


def _enforcement_gate_case_hooks_missing(tmp_path: Path) -> None:
    _write_harness_yaml(tmp_path)
    _write_feature_list(tmp_path, [_feature("T-01")])
    # Sem .claude/settings.local.json nenhum -- hooks ausentes por definição.


def _enforcement_gate_case_killswitch_on(tmp_path: Path) -> None:
    from harness.killswitch import disable

    _write_harness_yaml(tmp_path)
    _write_feature_list(tmp_path, [_feature("T-01")])
    _write_hooks_installed(tmp_path)
    disable(tmp_path, note="teste enforcement_gate")


def _enforcement_gate_case_installed(tmp_path: Path) -> None:
    _write_harness_yaml(tmp_path)
    _write_feature_list(tmp_path, [_feature("T-01")])
    _write_hooks_installed(tmp_path)


def _enforcement_gate_case_no_active_contract(tmp_path: Path) -> None:
    # Nenhum .harness/feature_list.json -- sem contrato ativo, o gate não é
    # da conta deste comando (dispatch_next já devolve None sem gate nenhum).
    pass


@pytest.mark.parametrize(
    "setup, expect_exit, expect_in_stderr, forbid_in_stderr",
    [
        pytest.param(
            _enforcement_gate_case_hooks_missing, 1,
            "harness compile-session",
            ("harness enable",),
            id="hooks_missing",
        ),
        pytest.param(
            _enforcement_gate_case_killswitch_on, 1,
            "harness enable",
            ("harness compile-session",),
            id="killswitch_on",
        ),
        pytest.param(
            _enforcement_gate_case_installed, 0, None, (), id="enforcement_installed",
        ),
        pytest.param(
            _enforcement_gate_case_no_active_contract, 0, None,
            ("harness compile-session", "harness enable"),
            id="no_active_contract",
        ),
    ],
)
def test_supervise_enforcement_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    setup,
    expect_exit: int,
    expect_in_stderr: str | None,
    forbid_in_stderr: tuple[str, ...],
) -> None:
    from harness.cli import main

    setup(tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "supervise", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == expect_exit
    err = capsys.readouterr().err
    if expect_in_stderr is not None:
        assert expect_in_stderr in err, err
    for forbidden in forbid_in_stderr:
        assert forbidden not in err, err


def test_supervise_enforcement_gate_installed_returns_next_feature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Regra (3) do gate: com enforcement instalado, `harness supervise`
    preserva o comportamento de hoje -- devolve a próxima feature pronta."""
    from harness.cli import main

    _enforcement_gate_case_installed(tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "supervise", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["next"]["id"] == "T-01"


def test_supervise_enforcement_gate_no_active_contract_returns_null_next(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    """Regra (4) do gate: sem contrato ativo, `harness supervise` não é
    barrado por este gate -- comportamento de hoje preservado (`next: null`,
    razão já existente antes do T-03)."""
    from harness.cli import main

    monkeypatch.setattr(sys, "argv", ["harness", "supervise", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["next"] is None
