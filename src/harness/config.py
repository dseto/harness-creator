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


def generate_minimal_harness_config_yaml() -> str:
    """Gera YAML mínimo com defaults de HarnessConfig.

    Usado pelo CLI preflight quando arquivo não existe mas há warnings corrigíveis.
    Arquivo gerado é válido e pode ser customizado depois via `harness init`.
    """
    config = HarnessConfig()
    yaml_lines = [
        "# harness.yaml — configuração mínima gerada pelo preflight",
        "# Customize conforme necessário; `harness init` pode expandir depois",
        "",
        "governance:",
        f"  approval_policy: {config.governance.approval_policy}",
        "  budget:",
        f"    max_tokens_per_task: {config.governance.budget.max_tokens_per_task}",
        f"    max_tokens_per_session: {config.governance.budget.max_tokens_per_session}",
        f"    max_tool_calls_per_task: {config.governance.budget.max_tool_calls_per_task}",
        f"    max_green_iterations: {config.governance.budget.max_green_iterations}",
        f"  extra_allowed_commands: []",
        f"  branch_per_contract: {str(config.governance.branch_per_contract).lower()}",
        "  protected_branches:",
        "    - main",
        "    - homolog",
        "    - develop",
        "",
        "verification:",
        f"  enforce_tdd: {str(config.verification.enforce_tdd).lower()}",
        f"  test_command: {config.verification.test_command!r}",
        f"  test_glob: {config.verification.test_glob!r}",
    ]
    return "\n".join(yaml_lines)
