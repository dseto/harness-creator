"""Carregamento e validação da configuração do harness (config/harness.yaml)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field

ApprovalMode = Literal["paranoid", "balanced", "auto"]


class BudgetConfig(BaseModel):
    max_tokens_per_task: int = 500_000
    max_tokens_per_session: int = 2_000_000
    max_tool_calls_per_task: int = 120
    max_green_iterations: int = 12


class GovernanceConfig(BaseModel):
    approval_policy: ApprovalMode = "balanced"
    budget: BudgetConfig = Field(default_factory=BudgetConfig)


class SandboxConfig(BaseModel):
    image: str = "harness-sandbox:latest"
    network_mode: str = "none"
    mem_limit: str = "2g"
    cpu_quota: int = 200_000
    pids_limit: int = 256
    workspace_mount: str = "/workspace"
    ephemeral: bool = True


class RoutingConfig(BaseModel):
    # tiers vazio é válido no modo plugin (compile/audit não roteiam modelo);
    # o orquestrador congelado ainda exige tiers preenchidos para executar.
    tiers: dict[str, str] = Field(default_factory=dict)
    default_tier: str = "standard"


class VerificationConfig(BaseModel):
    enforce_tdd: bool = True
    test_command: str = "pytest -x --tb=short"
    test_glob: str = "tests/**/*.py"


class EETConfig(BaseModel):
    enabled: bool = True
    confidence_threshold: float = 0.25       # abaixo disso -> termina cedo
    escalate_confidence_threshold: float = 0.45  # abaixo disso (mas acima do hard) -> escala tier
    min_turns_before_eval: int = 4
    repeated_failure_limit: int = 3


class ContextConfig(BaseModel):
    governance_files: list[str] = ["AGENTS.md", "CLAUDE.md"]
    memory_dir: str = ".harness/memory"
    index: dict[str, list[str]] = Field(
        default_factory=lambda: {"include": ["**/*.py"], "exclude": []}
    )


class GenerationConfig(BaseModel):
    max_tokens: int = 8192


class TelemetryConfig(BaseModel):
    trace_dir: str = ".harness/traces"
    capture_reasoning: bool = True
    cost_table: dict[str, dict[str, float]] = Field(default_factory=dict)


class MCPServerConfig(BaseModel):
    name: str
    transport: Literal["stdio", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None  # para transport=sse


class MCPConfig(BaseModel):
    servers: list[MCPServerConfig] = Field(default_factory=list)
    # Servidores MCP stdio hoje rodam como subprocesso NO HOST (fora do
    # sandbox sem rede) — ver ARCHITECTURE.md. Desligado por default;
    # habilitar é decisão explícita de quem opera o harness.
    allow_host_execution: bool = False


class HarnessConfig(BaseModel):
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
    generation: GenerationConfig = Field(default_factory=GenerationConfig)
    eet: EETConfig = Field(default_factory=EETConfig)
    context: ContextConfig = Field(default_factory=ContextConfig)
    telemetry: TelemetryConfig = Field(default_factory=TelemetryConfig)
    mcp: MCPConfig = Field(default_factory=MCPConfig)

    @classmethod
    def load(cls, path: str | Path = "config/harness.yaml") -> "HarnessConfig":
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)
