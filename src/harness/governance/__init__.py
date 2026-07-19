from typing import Any

from harness.governance.approval import ApprovalPolicy, ApprovalDecision

__all__ = [
    "SandboxEnvironment",
    "ApprovalPolicy",
    "ApprovalDecision",
    "TokenBudget",
    "SessionBudget",
    "BudgetExceededError",
    "UsageSnapshot",
]

_BUDGET_NAMES = {"TokenBudget", "SessionBudget", "BudgetExceededError", "UsageSnapshot"}


def __getattr__(name: str) -> Any:
    # Preguiçoso: sandbox depende do pacote `docker`, dispensável para
    # testar as demais camadas de governança.
    if name == "SandboxEnvironment":
        from harness.governance.sandbox import SandboxEnvironment

        return SandboxEnvironment
    # Preguiçoso: mantém `harness.governance` fora do load-path do modo
    # compilador (compiler/audit/analyzer/review só precisam de `approval`).
    if name in _BUDGET_NAMES:
        from harness.governance import budget

        return getattr(budget, name)
    raise AttributeError(f"module 'harness.governance' has no attribute {name!r}")
