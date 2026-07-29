"""Testes do Agent Session Lifecycle (17 passos, ROADMAP.md Fase 2) compilado
como bloco gerenciado adicional no AGENTS.md, com detalhe em
.harness/LIFECYCLE.md (progressive disclosure)."""

from __future__ import annotations

from pathlib import Path

from harness.compiler import AGENTS_BEGIN, AGENTS_END
from harness.lifecycle import (
    LIFECYCLE_BEGIN,
    LIFECYCLE_END,
    install_lifecycle,
    render_lifecycle_block,
    render_lifecycle_detail,
)


# ---------------- render_lifecycle_block / render_lifecycle_detail ----------------

def test_the_lifecycle_block_carries_the_17_steps_and_its_own_delimiters() -> None:
    """O bloco é resumo com progressive disclosure: os 17 passos numerados e o
    ponteiro para o detalhe. Os delimitadores são PRÓPRIOS — se colidissem com
    os do compiler, um bloco sobrescreveria o outro no mesmo AGENTS.md.

    O passo 15 exige, por escrito, descrição funcional + link `file:line`:
    issue #12 (dogfood 2026-07-23), em que mostrar só T-ID + JSON cru do
    `verify_cmd` foi classificado como "péssimo, não dá pra entender". Deixar
    isso implícito em "mensagem clara" não bastou."""
    block = render_lifecycle_block()

    for n in range(1, 18):
        assert f"{n}. " in block, f"passo {n} ausente do bloco"

    assert "1. Ler `AGENTS.md`" in block
    assert "scolher exatamente UMA feature" in block
    assert "verify_cmd" in block
    assert "aprovação humana" in block.lower()  # passo 15: gate antes do commit
    assert "limpa" in block.lower()  # passo 17: deixar caminho/working tree limpo
    assert ".harness/LIFECYCLE.md" in block
    assert "descrição funcional" in block
    assert "file:line" in block

    assert LIFECYCLE_BEGIN in block and LIFECYCLE_END in block
    assert LIFECYCLE_BEGIN != AGENTS_BEGIN
    assert LIFECYCLE_END != AGENTS_END
    assert AGENTS_BEGIN not in block
    assert AGENTS_END not in block


def test_the_lifecycle_detail_covers_every_step_and_names_its_sources() -> None:
    detail = render_lifecycle_detail()

    for n in range(1, 18):
        assert f"{n}. **" in detail, f"detalhe do passo {n} ausente"

    # passo 15 — gate humano antes do commit
    assert "aprovação humana" in detail
    assert "NUNCA commita sem sinal verde" in detail
    assert "não é suficiente" in detail
    assert "descrição funcional" in detail
    assert "file:line" in detail

    # passo 10 — de onde saem as stop conditions
    assert "stop_conditions" in detail
    assert "spec.md" in detail
    assert "harness.contract.get_stop_conditions" in detail


# ---------------- install_lifecycle ----------------

def test_install_creates_agents_md_when_missing(tmp_path: Path) -> None:
    agents_path, detail_path = install_lifecycle(tmp_path)

    assert agents_path == tmp_path / "AGENTS.md"
    assert agents_path.is_file()
    text = agents_path.read_text(encoding="utf-8")
    assert LIFECYCLE_BEGIN in text and LIFECYCLE_END in text

    assert detail_path == tmp_path / ".harness" / "LIFECYCLE.md"
    assert detail_path.is_file()
    assert "Agent Session Lifecycle" in detail_path.read_text(encoding="utf-8")


def test_install_preserves_manual_text_in_existing_agents_md(tmp_path: Path) -> None:
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        "# Meu projeto\n\nRegra manual minha, não mexer.\n", encoding="utf-8"
    )

    install_lifecycle(tmp_path)

    text = agents_path.read_text(encoding="utf-8")
    assert "Regra manual minha, não mexer." in text
    assert LIFECYCLE_BEGIN in text and LIFECYCLE_END in text


def test_install_is_idempotent_no_duplicate_block(tmp_path: Path) -> None:
    install_lifecycle(tmp_path)
    install_lifecycle(tmp_path)

    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert text.count(LIFECYCLE_BEGIN) == 1
    assert text.count(LIFECYCLE_END) == 1


def test_install_preserves_compiler_block_intact(tmp_path: Path) -> None:
    agents_path = tmp_path / "AGENTS.md"
    agents_path.write_text(
        f"# Projeto\n\n{AGENTS_BEGIN}\nconteudo do compiler.py intacto\n{AGENTS_END}\n",
        encoding="utf-8",
    )

    install_lifecycle(tmp_path)
    install_lifecycle(tmp_path)  # segunda rodada: idempotência não deve tocar o outro bloco

    text = agents_path.read_text(encoding="utf-8")
    assert f"{AGENTS_BEGIN}\nconteudo do compiler.py intacto\n{AGENTS_END}" in text
    assert text.count(AGENTS_BEGIN) == 1
    assert text.count(LIFECYCLE_BEGIN) == 1


def test_install_writes_detail_file_with_full_content(tmp_path: Path) -> None:
    _, detail_path = install_lifecycle(tmp_path)
    detail = detail_path.read_text(encoding="utf-8")
    assert detail == render_lifecycle_detail()
