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

    # passo 15 — visibilidade do que será commitado (deixou de ser gate em
    # `aviso-plugin-e-ciclo-automatico`; o que ele garante é legibilidade)
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


# ------------- T-06: commit e push automáticos, PR ainda humano -------------
#
# O ciclo tinha TRÊS paradas humanas (aprovar contrato, pedir implementação,
# aprovar commit) e passa a ter UMA. O gate do commit era instrucional — o
# `boundary_guard` só barra branch protegida —, então é este texto que
# governa o comportamento.

def test_the_cycle_no_longer_waits_for_a_human_before_committing() -> None:
    detail = render_lifecycle_detail()
    passo15 = detail[detail.index("15."):detail.index("16.")]
    passo16 = detail[detail.index("16."):detail.index("17.")]

    assert "NUNCA commita sem sinal verde" not in passo15
    assert "Só após aprovação" not in passo16
    for texto in (passo15, passo16):
        assert "pedir aprovação" not in texto


def test_the_diff_stays_visible_even_without_a_gate() -> None:
    """O passo 15 deixa de BARRAR, mas não deixa de MOSTRAR: a legibilidade
    conquistada na issue #12 (T-ID + JSON cru foi reprovado) é independente
    do gate e continua exigida."""
    detail = render_lifecycle_detail()
    passo15 = detail[detail.index("15."):detail.index("16.")]

    assert "descrição funcional" in passo15
    assert "file:line" in passo15


def test_committing_requires_the_proof_that_replaced_the_human_gate() -> None:
    """As pré-condições são o que substitui a aprovação humana. Sem elas
    escritas, "commit automático" viraria "commit de trabalho não verificado"."""
    detail = render_lifecycle_detail()
    passo16 = detail[detail.index("16."):detail.index("17.")]

    assert "harness finish" in passo16
    assert "blockers" in passo16
    assert "verify_cmd" in passo16


def test_the_push_is_automatic_but_only_on_the_contract_branch() -> None:
    detail = render_lifecycle_detail()
    passo16 = detail[detail.index("16."):detail.index("17.")]

    assert "push" in passo16
    assert "contract/" in passo16


def test_opening_the_pull_request_is_never_the_agents_job() -> None:
    """Fronteira dura do contrato `aviso-plugin-e-ciclo-automatico`: expor o
    trabalho para revisão e merge é decisão humana, por qualquer caminho."""
    detail = render_lifecycle_detail()
    block = render_lifecycle_block()

    assert "harness pr-draft" in detail
    assert "NUNCA abre" in detail or "nunca abre" in detail
    assert "pr-draft" in block
