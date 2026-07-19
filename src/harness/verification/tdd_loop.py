"""Camada 2 — TDDCycle: máquina de estados Red-Green-Refactor obrigatória.

O harness (não o modelo) é dono das transições:

  RED      -> agente escreve teste; harness EXIGE que ele falhe.
  GREEN    -> agente implementa; harness roda a suíte no sandbox e devolve
              stack traces até passar (ou estourar max_green_iterations).
  REFACTOR -> melhorias com suíte verde como invariante.

Guardrail anti-regressão estrutural: arquivos de teste são hashados ao entrar
em GREEN. Edição de teste durante GREEN = violação -> transição bloqueada.
Impede o clássico "fiz o teste passar apagando a asserção".
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from harness.governance.sandbox import SandboxEnvironment
from harness.patterns import _glob_to_regex
from harness.tools.terminal import CommandResult


class TDDPhase(str, Enum):
    RED = "red"
    GREEN = "green"
    REFACTOR = "refactor"
    DONE = "done"


class TDDViolation(RuntimeError):
    """Transição ilegal ou adulteração de testes."""


@dataclass
class TDDCycle:
    sandbox: SandboxEnvironment
    workspace: Path
    test_command: str                       # ex: "pytest -x --tb=short"
    test_glob: str = "tests/**/*.py"
    max_green_iterations: int = 12
    phase: TDDPhase = TDDPhase.RED
    green_iterations: int = 0
    _test_hashes: dict[str, str] = field(default_factory=dict)

    # ---------- RED ----------

    async def assert_red(self) -> CommandResult:
        """Valida a fase RED: a suíte DEVE falhar (teste novo é significativo).

        Suíte que já passa = teste tautológico/vazio -> violação."""
        self._require_phase(TDDPhase.RED)
        result = await self.sandbox.exec(self.test_command)
        if result.ok:
            raise TDDViolation(
                "Fase RED inválida: a suíte passou. O teste novo não exercita "
                "comportamento inexistente — reescreva o teste antes de implementar."
            )
        # Congela os testes: baseline anti-adulteração para a fase GREEN.
        self._test_hashes = self._hash_tests()
        self.phase = TDDPhase.GREEN
        self.green_iterations = 0
        return result

    # ---------- GREEN ----------

    async def try_green(self) -> CommandResult:
        """Uma iteração da fase GREEN. Retorna o resultado da suíte; o
        orquestrador injeta stdout/stderr (stack traces) de volta no modelo
        enquanto result.ok for False."""
        self._require_phase(TDDPhase.GREEN)
        self._assert_tests_untouched()

        self.green_iterations += 1
        if self.green_iterations > self.max_green_iterations:
            raise TDDViolation(
                f"GREEN excedeu {self.max_green_iterations} iterações sem passar. "
                "Abortando — candidato a EET/replanejamento humano."
            )

        result = await self.sandbox.exec(self.test_command)
        if result.ok:
            self.phase = TDDPhase.REFACTOR
        return result

    # ---------- REFACTOR ----------

    async def assert_still_green(self) -> CommandResult:
        """Após cada refactor, a suíte precisa continuar verde."""
        self._require_phase(TDDPhase.REFACTOR)
        self._assert_tests_untouched()
        result = await self.sandbox.exec(self.test_command)
        if not result.ok:
            # Refactor quebrou a suíte: volta para GREEN para corrigir.
            self.phase = TDDPhase.GREEN
        return result

    def finish(self) -> None:
        self._require_phase(TDDPhase.REFACTOR)
        self.phase = TDDPhase.DONE

    def allow_test_edit(self) -> None:
        """Escape hatch EXPLÍCITO (requer aprovação HITL a montante): re-hasha
        os testes após uma edição legítima aprovada por humano."""
        self._test_hashes = self._hash_tests()

    def is_test_path(self, path: str) -> bool:
        """True se `path` casar com `test_glob` — usado pelo TDDGuard para
        decidir se uma escrita precisa de proteção.

        RESOLVE o path relativo ao workspace antes de casar (fecha o bypass
        de `src/../tests/test_x.py` e de paths absolutos que apontam para
        dentro de `tests/` mas não começam textualmente com `tests/`), e usa
        o glob COMPLETO (mesma noção de `_hash_tests`), não prefixo/sufixo —
        `**/test_*.py` não pode mais marcar todo `.py` como teste. Casa por
        padrão, não por existência em disco: protege também a CRIAÇÃO de um
        teste novo durante GREEN/REFACTOR."""
        try:
            resolved = (self.workspace / path).resolve()
            rel = resolved.relative_to(self.workspace)
        except ValueError:
            return False  # fora do workspace — write_file já bloqueia traversal
        return bool(_glob_to_regex(self.test_glob).match(rel.as_posix()))

    # ---------- internos ----------

    def _require_phase(self, expected: TDDPhase) -> None:
        if self.phase != expected:
            raise TDDViolation(
                f"Transição ilegal: operação de {expected.value} chamada em fase {self.phase.value}."
            )

    def _hash_tests(self) -> dict[str, str]:
        return {
            str(p.relative_to(self.workspace)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(self.workspace.glob(self.test_glob))
            if p.is_file()
        }

    def _assert_tests_untouched(self) -> None:
        current = self._hash_tests()
        if current != self._test_hashes:
            changed = sorted(
                set(current) ^ set(self._test_hashes)
                | {k for k in current.keys() & self._test_hashes.keys()
                   if current[k] != self._test_hashes[k]}
            )
            raise TDDViolation(
                "Testes modificados durante GREEN/REFACTOR sem aprovação: "
                f"{changed}. Reverta ou solicite aprovação humana (allow_test_edit)."
            )
