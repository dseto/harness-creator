"""Teste de Inc.10/B8 — escalonamento de tier acionado antes da terminação."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from harness.orchestrator import AgentOrchestrator
from harness.routing.eet import EETEvaluator, EETVerdict
from harness.routing.router import ModelRouter
from _helpers import FakeSandboxContext, make_test_config


def _tool_use_response(tool_name: str, tool_input: dict) -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=10, output_tokens=10)
    block = SimpleNamespace(type="tool_use", id="call_1", name=tool_name, input=tool_input)
    return SimpleNamespace(usage=usage, content=[block], stop_reason="tool_use")


def _text_response() -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=10, output_tokens=10)
    block = SimpleNamespace(type="text", text="done")
    return SimpleNamespace(usage=usage, content=[block], stop_reason="end_turn")


async def test_escalation_triggered_once_before_hard_termination(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    # Confiança sempre "degradada mas não fatal": abaixo do soft (0.45),
    # acima do duro (0.25) -> deve escalar, nunca terminar por EET.
    def fake_evaluate(self) -> EETVerdict:
        return EETVerdict(terminate=False, confidence=0.35, reason="degradado (teste)")

    monkeypatch.setattr(EETEvaluator, "evaluate", fake_evaluate)

    escalate_calls: list[str] = []
    original_escalate = ModelRouter.escalate

    def spy_escalate(self, decision):
        escalate_calls.append(decision.tier.value)
        return original_escalate(self, decision)

    monkeypatch.setattr(ModelRouter, "escalate", spy_escalate)

    (workspace / "readme.txt").write_text("oi", encoding="utf-8")

    config = make_test_config()
    orchestrator = AgentOrchestrator(config, workspace)
    orchestrator._client.messages.create = AsyncMock(
        side_effect=[
            _tool_use_response("read_file", {"path": "readme.txt"}),
            _text_response(),
        ]
    )

    result = await orchestrator.run_task("tarefa qualquer")

    assert result["status"] == "completed"
    # Escalou exatamente 1 vez ao longo da tarefa (2 turns), não a cada turn —
    # evita ping-pong entre tiers.
    assert len(escalate_calls) == 1
