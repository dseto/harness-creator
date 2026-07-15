"""Regressões dos fixes do code-review (#1, #2, #8) não cobertas alhures."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness.orchestrator import AgentOrchestrator
from harness.routing.eet import EETEvaluator
from harness.telemetry.tracer import ExecutionTracer
from harness.tools.terminal import CommandResult
from harness.verification.tdd_loop import TDDCycle
from _helpers import FakeSandbox, FakeSandboxContext, make_test_config


# ---------- Fix #1: is_test_path com glob real e path resolvido ----------

def _cycle(workspace: Path, test_glob: str) -> TDDCycle:
    return TDDCycle(
        sandbox=FakeSandbox(), workspace=workspace,
        test_command="pytest -x --tb=short", test_glob=test_glob,
    )


def test_is_test_path_does_not_overblock_with_recursive_glob(workspace: Path) -> None:
    """Com '**/test_*.py', um .py de implementação NÃO pode ser tratado como
    teste (o parse manual antigo marcava todo .py)."""
    cycle = _cycle(workspace, "**/test_*.py")
    assert cycle.is_test_path("src/orchestrator.py") is False
    assert cycle.is_test_path("tests/test_x.py") is True
    assert cycle.is_test_path("tests/sub/test_y.py") is True


def test_is_test_path_matches_direct_child_with_tests_glob(workspace: Path) -> None:
    cycle = _cycle(workspace, "tests/**/*.py")
    assert cycle.is_test_path("tests/test_x.py") is True
    assert cycle.is_test_path("tests/sub/test_y.py") is True
    assert cycle.is_test_path("src/x.py") is False


def test_is_test_path_resolves_dotdot_bypass(workspace: Path) -> None:
    """'src/../tests/test_x.py' resolve para dentro de tests/ e deve ser
    reconhecido como teste (fecha o bypass textual)."""
    cycle = _cycle(workspace, "tests/**/*.py")
    assert cycle.is_test_path("src/../tests/test_x.py") is True


# ---------- Fix #2: tool alucinada não crasha a tarefa ----------

async def test_unknown_tool_returns_error_not_crash(workspace: Path) -> None:
    config = make_test_config()
    orchestrator = AgentOrchestrator(config, workspace)
    orchestrator._register_core_tools(FakeSandbox())

    tracer = ExecutionTracer(config.telemetry, workspace, task_id="unknown-tool")
    eet = EETEvaluator(config.eet)

    result = await orchestrator._execute_tool(
        name="edit_file",  # não registrada (alucinação)
        arguments={"path": "x"},
        tracer=tracer,
        eet=eet,
    )

    assert "error" in result
    assert "known_tools" in result  # payload estruturado para autocorreção


# ---------- Fix #8: run_task não-reentrante ----------

def _fake_response() -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=10, output_tokens=10)
    block = SimpleNamespace(type="text", text="ok")
    return SimpleNamespace(usage=usage, content=[block], stop_reason="end_turn")


async def test_run_task_is_not_reentrant(workspace: Path, monkeypatch) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    config = make_test_config()
    orchestrator = AgentOrchestrator(config, workspace)
    orchestrator._client.messages.create = AsyncMock(return_value=_fake_response())

    result1 = await orchestrator.run_task("tarefa 1")
    assert result1["status"] == "completed"

    with pytest.raises(RuntimeError, match="não é reutilizável"):
        await orchestrator.run_task("tarefa 2")
