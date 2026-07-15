"""Camada 6 — ModelRouter: tarefa certa no modelo certo.

Tarefas triviais/simples (navegação, pequenas edições) -> modelo pequeno e
barato. Coordenação e raciocínio arquitetural -> modelo de fronteira. Mapa
tier -> model_id vem de config/harness.yaml; nada hard-coded.

v0 classifica por heurística de palavras-chave. Interface pronta para trocar
por classificador LLM barato ou modelo aprendido sem tocar o orquestrador.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from harness.config import RoutingConfig


class TaskTier(str, Enum):
    TRIVIAL = "trivial"      # leitura, navegação de arquivos, perguntas pontuais
    SIMPLE = "simple"        # pequenas edições, renomes, ajustes de config
    STANDARD = "standard"    # implementação de features com TDD
    COMPLEX = "complex"      # arquitetura, coordenação, refactors cross-cutting


_TIER_KEYWORDS: dict[TaskTier, tuple[str, ...]] = {
    TaskTier.TRIVIAL: ("listar", "ler", "mostrar", "encontrar", "onde está", "list", "read", "find", "show"),
    TaskTier.SIMPLE: ("renomear", "typo", "pequena edição", "ajustar config", "rename", "small edit", "bump"),
    TaskTier.COMPLEX: ("arquitetura", "redesign", "migração", "refatorar sistema", "coordenar",
                       "architecture", "migration", "cross-cutting", "design"),
}


@dataclass
class RoutingDecision:
    tier: TaskTier
    model: str
    rationale: str


class ModelRouter:
    def __init__(self, config: RoutingConfig) -> None:
        self._cfg = config

    def route(self, task_description: str, forced_tier: TaskTier | None = None) -> RoutingDecision:
        tier = forced_tier or self._classify(task_description)
        model = self._cfg.tiers.get(tier.value) or self._cfg.tiers[self._cfg.default_tier]
        return RoutingDecision(
            tier=tier,
            model=model,
            rationale=f"classificado como '{tier.value}'"
            + (" (forçado)" if forced_tier else " por heurística de keywords"),
        )

    def escalate(self, decision: RoutingDecision) -> RoutingDecision:
        """Escalonamento: tarefa travou no modelo barato -> sobe um tier.
        Chamado pelo orquestrador após falhas repetidas abaixo do limite EET."""
        order = [TaskTier.TRIVIAL, TaskTier.SIMPLE, TaskTier.STANDARD, TaskTier.COMPLEX]
        idx = min(order.index(decision.tier) + 1, len(order) - 1)
        return self.route("", forced_tier=order[idx])

    @staticmethod
    def _classify(task: str) -> TaskTier:
        text = task.lower()
        for tier in (TaskTier.COMPLEX, TaskTier.TRIVIAL, TaskTier.SIMPLE):
            if any(kw in text for kw in _TIER_KEYWORDS[tier]):
                return tier
        return TaskTier.STANDARD
