from typing import Any

from harness.tools.registry import ToolRegistry, ToolSpec, ToolExecutionError
from harness.tools.terminal import TerminalTool, CommandResult

__all__ = [
    "ToolRegistry",
    "ToolSpec",
    "ToolExecutionError",
    "MCPClient",
    "TerminalTool",
    "CommandResult",
]


def __getattr__(name: str) -> Any:
    # Preguiçoso: MCPClient depende do SDK `mcp`, dispensável para as demais
    # ferramentas e para os testes de fumaça.
    if name == "MCPClient":
        from harness.tools.mcp_client import MCPClient

        return MCPClient
    raise AttributeError(f"module 'harness.tools' has no attribute {name!r}")
