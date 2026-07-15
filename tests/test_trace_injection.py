"""Teste de Inc.7 — task_id/tracer injetáveis em run_task.

Prova que um chamador externo (ex.: TaskManager do cockpit) pode criar o
ExecutionTracer com um task_id conhecido ANTES de agendar a tarefa e seguir
o arquivo .jsonl em tempo real, sem esperar o fim de run_task."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from harness.telemetry.tracer import ExecutionTracer
from harness.orchestrator import AgentOrchestrator
from _helpers import FakeSandboxContext, make_test_config


def _fake_response() -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=10, output_tokens=10)
    block = SimpleNamespace(type="text", text="ok")
    return SimpleNamespace(usage=usage, content=[block], stop_reason="end_turn")


async def test_tracer_created_before_run_task_is_followable(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    config = make_test_config()
    tracer = ExecutionTracer(config.telemetry, workspace, task_id="minha-tarefa-123")

    trace_file = workspace / config.telemetry.trace_dir / "trace-minha-tarefa-123.jsonl"
    # O arquivo já existe (com o evento trace_start) ANTES de run_task rodar.
    assert trace_file.is_file()

    orchestrator = AgentOrchestrator(config, workspace)
    orchestrator._client.messages.create = AsyncMock(return_value=_fake_response())

    summary = await orchestrator.run_task("tarefa qualquer", tracer=tracer)

    assert summary["trace_id"] == "minha-tarefa-123"


async def test_run_task_without_injection_still_generates_trace_id(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    config = make_test_config()
    orchestrator = AgentOrchestrator(config, workspace)
    orchestrator._client.messages.create = AsyncMock(return_value=_fake_response())

    summary = await orchestrator.run_task("tarefa qualquer")

    assert summary["trace_id"]  # gerado internamente, compatibilidade com a CLI
