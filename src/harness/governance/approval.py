"""Camada 4 — Human-in-the-Loop (HITL): políticas de aprovação configuráveis.

Três modos (config: governance.approval_policy):
  paranoid -> aprova literalmente tudo, inclusive leituras     (produção)
  balanced -> aprova tudo que muda estado: edit/execute/network (protótipos)
  auto     -> NÃO gateia edit/execute (auto-aprova); só network e edit_test
              seguem sempre gateados. NÃO é read-only — o agente pode editar
              arquivos e rodar comandos sem aprovação humana. Use apenas
              quando confiar na autonomia total do modelo.               (exploração)

A decisão usa o `risk_class` declarado no ToolSpec ("read" | "edit" |
"execute" | "network" | "edit_test"), nunca heurística sobre o nome da
ferramenta. `run_terminal` é "execute" porque um shell arbitrário pode
editar arquivos (`echo > file`) tão bem quanto uma tool de edição
dedicada — por isso `execute` fica no mesmo balde de risco que `edit` em
todo modo que não seja `auto`.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from harness.config import ApprovalMode

# Classes de risco sempre gateadas, independente do modo escolhido — nem
# "auto" as libera. "network" porque o sandbox é sem rede por padrão e
# abrir rede é decisão humana por definição; "edit_test" (Camada 2, TDD)
# porque editar teste é ação especial que nenhuma política automática deve
# aprovar sozinha.
_ALWAYS_GATED: set[str] = {"network", "edit_test"}

# Quais classes de risco adicionais exigem humano, por modo.
_POLICY_MATRIX: dict[ApprovalMode, set[str]] = {
    "paranoid": {"read", "edit", "execute", "network"},
    "balanced": {"edit", "execute", "network"},
    "auto": set(),
}

# Prompt padrão via terminal. Substituível por integração com Slack/PR review/
# UI web — basta injetar outro `prompt_fn` no construtor. `input()` roda em
# thread separada via `asyncio.to_thread`: bloqueia esta corrotina esperando
# o operador, mas NUNCA trava o event loop — outras tarefas concorrentes
# (múltiplas AgentOrchestrator no cockpit) continuam rodando enquanto isto
# espera stdin.
async def _default_prompt(message: str) -> bool:
    answer = await asyncio.to_thread(input, f"\n[HITL] {message}\nAprovar? [y/N] ")
    return answer.strip().lower() in {"y", "yes", "s", "sim"}


@dataclass
class ApprovalDecision:
    approved: bool
    reason: str


class ApprovalPolicy:
    def __init__(
        self,
        mode: ApprovalMode,
        prompt_fn: Callable[[str], Awaitable[bool]] | None = None,
    ) -> None:
        self.mode = mode
        self._requires_human = _POLICY_MATRIX[mode]
        self._prompt = prompt_fn or _default_prompt

    def needs_approval(self, risk_class: str) -> bool:
        if risk_class in _ALWAYS_GATED:
            return True
        return risk_class in self._requires_human

    async def gate(self, tool_name: str, risk_class: str, arguments: dict[str, Any]) -> ApprovalDecision:
        """Ponto único de decisão HITL. O orquestrador chama antes de todo dispatch."""
        if not self.needs_approval(risk_class):
            return ApprovalDecision(approved=True, reason=f"auto ({self.mode}/{risk_class})")

        summary = f"tool={tool_name} risk={risk_class} args={_truncate(arguments)}"
        approved = await self._prompt(summary)
        return ApprovalDecision(
            approved=approved,
            reason="aprovado pelo humano" if approved else "REJEITADO pelo humano",
        )


def _truncate(arguments: dict[str, Any], limit: int = 300) -> str:
    text = str(arguments)
    return text if len(text) <= limit else text[:limit] + "…"
