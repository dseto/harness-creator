"""Camada 2 — TDDGuard: fecha o guardrail "TDD obrigatório" de verdade.

Sem isto, o agente pode ignorar as ferramentas `tdd_*` e editar um arquivo
de teste + rodar a suíte direto via uma ferramenta de execução, contornando
o hash anti-adulteração do `TDDCycle` (que só é checado dentro das próprias
ferramentas TDD). O `TDDGuard` intercepta TODO dispatch de ferramenta antes
do gate HITL e bloqueia esses dois atalhos.

Decisão de altitude: o guard chaveia por **`risk_class`**, não por nome de
ferramenta. Qualquer ferramenta `execute` (incluindo tools MCP de shell
registradas dinamicamente) que invoque o test runner é barrada; qualquer
ferramenta `edit` que grave num arquivo de teste protegido é barrada. Isso
evita o buraco de só vigiar `run_terminal`/`write_file` por nome.

Ordem de chamada em `AgentOrchestrator._execute_tool`:
    check_pre_dispatch()  -- ANTES do ApprovalPolicy.gate()
    ... dispatch real ...
    note_post_dispatch()  -- DEPOIS do dispatch bem-sucedido

O re-hash de uma edição de teste aprovada (`tdd_request_test_edit`) só
acontece em `note_post_dispatch`, depois da escrita já ter ocorrido —
re-hashear no momento da aprovação capturaria o conteúdo ANTIGO do
arquivo, o que não protegeria nada contra o que acabou de ser escrito.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from harness.verification.tdd_loop import TDDCycle, TDDPhase

# Divide um comando de shell em tokens tratando metacaracteres como
# separadores — para que `pytest&&true`, `(pytest)`, `pytest;`, `pytest>log`
# não escapem da detecção do runner (o bug de tokenizar só por espaço).
_SHELL_SPLIT = re.compile(r"[\s;&|()<>`$\"']+")


@dataclass
class TDDGuard:
    cycle: TDDCycle
    test_command: str
    enabled: bool = True
    _test_edit_token: bool = field(default=False, init=False)

    def grant_test_edit_token(self) -> None:
        """Chamado pelo handler de `tdd_request_test_edit`, já depois do gate
        HITL de `risk_class="edit_test"` ter aprovado o pedido."""
        self._test_edit_token = True

    def check_pre_dispatch(
        self, risk_class: str, arguments: dict[str, Any]
    ) -> str | None:
        """Retorna o motivo do bloqueio (string) ou `None` se a chamada pode
        prosseguir para o gate HITL normal. Chaveado por `risk_class`."""
        if not self.enabled:
            return None

        # 1. Rodar a suíte de teste via QUALQUER ferramenta de execução, fora
        #    da máquina de estados TDD.
        if risk_class == "execute" and self._invokes_test_runner(arguments):
            return (
                "Suíte de teste só pode rodar através da máquina de estados TDD. "
                "Use 'tdd_try_green' (fase GREEN) ou 'tdd_assert_still_green' "
                "(fase REFACTOR) em vez de rodar o test runner diretamente."
            )

        # 2. Editar um arquivo de teste protegido via QUALQUER ferramenta de
        #    edição, durante GREEN/REFACTOR, sem token concedido.
        if risk_class == "edit" and self.cycle.phase in {TDDPhase.GREEN, TDDPhase.REFACTOR}:
            path = self._extract_path(arguments)
            if path and self.cycle.is_test_path(path):
                if self._test_edit_token:
                    return None
                return (
                    f"Edição de '{path}' bloqueada: arquivo de teste protegido "
                    f"durante a fase {self.cycle.phase.value}. Chame "
                    "'tdd_request_test_edit' e obtenha aprovação humana antes de editar."
                )

        return None

    def note_post_dispatch(
        self, risk_class: str, arguments: dict[str, Any], ok: bool
    ) -> None:
        """Chamado DEPOIS de um dispatch bem-sucedido. Consome o token de
        edição de teste e re-hasheia o conteúdo JÁ GRAVADO — mas SÓ quando a
        escrita foi de fato num arquivo de teste (senão um write de arquivo
        de implementação consumiria o token e re-baselinaria testes por
        engano)."""
        if not (ok and self._test_edit_token and risk_class == "edit"):
            return
        path = self._extract_path(arguments)
        if path and self.cycle.is_test_path(path):
            self.cycle.allow_test_edit()
            self._test_edit_token = False

    def _invokes_test_runner(self, arguments: dict[str, Any]) -> bool:
        runner = self.test_command.split()[0] if self.test_command else ""
        if not runner:
            return False
        # Junta todos os valores string dos argumentos (a ferramenta pode
        # nomear o comando de formas diferentes: "command", "cmd", etc.).
        blob = " ".join(str(v) for v in arguments.values() if isinstance(v, str))
        if self.test_command and self.test_command in blob:
            return True
        tokens = _SHELL_SPLIT.split(blob)
        return runner in tokens

    @staticmethod
    def _extract_path(arguments: dict[str, Any]) -> str | None:
        value = arguments.get("path")
        return value if isinstance(value, str) else None
