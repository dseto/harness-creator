"""Schema de validação da configuração do harness (`.harness/harness.yaml`).

O YAML é lido e validado pelos consumidores (`compiler.py`, `audit.py`) via
`HarnessConfig.model_validate(raw)` — este módulo só define o schema.
"""

from __future__ import annotations

from typing import Literal

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


class VerificationConfig(BaseModel):
    enforce_tdd: bool = True
    test_command: str = "pytest -x --tb=short"
    test_glob: str = "tests/**/*.py"


class HarnessConfig(BaseModel):
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
