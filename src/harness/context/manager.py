"""Camada 3 — ContextManager: contexto arquitetural + memória persistente.

Combate a "amnésia do agente" em três frentes:
  1. Diretrizes de governança (AGENTS.md / CLAUDE.md) injetadas em TODA sessão.
  2. Índice do código-fonte (CodeIndexer) para grounding estrutural.
  3. Memória de sessão persistida em .harness/memory/ (fatos e decisões
     sobrevivem entre sessões).
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from harness.config import ContextConfig
from harness.context.indexer import CodeIndexer


@dataclass
class MemoryEntry:
    timestamp: float
    kind: str          # "fact" | "decision" | "task_state"
    content: str

    def to_json(self) -> dict:
        return {"timestamp": self.timestamp, "kind": self.kind, "content": self.content}


class ContextManager:
    def __init__(self, config: ContextConfig, repo_root: Path) -> None:
        self._cfg = config
        self._root = repo_root.resolve()
        self._memory_dir = self._root / config.memory_dir
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        self._memory_file = self._memory_dir / "session_memory.jsonl"
        self.indexer = CodeIndexer(
            root=self._root,
            include=config.index.get("include", []),
            exclude=config.index.get("exclude", []),
        )

    # ---------- governança ----------

    def load_governance(self) -> str:
        """Lê AGENTS.md/CLAUDE.md da raiz. Contexto imutável de toda sessão."""
        sections: list[str] = []
        for name in self._cfg.governance_files:
            path = self._root / name
            if path.is_file():
                sections.append(f"<governance file=\"{name}\">\n{path.read_text(encoding='utf-8')}\n</governance>")
        if not sections:
            sections.append(
                "<governance missing=\"true\">Nenhum AGENTS.md/CLAUDE.md encontrado. "
                "Opere conservadoramente e proponha criar um AGENTS.md.</governance>"
            )
        return "\n\n".join(sections)

    # ---------- memória persistente ----------

    def remember(self, kind: str, content: str) -> None:
        entry = MemoryEntry(timestamp=time.time(), kind=kind, content=content)
        with self._memory_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.to_json(), ensure_ascii=False) + "\n")

    def recall(self, limit: int = 50) -> list[MemoryEntry]:
        if not self._memory_file.is_file():
            return []
        lines = self._memory_file.read_text(encoding="utf-8").splitlines()[-limit:]
        return [MemoryEntry(**json.loads(line)) for line in lines if line.strip()]

    # ---------- montagem do system prompt ----------

    def build_system_prompt(self, task_description: str) -> str:
        """Contexto completo por sessão: governança + mapa do repo + memória."""
        memories = self.recall()
        memory_block = (
            "\n".join(f"- [{m.kind}] {m.content}" for m in memories)
            if memories
            else "(sem memórias de sessões anteriores)"
        )
        return "\n\n".join(
            [
                "Você é um agente de engenharia de software operando dentro de um "
                "harness com TDD obrigatório, sandbox sem rede e aprovação HITL. "
                "Siga estritamente as diretrizes de governança abaixo.",
                self.load_governance(),
                f"<repository_map>\n{self.indexer.summary()}\n</repository_map>",
                f"<persistent_memory>\n{memory_block}\n</persistent_memory>",
                f"<task>\n{task_description}\n</task>",
            ]
        )
