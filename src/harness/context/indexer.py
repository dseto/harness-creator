"""Camada 3 — CodeIndexer: índice leve do repositório.

v0: mapa de arquivos + extração ingênua de símbolos de topo (def/class/
function/export). Interface estável para evoluir a tree-sitter/embeddings sem
tocar o ContextManager.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SYMBOL_RE = re.compile(
    r"^(?:def|class|async def)\s+(\w+)"          # Python
    r"|^(?:export\s+)?(?:function|class|const|interface|type)\s+(\w+)",  # TS/JS
    re.MULTILINE,
)


@dataclass
class IndexedFile:
    path: str
    symbols: list[str]
    lines: int


class CodeIndexer:
    def __init__(self, root: Path, include: list[str], exclude: list[str]) -> None:
        self._root = root
        self._include = include or ["**/*.py"]
        self._exclude = exclude or []
        self._files: list[IndexedFile] = []

    def build(self) -> None:
        self._files = []
        seen: set[Path] = set()
        for pattern in self._include:
            for path in self._root.glob(pattern):
                if not path.is_file() or path in seen or self._is_excluded(path):
                    continue
                seen.add(path)
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                symbols = [a or b for a, b in _SYMBOL_RE.findall(text)]
                self._files.append(
                    IndexedFile(
                        path=str(path.relative_to(self._root)),
                        symbols=symbols[:40],
                        lines=text.count("\n") + 1,
                    )
                )

    def _is_excluded(self, path: Path) -> bool:
        rel = str(path.relative_to(self._root)).replace("\\", "/")
        return any(Path(rel).match(pat) or pat.strip("*/") in rel for pat in self._exclude)

    def summary(self, max_files: int = 200) -> str:
        """Mapa compacto do repo para o system prompt."""
        if not self._files:
            self.build()
        lines = [
            f"{f.path} ({f.lines}L): {', '.join(f.symbols) or '—'}"
            for f in sorted(self._files, key=lambda f: f.path)[:max_files]
        ]
        omitted = len(self._files) - max_files
        if omitted > 0:
            lines.append(f"... +{omitted} arquivos omitidos")
        return "\n".join(lines) or "(repositório vazio)"

    def search(self, query: str, limit: int = 20) -> list[IndexedFile]:
        """Busca simples por nome de arquivo/símbolo. Substituível por
        busca semântica (embeddings) mantendo a assinatura."""
        if not self._files:
            self.build()
        q = query.lower()
        hits = [
            f for f in self._files
            if q in f.path.lower() or any(q in s.lower() for s in f.symbols)
        ]
        return hits[:limit]
