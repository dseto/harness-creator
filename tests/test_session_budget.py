"""Teste de Inc.6/B7 + Fix #5 — SessionBudget compartilhado, task_usage isolado.

Contrato: 1 AgentOrchestrator por tarefa. Um TaskManager (cockpit) cria UM
SessionBudget e injeta em cada instância. O teto de sessão acumula entre
tarefas; o task_usage fica isolado por instância (sem clobber concorrente)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from harness.config import BudgetConfig
from harness.governance.budget import SessionBudget, TokenBudget
from harness.orchestrator import AgentOrchestrator
from _helpers import FakeSandboxContext, make_test_config


def test_shared_session_does_not_clobber_per_task_counter() -> None:
    """Fix #5: reset_task numa tarefa não zera o task_usage de outra que
    compartilha o mesmo SessionBudget; a sessão soma as duas."""
    cfg = BudgetConfig(max_tokens_per_task=10_000, max_tokens_per_session=100_000)
    session = SessionBudget(cfg)
    b1 = TokenBudget(cfg, session=session)
    b2 = TokenBudget(cfg, session=session)

    b1.record_model_turn(300, 0)
    b2.record_model_turn(400, 0)
    b2.reset_task()  # reseta só b2

    assert b1.task_usage.total_tokens == 300      # NÃO foi zerado por b2
    assert b2.task_usage.total_tokens == 0
    assert session.usage.total_tokens == 700      # sessão contou os dois


def test_standalone_budget_still_enforces_session_ceiling() -> None:
    """Sem SessionBudget injetado (CLI de tarefa única), o teto de sessão
    continua valendo via SessionBudget criado internamente."""
    cfg = BudgetConfig(max_tokens_per_task=10_000, max_tokens_per_session=500)
    budget = TokenBudget(cfg)  # sem session=
    import pytest

    with pytest.raises(Exception):
        budget.record_model_turn(300, 300)  # 600 > 500 sessão


def _fake_response(input_tokens: int, output_tokens: int) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens)
    block = SimpleNamespace(type="text", text="ok")
    return SimpleNamespace(usage=usage, content=[block], stop_reason="end_turn")


async def test_session_budget_accumulates_across_orchestrator_instances(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    config = make_test_config(
        governance={
            "approval_policy": "auto",
            "budget": {
                "max_tokens_per_task": 1_000_000,   # não estoura por-tarefa
                "max_tokens_per_session": 1_500,     # estoura na 2a tarefa
                "max_tool_calls_per_task": 50,
                "max_green_iterations": 12,
            },
        }
    )
    shared = SessionBudget(config.governance.budget)

    orch1 = AgentOrchestrator(config, workspace, session_budget=shared)
    orch1._client.messages.create = AsyncMock(return_value=_fake_response(500, 500))
    result1 = await orch1.run_task("tarefa 1")
    assert result1["status"] == "completed"
    assert shared.usage.total_tokens == 1000

    orch2 = AgentOrchestrator(config, workspace, session_budget=shared)
    orch2._client.messages.create = AsyncMock(return_value=_fake_response(400, 400))
    result2 = await orch2.run_task("tarefa 2")

    # 1000 + 800 = 1800 > 1500 -> estoura teto de SESSÃO, mesmo com cada tarefa
    # isoladamente abaixo do teto por-tarefa (1_000_000).
    assert result2["status"] == "aborted_budget"
    assert shared.usage.total_tokens > config.governance.budget.max_tokens_per_session


async def test_independent_budgets_when_not_shared(workspace: Path, monkeypatch) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    config = make_test_config(
        governance={
            "approval_policy": "auto",
            "budget": {
                "max_tokens_per_task": 1_000_000,
                "max_tokens_per_session": 1_500,
                "max_tool_calls_per_task": 50,
                "max_green_iterations": 12,
            },
        }
    )

    orch1 = AgentOrchestrator(config, workspace)  # sem session_budget
    orch1._client.messages.create = AsyncMock(return_value=_fake_response(500, 500))
    result1 = await orch1.run_task("tarefa 1")

    orch2 = AgentOrchestrator(config, workspace)
    orch2._client.messages.create = AsyncMock(return_value=_fake_response(400, 400))
    result2 = await orch2.run_task("tarefa 2")

    assert result1["status"] == "completed"
    assert result2["status"] == "completed"
