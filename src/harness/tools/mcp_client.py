"""Camada 1 — Cliente Model Context Protocol (MCP).

Conecta a servidores MCP (stdio/SSE), descobre ferramentas dinamicamente e as
registra no ToolRegistry com namespace `mcp__<server>__<tool>`.

Usa o SDK oficial `mcp` (https://github.com/modelcontextprotocol/python-sdk).
"""

from __future__ import annotations

import os
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from harness.config import MCPServerConfig
from harness.tools.registry import ToolRegistry, ToolSpec


def _expand_env(env: dict[str, str]) -> dict[str, str]:
    """Expande referências ${VAR} nos valores de env do harness.yaml."""
    return {k: os.path.expandvars(v) for k, v in env.items()}


class MCPClient:
    """Gerencia o ciclo de vida das conexões MCP de uma sessão do harness."""

    def __init__(self) -> None:
        self._stack = AsyncExitStack()
        self._sessions: dict[str, ClientSession] = {}

    async def connect(self, server: MCPServerConfig) -> ClientSession:
        if server.transport != "stdio":
            raise NotImplementedError(
                f"Transporte '{server.transport}' ainda não suportado (apenas stdio)."
            )
        params = StdioServerParameters(
            command=server.command or "",
            args=server.args,
            env={**os.environ, **_expand_env(server.env)},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params))
        session = await self._stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        self._sessions[server.name] = session
        return session

    async def register_tools(self, server: MCPServerConfig, registry: ToolRegistry) -> int:
        """Descobre ferramentas do servidor (tools/list) e registra cada uma.

        Retorna quantidade registrada."""
        session = self._sessions.get(server.name) or await self.connect(server)
        listing = await session.list_tools()
        count = 0
        for tool in listing.tools:
            namespaced = f"mcp__{server.name}__{tool.name}"

            async def _handler(
                _session: ClientSession = session,
                _tool_name: str = tool.name,
                **arguments: Any,
            ) -> Any:
                result = await _session.call_tool(_tool_name, arguments=arguments)
                # Conteúdo MCP -> texto simples para o contexto do modelo.
                parts = [c.text for c in result.content if getattr(c, "text", None)]
                return "\n".join(parts) if parts else str(result.content)

            registry.register(
                ToolSpec(
                    name=namespaced,
                    description=tool.description or f"Ferramenta MCP de {server.name}",
                    input_schema=tool.inputSchema or {"type": "object", "properties": {}},
                    handler=_handler,
                    # "network": servidores MCP stdio hoje rodam no HOST, fora
                    # do sandbox sem rede — risco sempre gateado, em todo modo
                    # (ver _ALWAYS_GATED em governance/approval.py).
                    risk_class="network",
                    source=f"mcp:{server.name}",
                )
            )
            count += 1
        return count

    async def close(self) -> None:
        await self._stack.aclose()
        self._sessions.clear()
