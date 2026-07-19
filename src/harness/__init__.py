"""harness-init — modo compilador: governança nativa do Claude Code.

Agente = Modelo + Harness. `compile`/`audit`/`analyze`/`review` compilam
.harness/harness.yaml para permissions/hooks/AGENTS.md nativos do Claude
Code e não dependem de Docker/Anthropic/MCP.
"""

from typing import Any

__all__ = ["HarnessConfig"]
# Fonte de verdade pro que fica gravado em .harness/feature_list.json
# (compiled_with_version) e .harness/compiled-state.json (plugin_version) -
# mudar aqui SEM bumpar .claude-plugin/plugin.json, .claude-plugin/marketplace.json
# e pyproject.toml deixa os quatro dessincronizados (ja aconteceu uma vez).
__version__ = "0.16.1"


def __getattr__(name: str) -> Any:
    if name == "HarnessConfig":
        from harness.config import HarnessConfig

        return HarnessConfig
    raise AttributeError(f"module 'harness' has no attribute {name!r}")
