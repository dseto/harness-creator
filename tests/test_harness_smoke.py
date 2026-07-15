"""Testes de fumaça das camadas de governança — rodam sem Docker nem API."""

from pathlib import Path

import pytest

from harness.config import BudgetConfig, EETConfig, RoutingConfig
from harness.governance.budget import BudgetExceededError, TokenBudget
from harness.routing.eet import EETEvaluator, TrajectoryStep
from harness.routing.router import ModelRouter, TaskTier
from harness.tools.registry import ToolExecutionError, ToolRegistry


def test_budget_hard_stop() -> None:
    budget = TokenBudget(BudgetConfig(max_tokens_per_task=100))
    with pytest.raises(BudgetExceededError):
        budget.record_model_turn(input_tokens=90, output_tokens=20)


def test_budget_tool_call_backstop() -> None:
    budget = TokenBudget(BudgetConfig(max_tool_calls_per_task=2))
    budget.record_tool_call()
    budget.record_tool_call()
    with pytest.raises(BudgetExceededError):
        budget.record_tool_call()


def test_router_sends_architecture_to_frontier() -> None:
    router = ModelRouter(RoutingConfig(tiers={
        "trivial": "cheap", "simple": "cheap", "standard": "mid", "complex": "frontier",
    }))
    assert router.route("redesenhar a arquitetura do módulo de billing").model == "frontier"
    assert router.route("listar arquivos do diretório src").model == "cheap"


def test_eet_terminates_degenerate_trajectory() -> None:
    eet = EETEvaluator(EETConfig(min_turns_before_eval=3, repeated_failure_limit=3))
    step = TrajectoryStep(
        tool="run_terminal",
        arguments_digest="abc",
        failed=True,
        failure_signature="ModuleNotFoundError: x",
        made_progress=False,
    )
    for _ in range(5):
        eet.observe(step)
    verdict = eet.evaluate()
    assert verdict.terminate
    assert verdict.confidence < 0.25


def test_registry_unknown_tool_is_structured_error() -> None:
    registry = ToolRegistry()
    with pytest.raises(ToolExecutionError) as excinfo:
        registry.get("nao_existe")
    assert "known_tools" in excinfo.value.payload
