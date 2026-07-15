"""Camada 1 — ToolRegistry: catálogo único de ferramentas (nativas + MCP).

Para o modelo, toda ferramenta é uma entrada com nome + JSON Schema. A origem
(função Python local ou servidor MCP remoto) é detalhe de despacho.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol


class ToolExecutionError(Exception):
    """Falha na execução de uma ferramenta. Carrega payload estruturado
    para que o orquestrador devolva o erro ao modelo (autocorreção)."""

    def __init__(self, message: str, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.payload = payload or {}


@dataclass
class ToolSpec:
    """Definição de ferramenta no formato aceito pela API do modelo."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., Awaitable[Any]]
    # Classificação usada pelo ApprovalPolicy (HITL):
    #   "read"     -> leitura, sem efeito colateral
    #   "edit"     -> modifica arquivos do workspace
    #   "execute"  -> executa comandos / código
    #   "network"  -> tocaria rede (bloqueado por padrão no sandbox)
    risk_class: str = "read"
    source: str = "native"  # "native" | "mcp:<server>"

    def to_api_format(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
        }


class ToolRegistry:
    """Registro central. O orquestrador só conhece esta interface."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.name in self._tools:
            raise ValueError(f"Ferramenta duplicada: {spec.name}")
        self._tools[spec.name] = spec

    def register_native(
        self,
        name: str,
        description: str,
        input_schema: dict[str, Any],
        handler: Callable[..., Awaitable[Any]],
        risk_class: str = "read",
    ) -> None:
        self.register(
            ToolSpec(
                name=name,
                description=description,
                input_schema=input_schema,
                handler=handler,
                risk_class=risk_class,
                source="native",
            )
        )

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise ToolExecutionError(
                f"Ferramenta desconhecida: {name}",
                payload={"known_tools": sorted(self._tools)},
            )

    def to_api_format(self) -> list[dict[str, Any]]:
        """Lista de ferramentas no formato do endpoint de Messages."""
        return [spec.to_api_format() for spec in self._tools.values()]

    async def dispatch(self, name: str, arguments: dict[str, Any]) -> Any:
        """Executa a ferramenta. Erros viram ToolExecutionError estruturado —
        nunca exceção crua vazando para o loop do agente."""
        spec = self.get(name)
        try:
            result = spec.handler(**arguments)
            if inspect.isawaitable(result):
                result = await result
            return result
        except ToolExecutionError:
            raise
        except Exception as exc:  # noqa: BLE001 — fronteira de despacho
            raise ToolExecutionError(
                f"Erro em '{name}': {exc}",
                payload={"tool": name, "arguments": arguments, "error": repr(exc)},
            ) from exc
