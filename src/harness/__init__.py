"""harness-init — arcabouço de execução para agentes autônomos.

Agente = Modelo + Harness. O modelo raciocina; o harness garante execução
confiável, segurança e governança.

Imports preguiçosos: `AgentOrchestrator` puxa dependências pesadas
(anthropic, docker, mcp); camadas puras (config, budget, routing, EET)
permanecem importáveis sem elas.
"""

from typing import Any

__all__ = ["AgentOrchestrator", "HarnessConfig"]
# Fonte de verdade pro que fica gravado em .harness/feature_list.json
# (compiled_with_version) e .harness/compiled-state.json (plugin_version) -
# mudar aqui SEM bumpar .claude-plugin/plugin.json, .claude-plugin/marketplace.json
# e pyproject.toml deixa os quatro dessincronizados (ja aconteceu uma vez).
__version__ = "0.15.8"


def __getattr__(name: str) -> Any:
    if name == "AgentOrchestrator":
        from harness.orchestrator import AgentOrchestrator

        return AgentOrchestrator
    if name == "HarnessConfig":
        from harness.config import HarnessConfig

        return HarnessConfig
    raise AttributeError(f"module 'harness' has no attribute {name!r}")
