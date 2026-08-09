"""Testes de `harness.spine` — os dois registros da spine cuja vida é o PROJETO
(§5.2 e §5.3 do design de loop engineering).

`progress.md` responde "onde estamos" e morre com a demanda. Estes dois
respondem "por que decidimos assim" e "o que atrapalhou", e sobrevivem a ela. A
diferença de ciclo de vida é o que torna a garantia daqui diferente: `progress.md`
é REESCRITO a cada demanda; estes são APPEND-ONLY, e é isso que estes testes
travam. Um registro de razões que pode ser reescrito não prova que a razão
gravada é a razão original — e essa prova é a única coisa que ele tem a oferecer.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.spine import (
    DECISIONS_FILE,
    LESSONS_FILE,
    open_lessons,
    read_decisions,
    read_lessons,
    record_decision,
    record_lesson,
    render_decisions_section,
)


# ---------------------------------------------------------------------------
# REGRA: registrar uma decisão numera, data e NUNCA altera o que já está lá.
# ---------------------------------------------------------------------------

def test_the_first_decision_of_a_project_starts_the_numbering(tmp_path: Path) -> None:
    decision_id = record_decision(
        tmp_path, "Guardar razão em arquivo", decision="Arquivo markdown", why="ADR é caro demais",
        today="2026-08-09",
    )

    assert decision_id == "D-001"
    content = (tmp_path / DECISIONS_FILE).read_text(encoding="utf-8")
    assert "## D-001 — Guardar razão em arquivo (2026-08-09)" in content
    assert "Decisão: Arquivo markdown" in content
    assert "Porquê: ADR é caro demais" in content


def test_numbering_continues_from_what_is_already_recorded(tmp_path: Path) -> None:
    for n in range(3):
        record_decision(tmp_path, f"Escolha {n}", decision="x", why="y", today="2026-08-09")

    assert record_decision(tmp_path, "Quarta", decision="x", why="y", today="2026-08-09") == "D-004"
    assert [d.id for d in read_decisions(tmp_path)] == ["D-001", "D-002", "D-003", "D-004"]


def test_numbering_survives_a_gap_left_by_a_hand_written_entry(tmp_path: Path) -> None:
    """Alguém escreveu D-007 direto no arquivo (num terminal, fora daqui). O
    próximo id é 008 — reusar 008 do zero criaria dois registros com o mesmo id,
    e o id é a única forma de citar uma decisão em outro documento."""
    (tmp_path / ".harness").mkdir()
    (tmp_path / DECISIONS_FILE).write_text(
        "# Decisões\n\n## D-007 — Escrita à mão (2026-08-01)\nDecisão: x\nPorquê: y\n",
        encoding="utf-8",
    )

    assert record_decision(tmp_path, "Nova", decision="x", why="y", today="2026-08-09") == "D-008"


def test_recording_never_rewrites_a_byte_that_was_already_there(tmp_path: Path) -> None:
    """A garantia inteira deste registro. Se um append pudesse mexer no que já
    está gravado, o arquivo deixaria de ser prova de qualquer coisa."""
    record_decision(tmp_path, "Primeira", decision="a", why="b", today="2026-08-09")
    before = (tmp_path / DECISIONS_FILE).read_text(encoding="utf-8")

    record_decision(tmp_path, "Segunda", decision="c", why="d", today="2026-08-10")

    after = (tmp_path / DECISIONS_FILE).read_text(encoding="utf-8")
    assert after.startswith(before), "o conteúdo anterior tem que continuar idêntico, e no início"


def test_a_multiline_title_is_flattened_so_the_heading_stays_a_heading(tmp_path: Path) -> None:
    record_decision(
        tmp_path, "Título\ncom quebra", decision="x", why="y", today="2026-08-09"
    )

    decisions = read_decisions(tmp_path)
    assert decisions[0].title == "Título com quebra"


def test_the_reason_may_span_lines_because_a_reason_often_does(tmp_path: Path) -> None:
    record_decision(
        tmp_path,
        "Escolha",
        decision="Fazer X",
        why="Porque Y.\nA alternativa Z foi descartada: custa uma volta a mais.",
        today="2026-08-09",
    )

    decisions = read_decisions(tmp_path)
    assert "alternativa Z" in decisions[0].why


def test_reading_a_project_without_the_file_is_empty_not_an_error(tmp_path: Path) -> None:
    """Repo que nunca registrou decisão nenhuma é o estado inicial de todo
    projeto — não é falha, e levantar aqui derrubaria o hook de abertura."""
    assert read_decisions(tmp_path) == []


# ---------------------------------------------------------------------------
# REGRA: lição é uma linha, anotada sem interromper o trabalho, e o que está em
# aberto é separável do que o humano já resolveu.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LessonCase:
    why: str
    lines: list[str]
    expected_open: int
    expected_total: int


LESSON_CASES = [
    LessonCase(
        why="lição em aberto conta como aberta",
        lines=["- [ ] guard barrou demais -> abrir excecao"],
        expected_open=1,
        expected_total=1,
    ),
    LessonCase(
        why="lição fechada pelo humano some da lista de abertas, nao do arquivo",
        lines=["- [x] ja resolvida -> virou o verbo novo"],
        expected_open=0,
        expected_total=1,
    ),
    LessonCase(
        why="X maiusculo tambem conta como fechada",
        lines=["- [X] ja resolvida -> idem"],
        expected_open=0,
        expected_total=1,
    ),
    LessonCase(
        why="prosa solta no arquivo nao vira licao",
        lines=["# Licoes", "", "texto livre do humano", "- [ ] essa sim -> melhoria"],
        expected_open=1,
        expected_total=1,
    ),
]


@pytest.mark.parametrize("case", LESSON_CASES, ids=lambda c: c.why)
def test_lessons_are_read_by_checkbox_state(tmp_path: Path, case: LessonCase) -> None:
    (tmp_path / ".harness").mkdir()
    (tmp_path / LESSONS_FILE).write_text("\n".join(case.lines) + "\n", encoding="utf-8")

    assert len(read_lessons(tmp_path)) == case.expected_total
    assert len(open_lessons(tmp_path)) == case.expected_open


def test_recording_a_lesson_writes_the_friction_and_the_candidate_fix(tmp_path: Path) -> None:
    record_lesson(tmp_path, "o guard nega git switch em comando composto", fix="tornar o deny determinístico")

    content = (tmp_path / LESSONS_FILE).read_text(encoding="utf-8")
    assert "- [ ] o guard nega git switch em comando composto" in content
    assert "tornar o deny determinístico" in content

    lessons = open_lessons(tmp_path)
    assert len(lessons) == 1
    assert lessons[0].fix == "tornar o deny determinístico"


def test_a_lesson_is_one_line_even_when_the_friction_was_described_in_three(tmp_path: Path) -> None:
    """Uma lição por linha é o formato; texto multi-linha viraria um item que os
    leitores seguintes não conseguem contar."""
    record_lesson(tmp_path, "primeira linha\nsegunda linha", fix="alguma\ncoisa")

    body = (tmp_path / LESSONS_FILE).read_text(encoding="utf-8")
    assert len([line for line in body.splitlines() if line.startswith("- [")]) == 1


def test_recording_a_lesson_never_rewrites_what_was_already_there(tmp_path: Path) -> None:
    record_lesson(tmp_path, "primeira", fix="a")
    before = (tmp_path / LESSONS_FILE).read_text(encoding="utf-8")

    record_lesson(tmp_path, "segunda", fix="b")

    assert (tmp_path / LESSONS_FILE).read_text(encoding="utf-8").startswith(before)


# ---------------------------------------------------------------------------
# REGRA: o que vai para a abertura da sessão é o recente, não o acervo.
# ---------------------------------------------------------------------------

def test_a_project_without_decisions_injects_nothing(tmp_path: Path) -> None:
    assert render_decisions_section([]) is None


def test_the_section_carries_the_reason_not_only_the_title(tmp_path: Path) -> None:
    """Só o título faria a sessão saber que existe uma decisão sem saber o que
    ela proíbe — e o modo de falha que este registro existe para evitar é
    justamente re-tentar a alternativa já descartada."""
    record_decision(
        tmp_path, "Não inferir acoplamento", decision="Usar files[] declarado",
        why="Inferência por import erra em silêncio", today="2026-08-09",
    )

    section = render_decisions_section(read_decisions(tmp_path))

    assert section is not None
    assert "Não inferir acoplamento" in section
    assert "Inferência por import erra em silêncio" in section


def test_only_the_most_recent_decisions_are_injected(tmp_path: Path) -> None:
    """O acervo cresce com o projeto; o contexto de abertura, não. Injetar tudo
    faria a seção competir com o aviso de reconciliação e o resumo de progresso
    até os três serem lidos na diagonal."""
    for n in range(1, 13):
        record_decision(tmp_path, f"Decisao {n}", decision="x", why="y", today="2026-08-09")

    section = render_decisions_section(read_decisions(tmp_path), limit=5)

    assert section is not None
    assert "Decisao 12" in section
    assert "Decisao 7" not in section
    # o corte precisa ser DITO, senão a sessão acredita estar vendo o acervo inteiro
    assert "12" in section
