"""Testes de `harness.convergence` — o sinal de trajetória do §4.3.

T-02/T-03 do contrato `convergencia-opt-in`. Um teste por REGRA, tabela de
casos — `convergence.py` nunca chama git/subprocess/relógio; quem grava
recebe `commit`/`dirty`/`recorded_at` já prontos (mesma divisão de
`attempts.py`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.convergence import (
    ConvergenceError,
    best_so_far,
    metric_path,
    parse_metric_value,
    parse_target,
    read_measurements,
    record_measurement,
    summarize_trajectory,
    target_met,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_measurements(tmp_path: Path, values: list[float], contract: str = "c") -> None:
    lines = [
        json.dumps({"value": v, "recorded_at": "t", "commit": "abc", "dirty": False})
        for v in values
    ]
    _write(metric_path(tmp_path, contract, "T-01"), "\n".join(lines) + ("\n" if lines else ""))


# ---------------------------------------------------------------------------
# REGRA 1 — saída do metric_cmd que não parseia como número é erro, nunca zero
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ParseValueCase:
    stdout: str
    expect: float | None
    why: str


PARSE_VALUE_CASES = [
    ParseValueCase("0.85", 0.85, "número simples"),
    ParseValueCase("  0.85  \n", 0.85, "espaço/quebra de linha nas pontas é ignorado"),
    ParseValueCase("-3", -3.0, "negativo é um valor válido"),
    ParseValueCase("42", 42.0, "inteiro parseia como float"),
    ParseValueCase("", None, "saída vazia é falha de ambiente"),
    ParseValueCase("   ", None, "só espaço é falha de ambiente"),
    ParseValueCase("nao é um número", None, "texto é falha de ambiente"),
    ParseValueCase("0.85\n0.90", None, "múltiplas linhas não é 'um único número'"),
]


@pytest.mark.parametrize("case", PARSE_VALUE_CASES, ids=lambda c: c.why)
def test_parse_metric_value_never_invents_a_number(case: ParseValueCase) -> None:
    if case.expect is None:
        with pytest.raises(ConvergenceError):
            parse_metric_value(case.stdout)
    else:
        assert parse_metric_value(case.stdout) == case.expect


# ---------------------------------------------------------------------------
# REGRA 2 — target é uma expressão de comparação com direção
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TargetCase:
    target: str
    operator: str | None
    threshold: float | None
    why: str


TARGET_CASES = [
    TargetCase(">= 0.85", ">=", 0.85, "maior é melhor, com espaço"),
    TargetCase("<=5", "<=", 5.0, "menor é melhor, sem espaço"),
    TargetCase("> 0", ">", 0.0, "estritamente maior"),
    TargetCase("< 10", "<", 10.0, "estritamente menor"),
    TargetCase("== 5", None, None, "igualdade não tem direção — malformado por desenho"),
    TargetCase("qualquer coisa", None, None, "texto livre é malformado"),
    TargetCase("", None, None, "vazio é malformado"),
]


@pytest.mark.parametrize("case", TARGET_CASES, ids=lambda c: c.why)
def test_parse_target_extracts_operator_and_threshold(case: TargetCase) -> None:
    if case.operator is None:
        with pytest.raises(ConvergenceError):
            parse_target(case.target)
    else:
        assert parse_target(case.target) == (case.operator, case.threshold)


@dataclass(frozen=True)
class TargetMetCase:
    value: float
    target: str
    met: bool
    why: str


TARGET_MET_CASES = [
    TargetMetCase(0.90, ">= 0.85", True, "acima do limiar com >="),
    TargetMetCase(0.85, ">= 0.85", True, "empata o limiar com >="),
    TargetMetCase(0.80, ">= 0.85", False, "abaixo do limiar com >="),
    TargetMetCase(3, "<= 5", True, "abaixo do limiar com <="),
    TargetMetCase(5, "<= 5", True, "empata o limiar com <="),
    TargetMetCase(6, "<= 5", False, "acima do limiar com <="),
]


@pytest.mark.parametrize("case", TARGET_MET_CASES, ids=lambda c: c.why)
def test_target_met_compares_value_against_threshold(case: TargetMetCase) -> None:
    assert target_met(case.value, case.target) is case.met


# ---------------------------------------------------------------------------
# REGRA 3 — gravar é sempre APPEND, ler nunca levanta
# ---------------------------------------------------------------------------

def test_record_measurement_writes_the_full_schema(tmp_path: Path) -> None:
    path = record_measurement(
        tmp_path, "meu-contrato", "T-01",
        value=0.72, commit="a1b2c3d", dirty=False, recorded_at="2026-08-09T04:00:00+00:00",
    )
    record = json.loads(path.read_text(encoding="utf-8").strip())
    assert record == {
        "value": 0.72, "recorded_at": "2026-08-09T04:00:00+00:00",
        "commit": "a1b2c3d", "dirty": False,
    }


def test_record_measurement_accumulates_in_order(tmp_path: Path) -> None:
    for value in (0.5, 0.6, 0.7):
        record_measurement(
            tmp_path, "c", "T-01", value=value, commit="x", dirty=False, recorded_at="t",
        )
    records = read_measurements(tmp_path, "c", "T-01")
    assert [r["value"] for r in records] == [0.5, 0.6, 0.7]


@dataclass(frozen=True)
class ReadCase:
    content: str | None
    expect_values: list[float]
    why: str


READ_CASES = [
    ReadCase(None, [], "arquivo ausente"),
    ReadCase("", [], "arquivo vazio"),
    ReadCase('{"value": 0.5}\n', [0.5], "uma linha válida"),
    ReadCase('{"value": 0.5}\nnão é json\n{"value": 0.6}\n', [0.5, 0.6], "linha corrompida é pulada"),
    ReadCase('{"nota": "sem value"}\n{"value": 0.5}\n', [0.5], "linha sem value numérico é pulada"),
]


@pytest.mark.parametrize("case", READ_CASES, ids=lambda c: c.why)
def test_read_measurements_degrades_without_raising(tmp_path: Path, case: ReadCase) -> None:
    if case.content is not None:
        _write(metric_path(tmp_path, "c", "T-01"), case.content)
    records = read_measurements(tmp_path, "c", "T-01")
    assert [r["value"] for r in records] == case.expect_values


def test_feature_without_metric_creates_no_file(tmp_path: Path) -> None:
    assert read_measurements(tmp_path, "c", "T-01") == []
    assert not metric_path(tmp_path, "c", "T-01").exists()


# ---------------------------------------------------------------------------
# REGRA 4 — o melhor valor do rastro, na direção que o target manda
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BestCase:
    values: list[float]
    target: str
    expect_best: float | None
    why: str


BEST_CASES = [
    BestCase([], ">= 0.85", None, "rastro vazio"),
    BestCase([0.5, 0.9, 0.7], ">= 0.85", 0.9, "maior é melhor: argmax"),
    BestCase([10, 3, 7], "<= 5", 3, "menor é melhor: argmin"),
    BestCase([0.9, 0.5, 0.9], ">= 0.85", 0.9, "empate resolve pela mais antiga"),
]


@pytest.mark.parametrize("case", BEST_CASES, ids=lambda c: c.why)
def test_best_so_far_picks_the_extreme_by_target_direction(
    tmp_path: Path, case: BestCase
) -> None:
    _write_measurements(tmp_path, case.values)
    measurements = read_measurements(tmp_path, "c", "T-01")
    best = best_so_far(measurements, case.target)
    if case.expect_best is None:
        assert best is None
    else:
        assert best["value"] == case.expect_best


def test_best_so_far_prefers_the_oldest_on_tie(tmp_path: Path) -> None:
    _write_measurements(tmp_path, [0.9, 0.5, 0.9])
    measurements = read_measurements(tmp_path, "c", "T-01")
    best = best_so_far(measurements, ">= 0.85")
    assert best is measurements[0]


# ---------------------------------------------------------------------------
# REGRA 5 — trajetória: piora (últimas piores que o melhor) e platô (últimas
# sem bater recorde) são sinais DIFERENTES — oscilação cai só no platô
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TrajectoryCase:
    values: list[float]
    target: str
    worsening: int
    plateau: int
    why: str


TRAJECTORY_CASES = [
    TrajectoryCase([], ">= 0.85", 0, 0, "rastro vazio"),
    TrajectoryCase([0.9], ">= 0.85", 0, 0, "uma medição não pode ser pior que si mesma"),
    TrajectoryCase([0.9, 0.7], ">= 0.85", 1, 1, "uma piora conta uma vez nos dois sinais"),
    TrajectoryCase(
        [0.9, 0.7, 0.6], ">= 0.85", 2, 2,
        "duas piores seguidas: fecha o teto de stop_worsening (2)",
    ),
    TrajectoryCase(
        [0.9, 0.5, 0.9, 0.5, 0.9], ">= 0.85", 0, 4,
        "oscilação que sempre volta ao pico: não é 'pior que o melhor' no "
        "fim (empata), mas nenhuma das últimas 4 bateu recorde — só o platô "
        "pega isso, exatamente o caso que o design chama de traiçoeiro",
    ),
    TrajectoryCase(
        [3, 4, 5], "<= 2", 2, 2,
        "direção invertida (menor é melhor): as duas últimas pioraram frente à primeira",
    ),
]


@pytest.mark.parametrize("case", TRAJECTORY_CASES, ids=lambda c: c.why)
def test_summarize_trajectory_distinguishes_worsening_from_plateau(
    tmp_path: Path, case: TrajectoryCase
) -> None:
    _write_measurements(tmp_path, case.values)
    measurements = read_measurements(tmp_path, "c", "T-01")
    summary = summarize_trajectory(measurements, case.target)
    assert summary["worsening_streak"] == case.worsening
    assert summary["plateau_streak"] == case.plateau


def test_summarize_trajectory_target_met_reflects_the_latest_measurement(
    tmp_path: Path,
) -> None:
    _write_measurements(tmp_path, [0.5, 0.9])
    measurements = read_measurements(tmp_path, "c", "T-01")
    assert summarize_trajectory(measurements, ">= 0.85")["target_met"] is True

    _write_measurements(tmp_path, [0.9, 0.5], contract="c2")
    measurements2 = read_measurements(tmp_path, "c2", "T-01")
    assert summarize_trajectory(measurements2, ">= 0.85")["target_met"] is False


def test_summarize_trajectory_empty_trail_is_all_zero(tmp_path: Path) -> None:
    summary = summarize_trajectory([], ">= 0.85")
    assert summary == {
        "best": None, "worsening_streak": 0, "plateau_streak": 0, "target_met": False,
    }


# ---------------------------------------------------------------------------
# REGRA 6 — o caminho do rastro é escopado por contrato, mesmo padrão de attempts
# ---------------------------------------------------------------------------

def test_metric_path_is_scoped_by_contract_and_suffixed(tmp_path: Path) -> None:
    path = metric_path(tmp_path, "meu-contrato", "T-01")
    assert path == tmp_path / ".harness" / "attempts" / "meu-contrato" / "T-01-metric.jsonl"


def test_metric_path_never_collides_with_the_failure_trail(tmp_path: Path) -> None:
    from harness.attempts import attempts_path

    assert metric_path(tmp_path, "c", "T-01") != attempts_path(tmp_path, "c", "T-01")
