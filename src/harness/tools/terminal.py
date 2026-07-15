"""Camada 1 — TerminalTool: execução de comandos com recuperação dinâmica de erros.

Regra inegociável: comandos SEMPRE rodam dentro do SandboxEnvironment. Não
existe caminho de execução no host. Em falha, o resultado estruturado
(stderr + hints) volta ao contexto do modelo, que ajusta a estratégia —
o loop de autocorreção é propriedade do harness, não boa vontade do modelo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harness.governance.sandbox import SandboxEnvironment

# Padrões de erro conhecidos -> dica de recuperação injetada no contexto.
# Extensível via config; mantém o modelo fora de becos comuns.
_RECOVERY_PATTERNS: list[tuple[str, str]] = [
    ("ModuleNotFoundError", "Dependência ausente no sandbox. Instale via gerenciador do projeto (ex: 'pip install -e .' ou 'npm ci') antes de reexecutar."),
    ("command not found", "Binário inexistente na imagem do sandbox. Verifique o nome ou use alternativa disponível; NÃO tente instalar via rede (sandbox sem rede)."),
    ("Permission denied", "Sem permissão no sandbox. Opere apenas dentro do workspace montado."),
    ("SyntaxError", "Erro de sintaxe no código gerado. Releia o arquivo citado no traceback antes de editar de novo."),
    ("Connection refused", "Sandbox não tem acesso à rede (network_mode=none). Remova a dependência de rede do passo ou solicite aprovação HITL para habilitar rede."),
    ("No such file or directory", "Caminho inexistente. Liste o diretório antes de assumir estrutura."),
]


@dataclass
class CommandResult:
    """Resultado estruturado — é isto que entra no contexto do modelo."""

    command: str
    exit_code: int
    stdout: str
    stderr: str
    duration_s: float
    recovery_hints: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    def to_model_payload(self) -> dict:
        payload = {
            "command": self.command,
            "exit_code": self.exit_code,
            "stdout": self.stdout[-8000:],   # cauda: fim do output carrega o erro
            "stderr": self.stderr[-8000:],
        }
        if not self.ok and self.recovery_hints:
            payload["recovery_hints"] = self.recovery_hints
        return payload


class TerminalTool:
    """Ferramenta de terminal acoplada a um sandbox específico."""

    name = "run_terminal"
    description = (
        "Executa um comando de shell dentro do sandbox isolado (sem rede). "
        "Retorna exit_code, stdout, stderr e, em falha, dicas de recuperação. "
        "Leia stderr e ajuste a estratégia antes de repetir um comando que falhou."
    )
    input_schema = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Comando de shell a executar."},
            "timeout_s": {"type": "integer", "default": 120, "maximum": 600},
        },
        "required": ["command"],
    }
    risk_class = "execute"

    def __init__(self, sandbox: "SandboxEnvironment") -> None:
        self._sandbox = sandbox

    async def __call__(self, command: str, timeout_s: int = 120) -> dict:
        result = await self._sandbox.exec(command, timeout_s=timeout_s)
        if not result.ok:
            result.recovery_hints = self._hints_for(result.stderr + result.stdout)
        return result.to_model_payload()

    @staticmethod
    def _hints_for(output: str) -> list[str]:
        return [hint for pattern, hint in _RECOVERY_PATTERNS if pattern in output]
