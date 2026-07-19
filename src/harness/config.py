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


class VerificationConfig(BaseModel):
    enforce_tdd: bool = True
    test_command: str = "pytest -x --tb=short"
    test_glob: str = "tests/**/*.py"


class HarnessConfig(BaseModel):
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)

    @classmethod
    def load(cls, path: str | Path = "config/harness.yaml") -> "HarnessConfig":
        raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        return cls.model_validate(raw)
