"""Onda 4 ("prompts e docs") -- dedup de prosa repetida entre skills e docs.

Cada teste trava uma duplicacao medida no
docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md (itens 7, 8, 14):
nao e teste de comportamento de codigo, e teste de conteudo de
prompt/documentacao (mesmo padrao de tests/test_docs_enforcement_claims.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

_PYTHONPATH_SKILL_FILES = (
    "skills/plan/SKILL.md",
    "skills/preflight/SKILL.md",
    "skills/init/SKILL.md",
    "skills/audit/SKILL.md",
    "skills/team/SKILL.md",
)

_JUSTIFICATIVA_MARKER = "aprovação sem necessidade"


@pytest.mark.parametrize("rel_path", _PYTHONPATH_SKILL_FILES)
def test_pythonpath_justificativa_nao_duplicada_por_skill(rel_path: str) -> None:
    text = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
    assert _JUSTIFICATIVA_MARKER not in text, (
        f"{rel_path} ainda repete a justificativa completa do PYTHONPATH -- "
        "deveria virar 1 linha apontando pro GUIDE.md (item 7)"
    )
    assert "PYTHONPATH" in text and "ModuleNotFoundError" in text, (
        f"{rel_path} perdeu a dica curta de PYTHONPATH -- so a justificativa "
        "longa deveria sair, nao a instrucao em si"
    )


def test_pythonpath_justificativa_vive_uma_vez_no_guide() -> None:
    text = (REPO_ROOT / "docs/plugin/GUIDE.md").read_text(encoding="utf-8")
    assert text.count(_JUSTIFICATIVA_MARKER) == 1, (
        "GUIDE.md deveria ser a fonte unica (SSOT) da justificativa do "
        "PYTHONPATH (item 7)"
    )


def test_assess_model_routing_delega_coleta_a_haiku_e_julgamento_ao_forte() -> None:
    text = (REPO_ROOT / "skills/assess/SKILL.md").read_text(encoding="utf-8")
    lower = text.lower()
    assert "haiku" in lower, "assess/SKILL.md nao menciona roteamento pra Haiku (item 8)"
    assert "modelo forte" in lower, (
        "falta deixar explicito que o julgamento (Passo 3/4) continua no "
        "modelo forte, nao em Haiku"
    )

    como_executar_idx = lower.index("## como executar")
    passo1_idx = lower.index("## passo 1")
    delegacao = lower[como_executar_idx:passo1_idx]
    assert "haiku" in delegacao, (
        "a secao de delegacao (## Como executar) deveria explicar o "
        "roteamento pra Haiku -- e onde o humano confere a decisao"
    )

    passo3_idx = lower.index("## passo 3")
    passo4_end_idx = lower.find("## passo 5")
    julgamento = lower[passo3_idx : passo4_end_idx if passo4_end_idx != -1 else None]
    assert "haiku" not in julgamento, (
        "Passo 3/4 (julgamento) nao pode instruir rodar em Haiku -- "
        "desfaz o motivo de independencia/qualidade do item 8"
    )


_KILLSWITCH_ANEDOTA_PATTERN = re.compile(r"quatro[\s>]*dias")
_KILLSWITCH_DOCS = (
    "docs/plugin/GUIDE.md",
    "docs/plugin/TUTORIAL.md",
    "docs/plugin/ARCHITECTURE.md",
)


def test_killswitch_anedota_contada_uma_unica_vez() -> None:
    hits = [
        rel
        for rel in _KILLSWITCH_DOCS
        if _KILLSWITCH_ANEDOTA_PATTERN.search(
            (REPO_ROOT / rel).read_text(encoding="utf-8")
        )
    ]
    assert hits == ["docs/plugin/GUIDE.md"], (
        f"anedota do kill-switch ('quatro dias') duplicada "
        f"em: {hits} -- so GUIDE.md deveria conte-la (item 14)"
    )


def test_killswitch_tutorial_e_architecture_apontam_pro_guide() -> None:
    for rel in ("docs/plugin/TUTORIAL.md", "docs/plugin/ARCHITECTURE.md"):
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "GUIDE.md" in text, (
            f"{rel} deveria apontar pro GUIDE.md pro aviso completo do "
            "kill-switch (item 14)"
        )
        assert "harness disable" in text and "harness enable" in text, (
            f"{rel} nao pode perder os comandos harness disable/enable "
            "so porque a anedota saiu"
        )
