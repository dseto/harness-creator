"""Teste de Inc.11/B10 — aviso de custo zero e max_tokens configurável."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from harness.config import TelemetryConfig
from harness.orchestrator import AgentOrchestrator
from harness.telemetry.tracer import ExecutionTracer
from _helpers import FakeSandboxContext, make_test_config


def test_unknown_model_warns_exactly_once(tmp_path: Path) -> None:
    telemetry_config = TelemetryConfig(cost_table={})
    tracer = ExecutionTracer(telemetry_config, tmp_path, task_id="t1")

    tracer.record_model_turn(
        model="modelo-desconhecido", input_tokens=100, output_tokens=50,
        reasoning="x", stop_reason="end_turn",
    )
    tracer.record_model_turn(
        model="modelo-desconhecido", input_tokens=100, output_tokens=50,
        reasoning="y", stop_reason="end_turn",
    )

    trace_file = tmp_path / telemetry_config.trace_dir / "trace-t1.jsonl"
    lines = trace_file.read_text(encoding="utf-8").splitlines()
    warnings = [
        json.loads(line) for line in lines
        if json.loads(line).get("type") == "telemetry_warning"
    ]
    assert len(warnings) == 1
    assert "modelo-desconhecido" in warnings[0]["detail"]


def _fake_response() -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=10, output_tokens=10)
    block = SimpleNamespace(type="text", text="ok")
    return SimpleNamespace(usage=usage, content=[block], stop_reason="end_turn")


async def test_max_tokens_configurable_is_passed_to_model_call(
    workspace: Path, monkeypatch
) -> None:
    monkeypatch.setattr("harness.orchestrator.SandboxEnvironment", FakeSandboxContext)

    config = make_test_config(generation={"max_tokens": 1234})
    orchestrator = AgentOrchestrator(config, workspace)
    create_mock = AsyncMock(return_value=_fake_response())
    orchestrator._client.messages.create = create_mock

    await orchestrator.run_task("tarefa qualquer")

    _, kwargs = create_mock.call_args
    assert kwargs["max_tokens"] == 1234
