"""Schema de validação da configuração do harness (`.harness/harness.yaml`).

O YAML é lido e validado pelos consumidores (`compiler.py`, `audit.py`) via
`HarnessConfig.model_validate(raw)` — este módulo só define o schema.

Toda `description=` de `Field` abaixo é a fonte ÚNICA do comentário de uma
linha que `harness.templates.render_harness_yaml` grava ao lado de cada
chave no `.harness/harness.yaml` gerado (T-07, contrato
`skips-nunca-silenciosos`) — nunca uma segunda lista mantida à parte que
poderia divergir deste schema (mesmo padrão da decisão D-006: importar a
lista, não comparar duas listas). Todo campo novo aqui PRECISA de
`description`, ou a geração do YAML levanta erro em vez de gerar um arquivo
com uma chave muda.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ApprovalMode = Literal["paranoid", "balanced", "auto"]


class BudgetConfig(BaseModel):
    max_tokens_per_task: int = Field(
        500_000, description="Teto rígido de tokens por tarefa — estourou, aborta."
    )
    max_tokens_per_session: int = Field(
        2_000_000, description="Teto rígido de tokens pela sessão inteira."
    )
    max_tool_calls_per_task: int = Field(
        120, description="Backstop contra runaway loops: chamadas de ferramenta por tarefa."
    )
    max_green_iterations: int = Field(
        12, description="Tentativas de autocorreção permitidas na fase verde (GREEN) de uma tarefa."
    )


class GovernanceConfig(BaseModel):
    approval_policy: ApprovalMode = Field(
        "balanced",
        description=(
            "paranoid=aprova tudo, inclusive leituras; balanced=aprova o que muda "
            "estado (edit/execute/network); auto=auto-aprova edit/execute, só "
            "network e edit_test seguem gateados — use só com autonomia confiada."
        ),
    )
    budget: BudgetConfig = Field(default_factory=BudgetConfig)
    # Comandos permanentes que o dono do repo libera no boundary_guard além
    # do que já deriva de verify_cmd/lint/build/install/git local — mesma
    # semântica de PREFIXO de tokens que verify_cmd já tem.
    extra_allowed_commands: list[str] = Field(
        default_factory=list,
        description=(
            "Comandos permanentes deste repo, além do que já sai de "
            "verify_cmd/lint/build/install/git local. Casa por PREFIXO."
        ),
    )
    # Fluxo branch-first (finding C do dogfood 2026-07-22): compile-session
    # cria/muda para `contract/<slug>` antes de instalar o guard. Branch é
    # decisão da FERRAMENTA, não do agente — nenhum comando git de branch é
    # liberado no boundary_guard por causa disto.
    branch_per_contract: bool = Field(
        True,
        description=(
            "compile-session cria/muda para contract/<slug> antes de instalar o "
            "guard. Desligue se este repo não quer branch por contrato."
        ),
    )
    # Branches onde `git commit` direto é proibido (só via PR) — o
    # boundary_guard nega commit nelas incondicionalmente (postura de floor),
    # além da proteção server-side configurada no GitHub.
    protected_branches: list[str] = Field(
        default_factory=lambda: ["main", "homolog", "develop"],
        description="git commit direto é negado nestas branches incondicionalmente — só via PR.",
    )


class VerificationConfig(BaseModel):
    enforce_tdd: bool = Field(
        True, description="TDDGuard bloqueia atalhos de teste (Camada 2)."
    )
    test_command: str = Field(
        "pytest -x --tb=short", description="Comando de teste padrão deste repositório."
    )
    test_glob: str = Field(
        "tests/**/*.py", description="Glob dos arquivos que contam como teste (protegidos pelo TDDGuard)."
    )
    allowed_skips: list[str] = Field(
        default_factory=list,
        description=(
            "Skips LEGÍTIMOS deste repositório (plataforma, fixture externa) — "
            "cada entrada é um trecho do `reason` do skip, casado por substring. "
            "Sem isto, skip por falta de env var/credencial/ferramenta bloqueia "
            "harness verify já na primeira execução, com veredito INFRA."
        ),
    )


class HarnessConfig(BaseModel):
    governance: GovernanceConfig = Field(default_factory=GovernanceConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)
