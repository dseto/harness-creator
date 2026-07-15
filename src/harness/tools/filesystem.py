"""Camada 1 — ferramentas discretas de arquivo: read_file / write_file.

Existem à parte de `run_terminal` para que `risk_class` reflita o poder
real da ação: ler é "read" (nunca gateado), escrever é "edit" (gateado em
paranoid/balanced). `run_terminal` continua existindo para o resto, mas o
guia de governança (AGENTS.md) recomenda estas duas para I/O simples.

Decisão de altitude (fronteira de contenção): diferente de `run_terminal`,
estas ferramentas operam no filesystem do HOST (repo_root), não dentro do
contêiner. É intencional e equivalente em efeito: o sandbox monta o
workspace como bind-mount `rw`, então uma escrita container-side no
workspace já apareceria no host. A contenção de `write_file` é, por
projeto, `_resolve_within_workspace` — que segue symlinks via `.resolve()`
e recusa qualquer alvo fora do repo_root. As demais garantias do sandbox
(sem rede, limites de processo) são sobre EXECUÇÃO de código, não sobre
I/O inerte de arquivo, e não se aplicam aqui.
"""

from __future__ import annotations

from pathlib import Path

from harness.tools.registry import ToolExecutionError


def _resolve_within_workspace(workspace: Path, path: str) -> Path:
    """Resolve `path` relativo a `workspace`; recusa qualquer escape do repo.

    `.resolve()` segue symlinks ANTES da checagem `relative_to`, então um
    symlink dentro do workspace apontando para fora resolve para o alvo real
    e é recusado — não dá para escapar via link. `workspace` já vem
    resolvido (ver __init__ das tools), garantindo comparação consistente."""
    candidate = (workspace / path).resolve()
    try:
        candidate.relative_to(workspace)
    except ValueError:
        raise ToolExecutionError(
            f"Caminho '{path}' escapa do workspace — operação recusada.",
            payload={"path": path},
        )
    return candidate


class FileReadTool:
    name = "read_file"
    description = "Lê o conteúdo de um arquivo dentro do workspace."
    input_schema = {
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Caminho relativo ao workspace."}},
        "required": ["path"],
    }
    risk_class = "read"

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.resolve()

    async def __call__(self, path: str) -> dict:
        target = _resolve_within_workspace(self._workspace, path)
        if not target.is_file():
            raise ToolExecutionError(f"Arquivo não encontrado: '{path}'.", payload={"path": path})
        return {"path": path, "content": target.read_text(encoding="utf-8", errors="replace")}


class FileWriteTool:
    name = "write_file"
    description = "Escreve (cria ou sobrescreve) um arquivo dentro do workspace."
    input_schema = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Caminho relativo ao workspace."},
            "content": {"type": "string", "description": "Conteúdo completo do arquivo."},
        },
        "required": ["path", "content"],
    }
    risk_class = "edit"

    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace.resolve()

    async def __call__(self, path: str, content: str) -> dict:
        target = _resolve_within_workspace(self._workspace, path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {"path": path, "bytes_written": len(content.encode("utf-8"))}
