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
    # Comandos permanentes que o dono do repo libera no boundary_guard além
    # do que já deriva de verify_cmd/lint/build/install/git local — mesma
    # semântica de PREFIXO de tokens que verify_cmd já tem.
    extra_allowed_commands: list[str] = Field(default_factory=list)
    # Fluxo branch-first (finding C do dogfood 2026-07-22): compile-session
    # cria/muda para `contract/<slug>` antes de instalar o guard. Branch é
    # decisão da FERRAMENTA, não do agente — nenhum comando git de branch é
    # liberado no boundary_guard por causa disto.
    branch_per_contract: bool = True
    # Branches onde `git commit` direto é proibido (só via PR) — o
    # boundary_guard nega commit nelas incondicionalmente (postura de floor),
    # além da proteção server-side configurada no GitHub.
    protected_branches: list[str] = Field(
        default_factory=lambda: ["main", "homolog", "develop"]
    )


class VerificationConfig(BaseModel):
    enforce_tdd: bool = True
    test_command: str = "pytest -x --tb=short"
    test_glob: str = "tests/**/*.py"


class HarnessConfig(BaseModel):
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
