"""Testes de Inc.2 (matriz de aprovação honesta) e Inc.3 (MCP isolado por default)."""

from harness.config import MCPConfig
from harness.governance.approval import ApprovalPolicy


def test_balanced_gates_execute() -> None:
    # Bug central do B1: run_terminal é "execute"; balanced tinha esquecido
    # de gatear essa classe, deixando-a se comportar como "auto".
    policy = ApprovalPolicy("balanced")
    assert policy.needs_approval("execute") is True


def test_balanced_gates_edit_and_network() -> None:
    policy = ApprovalPolicy("balanced")
    assert policy.needs_approval("edit") is True
    assert policy.needs_approval("network") is True


def test_balanced_does_not_gate_read() -> None:
    policy = ApprovalPolicy("balanced")
    assert policy.needs_approval("read") is False


def test_paranoid_gates_everything_including_read() -> None:
    policy = ApprovalPolicy("paranoid")
    for risk in ("read", "edit", "execute", "network"):
        assert policy.needs_approval(risk) is True


def test_auto_gates_only_always_gated_classes() -> None:
    policy = ApprovalPolicy("auto")
    assert policy.needs_approval("read") is False
    assert policy.needs_approval("edit") is False
    assert policy.needs_approval("execute") is False
    # network é sempre gateado, mesmo em auto — sandbox sem rede é o padrão.
    assert policy.needs_approval("network") is True


async def test_gate_rejects_when_prompt_returns_false() -> None:
    async def always_reject(_message: str) -> bool:
        return False

    policy = ApprovalPolicy("balanced", prompt_fn=always_reject)
    decision = await policy.gate("run_terminal", "execute", {"command": "echo hi"})
    assert decision.approved is False


async def test_gate_auto_approves_read_without_prompting() -> None:
    called = False

    async def fail_if_called(_message: str) -> bool:
        nonlocal called
        called = True
        return True

    policy = ApprovalPolicy("balanced", prompt_fn=fail_if_called)
    decision = await policy.gate("read_file", "read", {"path": "x.py"})
    assert decision.approved is True
    assert called is False


def test_mcp_disabled_by_default() -> None:
    assert MCPConfig().allow_host_execution is False
