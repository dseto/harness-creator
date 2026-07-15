"""Helpers de teste compartilhados (não é módulo de teste em si)."""

from __future__ import annotations

from dataclasses import dataclass, field

from harness.config import HarnessConfig, RoutingConfig
from harness.tools.terminal import CommandResult


def make_test_config(**overrides) -> HarnessConfig:
    base = {
        "routing": RoutingConfig(
            tiers={"trivial": "m", "simple": "m", "standard": "m", "complex": "m"}
        ),
    }
    base.update(overrides)
    return HarnessConfig(**base)


class FakeSandboxContext:
    """Substitui `SandboxEnvironment` como context manager assíncrono nos
    testes de `run_task`/`_agent_loop` — evita depender de Docker real."""

    def __init__(self, *_args, **_kwargs) -> None:
        self.sandbox = FakeSandbox()

    async def __aenter__(self) -> "FakeSandbox":
        return self.sandbox

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


@dataclass
class FakeSandbox:
    """Substitui SandboxEnvironment nos testes — sem Docker. `script` mapeia
    comando -> CommandResult; comando ausente retorna sucesso vazio."""

    script: dict[str, CommandResult] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    container_id: str | None = "fake-container-id"

    async def exec(self, command: str, timeout_s: int = 120) -> CommandResult:
        self.calls.append(command)
        if command in self.script:
            return self.script[command]
        return CommandResult(command=command, exit_code=0, stdout="", stderr="", duration_s=0.0)
