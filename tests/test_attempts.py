"""Testes de `harness.attempts` — o rastro de tentativas de verificação.

T-01 do contrato `rastro-de-tentativas-e-budget` (§5.1/§8.2 de
`docs/reference/loop-engineering-design.md`): até aqui, `harness verify`
gravava SÓ sucesso — a falha não deixava rastro nenhum em disco, e a regra do
padrão repetido ("mesma falha de novo = a abordagem está errada, não a
execução") só existia como prosa no passo 10 do lifecycle, contada de cabeça
pelo agente e perdida na primeira sessão nova.

Este módulo é só o registro e a contagem. Quem grava é `verify` (T-02); quem
decide continuar ou parar é `budget` (T-04). Um teste por REGRA, com tabela de
casos — não um `def` por caso.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.attempts import (
    ATTEMPTS_DIR,
    UNSCOPED_ATTEMPTS_DIR,
    attempts_path,
    extract_failure_line,
    failure_signature,
    read_attempts,
    record_failure,
    record_pass,
    summarize,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------------------------------------------------------------------
# REGRA 1 — o rastro é escopado por contrato, espelhando `evidence_path`
#
# Mesmo motivo do caminho da evidência (`verify.evidence_path`): todo contrato
# começa em `T-01`, então rastro sem contrato no caminho faz o contrato novo
# herdar a contagem de falhas do anterior — e o disjuntor de T-04 pararia o
# loop por falhas que outro contrato cometeu.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PathCase:
    contract: object
    expected_dir: str
    why: str


PATH_CASES = [
    PathCase("meu-contrato", "meu-contrato", "slug normal vira subdiretório"),
    PathCase("", UNSCOPED_ATTEMPTS_DIR, "contrato vazio cai no diretório sem-contrato"),
    PathCase(None, UNSCOPED_ATTEMPTS_DIR, "contrato ausente cai no diretório sem-contrato"),
    PathCase("  ", UNSCOPED_ATTEMPTS_DIR, "só espaço conta como ausente"),
    PathCase("  outro  ", "outro", "espaço em volta não vira parte do nome"),
]


@pytest.mark.parametrize("case", PATH_CASES, ids=lambda c: c.why)
def test_attempts_path_is_scoped_by_contract(tmp_path: Path, case: PathCase) -> None:
    path = attempts_path(tmp_path, case.contract, "T-01")
    assert path == tmp_path / ATTEMPTS_DIR / case.expected_dir / "T-01.jsonl"


def test_attempts_path_never_collides_between_contracts(tmp_path: Path) -> None:
    a = attempts_path(tmp_path, "contrato-a", "T-01")
    b = attempts_path(tmp_path, "contrato-b", "T-01")
    assert a != b


# ---------------------------------------------------------------------------
# REGRA 2 — a assinatura identifica a MESMA falha, ignorando ruído de espaço
#
# A assinatura é o que permite distinguir "tentei de novo e quebrou igual"
# (abordagem errada) de "quebrou em outro ponto" (progresso). Ela normaliza
# espaço porque runner de teste alinha coluna de forma instável entre rodadas.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignatureCase:
    left: str
    right: str
    same: bool
    why: str


SIGNATURE_CASES = [
    SignatureCase("E   assert 1 == 2", "E   assert 1 == 2", True, "linha idêntica"),
    SignatureCase("E   assert 1 == 2", "E assert 1 == 2", True, "espaço interno colapsado"),
    SignatureCase("E assert 1 == 2", "  E assert 1 == 2  ", True, "espaço nas pontas ignorado"),
    SignatureCase("E assert 1 == 2", "E\tassert 1 == 2", True, "tab conta como espaço"),
    SignatureCase("E assert 1 == 2", "E assert 1 == 3", False, "valor diferente é falha diferente"),
    SignatureCase("ModuleNotFoundError: x", "ModuleNotFoundError: y", False, "módulo diferente"),
    SignatureCase("E assert 1 == 2", "e assert 1 == 2", False, "caixa não é normalizada"),
    SignatureCase("", "", True, "vazio é estável"),
]


@pytest.mark.parametrize("case", SIGNATURE_CASES, ids=lambda c: c.why)
def test_failure_signature_matches_same_failure_across_noise(case: SignatureCase) -> None:
    assert (failure_signature(case.left) == failure_signature(case.right)) is case.same


def test_failure_signature_is_short_stable_hex() -> None:
    signature = failure_signature("E   assert 1 == 2")
    assert len(signature) == 12
    assert all(char in "0123456789abcdef" for char in signature)
    assert signature == failure_signature("E   assert 1 == 2")


# ---------------------------------------------------------------------------
# REGRA 3 — a linha da falha vem do erro cru, stderr primeiro
#
# §3 do design: "erro entra cru no próximo ciclo — resumir erro é jogar fora o
# sinal". O que é guardado é a primeira linha ÚTIL do erro real, não um resumo
# escrito pelo agente. stderr antes de stdout porque é onde o traceback sai;
# pytest, porém, imprime o resumo em stdout — daí o fallback.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FailureLineCase:
    stdout: str
    stderr: str
    expect: str
    why: str


FAILURE_LINE_CASES = [
    FailureLineCase("", "Traceback (most recent call last):", "Traceback (most recent call last):", "stderr tem prioridade"),
    FailureLineCase("saída normal", "boom", "boom", "stderr vence stdout quando os dois têm conteúdo"),
    FailureLineCase("E assert 1 == 2", "", "E assert 1 == 2", "sem stderr, cai no stdout"),
    FailureLineCase("E assert 1 == 2", "   \n  \n", "E assert 1 == 2", "stderr só com espaço conta como vazio"),
    FailureLineCase("\n\nprimeira útil\nsegunda", "", "primeira útil", "pula linha em branco do topo"),
    FailureLineCase("  recuada  ", "", "recuada", "linha devolvida sem espaço nas pontas"),
    FailureLineCase("", "", "", "sem saída nenhuma devolve vazio"),
]


@pytest.mark.parametrize("case", FAILURE_LINE_CASES, ids=lambda c: c.why)
def test_extract_failure_line_takes_first_useful_line(case: FailureLineCase) -> None:
    assert extract_failure_line(case.stdout, case.stderr) == case.expect


def test_extract_failure_line_truncates_very_long_output() -> None:
    line = extract_failure_line("x" * 500, "")
    assert len(line) == 300


# ---------------------------------------------------------------------------
# REGRA 4 — gravar é sempre APPEND: o rastro é o produto, nunca é sobrescrito
#
# Um rastro que o verde apaga não serve para nada: a pergunta "o que já falhou
# aqui?" é feita pela sessão SEGUINTE, depois de a fatia ter ficado verde.
# ---------------------------------------------------------------------------

def test_record_failure_writes_the_full_schema(tmp_path: Path) -> None:
    path = record_failure(
        tmp_path,
        "meu-contrato",
        "T-01",
        verify_cmd="pytest tests/test_x.py -q",
        exit_code=1,
        stdout="E assert 1 == 2",
        stderr="",
        files_hash="sha256:abc",
        recorded_at="2026-08-09T04:00:00+00:00",
    )

    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record == {
        "result": "fail",
        "contract": "meu-contrato",
        "feature_id": "T-01",
        "recorded_at": "2026-08-09T04:00:00+00:00",
        "verify_cmd": "pytest tests/test_x.py -q",
        "exit_code": 1,
        "failure_line": "E assert 1 == 2",
        "failure_signature": failure_signature("E assert 1 == 2"),
        "files_hash": "sha256:abc",
    }


def test_record_pass_writes_the_full_schema(tmp_path: Path) -> None:
    path = record_pass(
        tmp_path,
        "meu-contrato",
        "T-01",
        files_hash="sha256:def",
        recorded_at="2026-08-09T04:05:00+00:00",
    )

    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record == {
        "result": "pass",
        "recorded_at": "2026-08-09T04:05:00+00:00",
        "files_hash": "sha256:def",
    }


def test_records_accumulate_in_order_and_survive_the_green(tmp_path: Path) -> None:
    for exit_code in (1, 2):
        record_failure(
            tmp_path, "c", "T-01",
            verify_cmd="pytest", exit_code=exit_code, stdout=f"erro {exit_code}",
            stderr="", files_hash="h", recorded_at="2026-08-09T04:00:00+00:00",
        )
    record_pass(tmp_path, "c", "T-01", files_hash="h", recorded_at="2026-08-09T04:01:00+00:00")

    records = read_attempts(tmp_path, "c", "T-01")
    assert [r["result"] for r in records] == ["fail", "fail", "pass"]
    assert [r["exit_code"] for r in records if r["result"] == "fail"] == [1, 2]


def test_record_failure_creates_the_directory_when_missing(tmp_path: Path) -> None:
    assert not (tmp_path / ATTEMPTS_DIR).exists()
    path = record_failure(
        tmp_path, "c", "T-01",
        verify_cmd="pytest", exit_code=1, stdout="x", stderr="",
        files_hash="h", recorded_at="2026-08-09T04:00:00+00:00",
    )
    assert path.is_file()


# ---------------------------------------------------------------------------
# REGRA 5 — ler rastro ausente ou corrompido nunca levanta
#
# Mesma degradação graciosa do resto do harness (`supervisor.dispatch_next`,
# `branching.load_branch_per_contract`): o rastro é subproduto. Uma linha
# corrompida não pode derrubar a verificação que a estava gravando.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ReadCase:
    content: str | None
    expect_results: list[str]
    why: str


READ_CASES = [
    ReadCase(None, [], "arquivo ausente"),
    ReadCase("", [], "arquivo vazio"),
    ReadCase("\n\n  \n", [], "só linhas em branco"),
    ReadCase('{"result": "fail"}\n', ["fail"], "uma linha válida"),
    ReadCase('{"result": "fail"}\nnão é json\n{"result": "pass"}\n', ["fail", "pass"], "linha corrompida é pulada"),
    ReadCase('[1, 2, 3]\n{"result": "fail"}\n', ["fail"], "json válido que não é objeto é pulado"),
]


@pytest.mark.parametrize("case", READ_CASES, ids=lambda c: c.why)
def test_read_attempts_degrades_without_raising(tmp_path: Path, case: ReadCase) -> None:
    if case.content is not None:
        _write(attempts_path(tmp_path, "c", "T-01"), case.content)
    records = read_attempts(tmp_path, "c", "T-01")
    assert [r.get("result") for r in records] == case.expect_results


# ---------------------------------------------------------------------------
# REGRA 6 — os contadores respondem as três perguntas do disjuntor
#
# "quantas vezes já falhou?" (total), "quantas desde o último verde?"
# (consecutivas — o teto de iterações de §4.2) e "quantas vezes seguidas com a
# MESMA falha?" (§8.2 — o sinal de que insistir não adianta). O verde zera as
# duas últimas: fatia que passou e voltou a quebrar recomeça a contagem.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SummaryCase:
    sequence: list[str]
    total: int
    consecutive: int
    streak: int
    why: str


SUMMARY_CASES = [
    SummaryCase([], 0, 0, 0, "rastro vazio"),
    SummaryCase(["a"], 1, 1, 1, "uma falha"),
    SummaryCase(["a", "a", "a"], 3, 3, 3, "mesma falha três vezes"),
    SummaryCase(["a", "b", "c"], 3, 3, 1, "falhas diferentes: streak só conta a última"),
    SummaryCase(["a", "a", "b"], 3, 3, 1, "falha mudou no fim: streak reinicia"),
    SummaryCase(["a", "b", "b"], 3, 3, 2, "as duas últimas iguais"),
    SummaryCase(["P"], 0, 0, 0, "só verde"),
    SummaryCase(["a", "a", "P"], 2, 0, 0, "verde zera consecutivas e streak, total permanece"),
    SummaryCase(["a", "a", "P", "b"], 3, 1, 1, "quebrou de novo depois do verde: conta do zero"),
    SummaryCase(["a", "P", "a", "a"], 3, 2, 2, "mesma assinatura de antes do verde não soma com a de depois"),
]


def _write_sequence(tmp_path: Path, sequence: list[str]) -> None:
    lines = []
    for token in sequence:
        if token == "P":
            lines.append(json.dumps({"result": "pass", "recorded_at": "t", "files_hash": "h"}))
        else:
            lines.append(json.dumps({
                "result": "fail",
                "contract": "c",
                "feature_id": "T-01",
                "recorded_at": "t",
                "verify_cmd": "pytest",
                "exit_code": 1,
                "failure_line": token,
                "failure_signature": failure_signature(token),
                "files_hash": "h",
            }))
    _write(attempts_path(tmp_path, "c", "T-01"), "\n".join(lines) + ("\n" if lines else ""))


@pytest.mark.parametrize("case", SUMMARY_CASES, ids=lambda c: c.why)
def test_summarize_counts_total_consecutive_and_same_failure_streak(
    tmp_path: Path, case: SummaryCase
) -> None:
    _write_sequence(tmp_path, case.sequence)
    summary = summarize(read_attempts(tmp_path, "c", "T-01"))
    assert summary["attempts_total"] == case.total
    assert summary["consecutive_failures"] == case.consecutive
    assert summary["same_signature_streak"] == case.streak


def test_summarize_exposes_the_last_raw_failure_for_the_escalation(tmp_path: Path) -> None:
    """A escalada ao humano (§8) pede o último erro CRU. O resumo carrega a
    linha e a assinatura da última falha para quem for montar esse relatório —
    sem obrigar o consumidor a reparsear o jsonl."""
    _write_sequence(tmp_path, ["primeira", "última"])
    summary = summarize(read_attempts(tmp_path, "c", "T-01"))
    assert summary["last_failure_line"] == "última"
    assert summary["last_failure_signature"] == failure_signature("última")


def test_summarize_has_no_last_failure_after_a_green(tmp_path: Path) -> None:
    _write_sequence(tmp_path, ["quebrou", "P"])
    summary = summarize(read_attempts(tmp_path, "c", "T-01"))
    assert summary["last_failure_line"] is None
    assert summary["last_failure_signature"] is None
