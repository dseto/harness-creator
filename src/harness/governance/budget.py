"""Camada 4 — orçamento de tokens: limites rígidos contra runaway loops.

Dois níveis, deliberadamente separados:

- **`SessionBudget`**: teto de tokens da SESSÃO inteira. É COMPARTILHADO entre
  tarefas — um TaskManager cria um e injeta em cada `TokenBudget` (via
  AgentOrchestrator). Só acumula; nunca é resetado por uma tarefa.
- **`TokenBudget`**: teto por TAREFA + backstop de tool calls. É por-instância
  (contrato: 1 AgentOrchestrator por tarefa). Referencia opcionalmente um
  `SessionBudget` compartilhado.

Separá-los é o que evita o bug de clobber: se o `task_usage` vivesse no objeto
compartilhado, uma tarefa entrando em `reset_task()` zeraria o contador de
outra tarefa concorrente em voo. Aqui `task_usage` é sempre local à instância.

Estourou qualquer teto -> BudgetExceededError -> o orquestrador encerra o loop.
Não é advisory: é hard stop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from harness.config import BudgetConfig


class BudgetExceededError(RuntimeError):
    """Teto de orçamento atingido. O loop do agente DEVE terminar."""


@dataclass
class UsageSnapshot:
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: int = 0

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class SessionBudget:
    """Acumulado da sessão, compartilhável entre tarefas. Nunca é resetado."""

    config: BudgetConfig
    usage: UsageSnapshot = field(default_factory=UsageSnapshot)

    def record(self, input_tokens: int, output_tokens: int) -> None:
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        self.enforce()

    def enforce(self) -> None:
        if self.usage.total_tokens > self.config.max_tokens_per_session:
            raise BudgetExceededError(
                f"Sessão excedeu {self.config.max_tokens_per_session:,} tokens."
            )


@dataclass
class TokenBudget:
    config: BudgetConfig
    session: SessionBudget | None = None
    task_usage: UsageSnapshot = field(default_factory=UsageSnapshot)

    def __post_init__(self) -> None:
        # Sem sessão compartilhada injetada (ex.: CLI de tarefa única), o
        # budget cria a sua própria — o teto de sessão continua valendo.
        if self.session is None:
            self.session = SessionBudget(self.config)

    def record_model_turn(self, input_tokens: int, output_tokens: int) -> None:
        self.task_usage.input_tokens += input_tokens
        self.task_usage.output_tokens += output_tokens
        self._enforce_task()
        # Sessão por último: pode levantar por teto de sessão mesmo com a
        # tarefa isolada abaixo do teto por-tarefa.
        self.session.record(input_tokens, output_tokens)

    def record_tool_call(self) -> None:
        self.task_usage.tool_calls += 1
        self._enforce_task()

    def enforce(self) -> None:
        self._enforce_task()
        self.session.enforce()

    def _enforce_task(self) -> None:
        c = self.config
        if self.task_usage.total_tokens > c.max_tokens_per_task:
            raise BudgetExceededError(
                f"Tarefa excedeu {c.max_tokens_per_task:,} tokens "
                f"(usados: {self.task_usage.total_tokens:,})."
            )
        if self.task_usage.tool_calls > c.max_tool_calls_per_task:
            raise BudgetExceededError(
                f"Tarefa excedeu {c.max_tool_calls_per_task} tool calls — provável runaway loop."
            )

    def reset_task(self) -> None:
        self.task_usage = UsageSnapshot()

    @property
    def remaining_task_tokens(self) -> int:
        return max(0, self.config.max_tokens_per_task - self.task_usage.total_tokens)
