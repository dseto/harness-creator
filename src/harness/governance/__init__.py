from typing import Any

from harness.governance.approval import ApprovalPolicy, ApprovalDecision
from harness.governance.budget import (
    TokenBudget,
    SessionBudget,
    BudgetExceededError,
    UsageSnapshot,
)

__all__ = [
    "SandboxEnvironment",
    "ApprovalPolicy",
    "ApprovalDecision",
    "TokenBudget",
    "SessionBudget",
    "BudgetExceededError",
    "UsageSnapshot",
]


def __getattr__(name: str) -> Any:
    # Preguiçoso: sandbox depende do pacote `docker`, dispensável para
    # testar as demais camadas de governança.
    if name == "SandboxEnvironment":
        from harness.governance.sandbox import SandboxEnvironment

        return SandboxEnvironment
    raise AttributeError(f"module 'harness.governance' has no attribute {name!r}")
