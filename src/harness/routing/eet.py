"""Camada 6 — EETEvaluator: Experience-Driven Early Termination (PLACEHOLDER).

Objetivo: interromper execuções redundantes precocemente com base em
pontuação de confiança, evitando gasto de API quando o agente trava em
tarefa impossível ou entra em trajetória degenerada.

v0 (este arquivo) = heurísticas determinísticas sobre a trajetória:
  - mesma ferramenta + mesmos argumentos repetidos N vezes;
  - mesma assinatura de falha (stderr) repetida N vezes;
  - ausência de eventos de progresso (edição nova, teste novo passando).

v1 (futuro) = modelo aprendido sobre trajetórias históricas do
ExecutionTracer (.harness/traces/*.jsonl): treinar um classificador
"vai convergir?" e substituir apenas `score()` — a interface é o contrato.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from dataclasses import dataclass, field

from harness.config import EETConfig


@dataclass
class TrajectoryStep:
    """Resumo de um turn do agente, alimentado pelo orquestrador."""

    tool: str | None
    arguments_digest: str
    failed: bool
    failure_signature: str | None   # ex: primeira linha do stderr
    made_progress: bool             # arquivo novo editado, teste passou, etc.

    @staticmethod
    def digest(arguments: dict) -> str:
        return hashlib.sha256(repr(sorted(arguments.items())).encode()).hexdigest()[:16]


@dataclass
class EETVerdict:
    terminate: bool
    confidence: float               # confiança de que a trajetória converge [0, 1]
    reason: str


@dataclass
class EETEvaluator:
    config: EETConfig
    steps: list[TrajectoryStep] = field(default_factory=list)

    def observe(self, step: TrajectoryStep) -> None:
        self.steps.append(step)

    def evaluate(self) -> EETVerdict:
        if not self.config.enabled or len(self.steps) < self.config.min_turns_before_eval:
            return EETVerdict(terminate=False, confidence=1.0, reason="janela mínima não atingida")

        confidence = self.score()
        if confidence < self.config.confidence_threshold:
            return EETVerdict(
                terminate=True,
                confidence=confidence,
                reason=(
                    f"confiança {confidence:.2f} < limiar {self.config.confidence_threshold} — "
                    "trajetória degenerada (repetição sem progresso). Terminando cedo para "
                    "poupar orçamento; escalar para humano ou tier superior."
                ),
            )
        return EETVerdict(terminate=False, confidence=confidence, reason="trajetória saudável")

    # ------------------------------------------------------------------
    # PLACEHOLDER: substituir por modelo aprendido (experience-driven).
    # Contrato: retorna confiança de convergência em [0, 1].
    # ------------------------------------------------------------------
    def score(self) -> float:
        recent = self.steps[-10:]
        penalty = 0.0

        # 1. Ação idêntica repetida (mesma ferramenta + mesmos argumentos).
        actions = Counter((s.tool, s.arguments_digest) for s in recent if s.tool)
        max_repeat = max(actions.values(), default=0)
        if max_repeat >= self.config.repeated_failure_limit:
            penalty += 0.4

        # 2. Mesma assinatura de falha repetida.
        failures = Counter(s.failure_signature for s in recent if s.failed and s.failure_signature)
        if failures and max(failures.values()) >= self.config.repeated_failure_limit:
            penalty += 0.4

        # 3. Nenhum progresso na janela recente.
        if recent and not any(s.made_progress for s in recent):
            penalty += 0.3

        return max(0.0, 1.0 - penalty)
