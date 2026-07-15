"""Camada 5 — ExecutionTracer: telemetria estruturada (JSONL).

Captura por evento: estado do ambiente, tokens, custo estimado e o histórico
completo do raciocínio do modelo (execution tracing). Base para métricas de
ROI como "Custo por PR Mesclado".
"""

from __future__ import annotations

import json
import platform
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from harness.config import TelemetryConfig


class ExecutionTracer:
    def __init__(self, config: TelemetryConfig, repo_root: Path, task_id: str | None = None) -> None:
        self._cfg = config
        self.trace_id = task_id or uuid.uuid4().hex[:12]
        self._dir = repo_root / config.trace_dir
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = self._dir / f"trace-{self.trace_id}.jsonl"
        self._cost_usd = 0.0
        self._warned_unknown_models: set[str] = set()
        self.emit("trace_start", environment=self._environment_snapshot())

    # ---------- emissão ----------

    def emit(self, event_type: str, span_id: str | None = None, **payload: Any) -> None:
        record = {
            "ts": time.time(),
            "trace_id": self.trace_id,
            "span_id": span_id or uuid.uuid4().hex[:8],
            "type": event_type,
            **payload,
        }
        with self._file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    @contextmanager
    def span(self, name: str, **attrs: Any) -> Iterator[str]:
        span_id = uuid.uuid4().hex[:8]
        start = time.monotonic()
        self.emit("span_start", span_id=span_id, name=name, **attrs)
        try:
            yield span_id
            self.emit("span_end", span_id=span_id, name=name,
                      duration_s=time.monotonic() - start, status="ok")
        except Exception as exc:
            self.emit("span_end", span_id=span_id, name=name,
                      duration_s=time.monotonic() - start, status="error", error=repr(exc))
            raise

    # ---------- eventos de domínio ----------

    def record_model_turn(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        reasoning: str | None,
        stop_reason: str | None,
    ) -> None:
        cost = self._estimate_cost(model, input_tokens, output_tokens)
        self._cost_usd += cost
        self.emit(
            "model_turn",
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=round(cost, 6),
            cumulative_cost_usd=round(self._cost_usd, 6),
            stop_reason=stop_reason,
            # Histórico completo do raciocínio — desligável via config.
            reasoning=reasoning if self._cfg.capture_reasoning else "[capture_reasoning=false]",
        )

    def record_tool_call(self, tool: str, arguments: dict, result_summary: str, ok: bool) -> None:
        self.emit("tool_call", tool=tool, arguments=arguments,
                  result_summary=result_summary[:2000], ok=ok)

    def record_governance(self, kind: str, detail: str) -> None:
        """Eventos HITL, budget, TDD violations, EET — trilha de auditoria."""
        self.emit("governance", kind=kind, detail=detail)

    # ---------- ROI ----------

    def roi_summary(self) -> dict:
        """Insumo para 'Custo por PR Mesclado': custo total desta trace.
        Agregação por PR acontece a jusante (join trace_id x PR mesclado)."""
        return {"trace_id": self.trace_id, "total_cost_usd": round(self._cost_usd, 4)}

    # ---------- internos ----------

    def _estimate_cost(self, model: str, input_tokens: int, output_tokens: int) -> float:
        table = self._cfg.cost_table.get(model)
        if not table:
            if model not in self._warned_unknown_models:
                self._warned_unknown_models.add(model)
                self.emit(
                    "telemetry_warning",
                    detail=f"custo zerado: modelo '{model}' ausente em cost_table",
                )
            return 0.0
        return (
            input_tokens * table.get("input", 0.0)
            + output_tokens * table.get("output", 0.0)
        ) / 1_000_000

    @staticmethod
    def _environment_snapshot() -> dict:
        return {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "hostname": platform.node(),
        }
