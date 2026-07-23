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


# ---------------- render_lifecycle_block ----------------

def test_block_contains_all_17_numbered_steps() -> None:
    block = render_lifecycle_block()
    for n in range(1, 18):
        assert f"{n}. " in block, f"passo {n} ausente do bloco"


def test_block_contains_key_milestones() -> None:
    block = render_lifecycle_block()
    assert "1. Ler `AGENTS.md`" in block
    assert "scolher exatamente UMA feature" in block
    assert "verify_cmd" in block
    assert "aprovação humana" in block.lower()  # passo 15: gate antes do commit
    assert "limpa" in block.lower()  # passo 17: deixar caminho/working tree limpo


def test_block_points_to_detail_file() -> None:
    block = render_lifecycle_block()
    assert ".harness/LIFECYCLE.md" in block


def test_block_uses_own_delimiters_distinct_from_compiler() -> None:
    block = render_lifecycle_block()
    assert LIFECYCLE_BEGIN in block and LIFECYCLE_END in block
    assert LIFECYCLE_BEGIN != AGENTS_BEGIN
    assert LIFECYCLE_END != AGENTS_END
    assert AGENTS_BEGIN not in block
    assert AGENTS_END not in block


def test_render_lifecycle_detail_covers_all_steps() -> None:
    detail = render_lifecycle_detail()
    for n in range(1, 18):
        assert f"{n}. **" in detail, f"detalhe do passo {n} ausente"


def test_render_lifecycle_detail_step_15_requires_human_approval_before_commit() -> None:
    detail = render_lifecycle_detail()
    assert "aprovação humana" in detail
    assert "NUNCA commita sem sinal verde" in detail


def test_render_lifecycle_detail_step_15_requires_functional_description_and_file_line_link() -> None:
    """Issue #12 (dogfood 2026-07-23): mostrar só T-ID + JSON cru do
    verify_cmd foi classificado como "péssimo, não dá pra entender" — o
    passo 15 precisa exigir, por escrito, descrição funcional + link
    file:line, não deixar implícito em "mensagem clara"."""
    detail = render_lifecycle_detail()
    assert "não é suficiente" in detail
    assert "descrição funcional" in detail
    assert "file:line" in detail


def test_render_lifecycle_block_step_15_mentions_functional_description_and_file_line() -> None:
    block = render_lifecycle_block()
    assert "descrição funcional" in block
    assert "file:line" in block


def test_render_lifecycle_detail_step_10_cites_stop_conditions_source() -> None:
    detail = render_lifecycle_detail()
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
