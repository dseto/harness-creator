"""Utilitários puros de pattern-matching (glob -> regex), sem dependências
frozen. Extraído de `verification/tdd_loop.py` para que o modo compilador
(compiler/audit/analyzer/review) não precise carregar o loop TDD (que
importa `docker` via `SandboxEnvironment`/`CommandResult`) só para reusar
esta função."""

from __future__ import annotations

import re


def _glob_to_regex(glob: str) -> re.Pattern[str]:
    """Traduz um glob de path (com `**` cross-segmento e `*` intra-segmento)
    para regex. Independente de versão do Python (não depende de
    `PurePath.full_match`, que é 3.13+). `**/` casa zero ou mais diretórios."""
    escaped = re.escape(glob.replace("\\", "/"))
    escaped = escaped.replace(r"\*\*/", "(?:.*/)?")  # **/ -> diretórios opcionais
    escaped = escaped.replace(r"\*\*", ".*")          # ** -> qualquer coisa
    escaped = escaped.replace(r"\*", "[^/]*")         # * -> dentro de um segmento
    escaped = escaped.replace(r"\?", "[^/]")
    return re.compile("^" + escaped + "$")
