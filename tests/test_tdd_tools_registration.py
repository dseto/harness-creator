"""Testes de Inc.4 — tools TDD completas registradas com risk_class correto."""

from pathlib import Path

from harness.governance.approval import ApprovalPolicy
from harness.orchestrator import AgentOrchestrator
from _helpers import FakeSandbox, make_test_config


def _build_orchestrator(workspace: Path) -> AgentOrchestrator:
    config = make_test_config()
    orchestrator = AgentOrchestrator(config, workspace)
    orchestrator._register_core_tools(FakeSandbox())
    return orchestrator


def test_tdd_request_test_edit_is_edit_test_risk(workspace: Path) -> None:
    orchestrator = _build_orchestrator(workspace)
    spec = orchestrator.registry.get("tdd_request_test_edit")
    assert spec.risk_class == "edit_test"


def test_edit_test_always_gated_even_in_auto() -> None:
    assert ApprovalPolicy("auto").needs_approval("edit_test") is True
    assert ApprovalPolicy("paranoid").needs_approval("edit_test") is True
    assert ApprovalPolicy("balanced").needs_approval("edit_test") is True


def test_all_tdd_lifecycle_tools_registered(workspace: Path) -> None:
    orchestrator = _build_orchestrator(workspace)
    for name in (
        "tdd_assert_red",
        "tdd_try_green",
        "tdd_assert_still_green",
        "tdd_finish",
        "tdd_request_test_edit",
    ):
        assert orchestrator.registry.get(name) is not None


def test_tdd_cycle_stored_for_guard_access(workspace: Path) -> None:
    orchestrator = _build_orchestrator(workspace)
    assert orchestrator._tdd_cycle is not None
    assert orchestrator._tdd_cycle.test_command == "pytest -x --tb=short"
