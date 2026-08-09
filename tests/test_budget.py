"""Testes de `harness.budget` — o disjuntor mecânico do loop.

T-04 do contrato `rastro-de-tentativas-e-budget`, fechando §4.2 do design de
loop engineering: "critério semântico mal escrito + ausência de teto = loop
infinito; o budget é o seguro contra o próprio erro de design".

Até aqui `max_green_iterations` existia no `harness.yaml` e no schema do
`config.py` sem UM consumidor — era compilado para o `AGENTS.md` na seção
literalmente chamada "Orçamento (orientação)". Este módulo é o consumidor: o
mesmo número passa a decidir, por contagem, quando o loop para.

O que este módulo NÃO faz (deliberado, mesmo desenho de `supervisor.py`): não
escreve nada, não roda `verify_cmd`, não chama git. Ele responde uma pergunta;
obedecer é papel de quem chama — hoje o passo 10 do lifecycle, amanhã o hook
Stop bloqueante da Fase 6.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from harness.attempts import CLASSIFICATION_TRANSIENT, attempts_path, failure_signature
from harness.budget import (
    DEFAULT_SAME_SIGNATURE_LIMIT,
    STOP_TRANSIENT_EXHAUSTED,
    BudgetError,
    check_budget,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(
    tmp_path: Path,
    typed: list[dict] | None = None,
    contract: str = "exemplo",
    feature_id: str = "T-01",
) -> None:
    payload = {
        "contract": contract,
        "compiled_at": "2026-08-09T04:00:00+00:00",
        "stop_conditions": {"typed": typed or [], "advisory": []},
        "features": [
            {
                "id": feature_id,
                "desc": "Fazer alguma coisa",
                "files": ["src/x.py"],
                "verify_cmd": "pytest -q",
                "depends": [],
                "passes": False,
            }
        ],
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _write_trail(tmp_path: Path, sequence: list[str], contract: str = "exemplo") -> None:
    """`sequence` usa tokens: "P" = verde, qualquer outro = falha com aquela
    assinatura."""
    lines = []
    for token in sequence:
        if token == "P":
            lines.append(json.dumps({"result": "pass", "recorded_at": "t", "files_hash": "h"}))
        else:
            lines.append(json.dumps({
                "result": "fail",
                "contract": contract,
                "feature_id": "T-01",
                "recorded_at": "t",
                "verify_cmd": "pytest -q",
                "exit_code": 1,
                "failure_line": token,
                "failure_signature": failure_signature(token),
                "files_hash": "h",
            }))
    _write(attempts_path(tmp_path, contract, "T-01"), "\n".join(lines) + ("\n" if lines else ""))


def _write_yaml(tmp_path: Path, max_green_iterations: int | None) -> None:
    body = "governance:\n"
    if max_green_iterations is not None:
        body += f"  budget:\n    max_green_iterations: {max_green_iterations}\n"
    else:
        body += "  approval_policy: auto\n"
    _write(tmp_path / ".harness" / "harness.yaml", body)


# ---------------------------------------------------------------------------
# REGRA 1 — os três vereditos, decididos por contagem e não por opinião
#
# `continue` enquanto há folga; `stop_same_failure` quando insistir deixou de
# adiantar (§8.2); `stop_iterations` quando o teto de §4.2 estourou.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class VerdictCase:
    sequence: list[str]
    verdict: str
    typed: list[dict] = field(default_factory=list)
    max_green: int = 12
    why: str = ""


VERDICT_CASES = [
    VerdictCase([], "continue", why="sem rastro: nada aconteceu ainda"),
    VerdictCase(["a"], "continue", why="uma falha está longe de qualquer teto"),
    VerdictCase(["a", "b"], "continue", why="falhas diferentes: houve mudança de sinal"),
    VerdictCase(["a", "a"], "continue", why="duas iguais ainda não fecham o padrão"),
    VerdictCase(["a", "a", "a"], "stop_same_failure", why="três iguais: a abordagem é que está errada"),
    VerdictCase(["a", "a", "a", "a"], "stop_same_failure", why="acima do teto continua parado"),
    VerdictCase(["a", "b", "a"], "continue", why="a mesma falha não-consecutiva não fecha o padrão"),
    VerdictCase(
        ["a", "b", "c", "d"], "stop_iterations", max_green=4,
        why="teto de iterações estourado com falhas todas diferentes",
    ),
    VerdictCase(
        ["a", "a", "P", "b"], "continue", max_green=2,
        why="o verde zera a contagem: o teto conta do último verde",
    ),
    VerdictCase(
        ["a", "a", "a"], "continue", typed=[{"type": "same_failure_signature", "n": 5}],
        why="contrato afrouxou o teto do padrão repetido",
    ),
    VerdictCase(
        ["a", "b"], "stop_iterations", typed=[{"type": "consecutive_verify_failures", "n": 2}],
        why="contrato apertou o teto de iterações",
    ),
    VerdictCase(
        ["a", "a"], "stop_same_failure", typed=[{"type": "same_failure_signature", "n": 2}],
        why="contrato apertou o teto do padrão repetido",
    ),
]


@pytest.mark.parametrize("case", VERDICT_CASES, ids=lambda c: c.why)
def test_check_budget_decides_by_counting(tmp_path: Path, case: VerdictCase) -> None:
    _write_feature_list(tmp_path, typed=case.typed)
    _write_yaml(tmp_path, case.max_green)
    _write_trail(tmp_path, case.sequence)

    assert check_budget(tmp_path, "T-01")["verdict"] == case.verdict


def test_same_failure_wins_when_both_limits_trip(tmp_path: Path) -> None:
    """Os dois tetos podem estourar juntos; o veredito reportado é o do padrão
    repetido porque ele carrega o DIAGNÓSTICO — "insistir nesta abordagem não
    leva a lugar nenhum" é acionável; "acabaram as tentativas" só informa que
    o tempo passou."""
    _write_feature_list(tmp_path, typed=[
        {"type": "same_failure_signature", "n": 2},
        {"type": "consecutive_verify_failures", "n": 2},
    ])
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, ["a", "a"])

    assert check_budget(tmp_path, "T-01")["verdict"] == "stop_same_failure"


# ---------------------------------------------------------------------------
# REGRA 1.5 — falha transiente esgotada (§8.1) vence QUALQUER outro veredito
#
# "Mesmo erro transiente 3× → reclassificar como infra (§8.3)": o único jeito
# de existir um registro `classification: "transient"` no rastro é
# `verify.run_verify` já ter esgotado os retries — então não espera acumular
# teto nenhum, e não compete com o loop de correção normal do §8.2.
# ---------------------------------------------------------------------------

def _write_trail_ending_transient(
    tmp_path: Path,
    structural_sequence: list[str],
    transient_line: str,
    contract: str = "exemplo",
) -> None:
    lines = []
    for token in structural_sequence:
        lines.append(json.dumps({
            "result": "fail", "contract": contract, "feature_id": "T-01",
            "recorded_at": "t", "verify_cmd": "pytest -q", "exit_code": 1,
            "failure_line": token, "failure_signature": failure_signature(token),
            "files_hash": "h", "classification": "structural",
        }))
    lines.append(json.dumps({
        "result": "fail", "contract": contract, "feature_id": "T-01",
        "recorded_at": "t", "verify_cmd": "pytest -q", "exit_code": 1,
        "failure_line": transient_line, "failure_signature": failure_signature(transient_line),
        "files_hash": "h", "classification": CLASSIFICATION_TRANSIENT,
    }))
    _write(attempts_path(tmp_path, contract, "T-01"), "\n".join(lines) + "\n")


def test_transient_exhausted_stops_immediately_without_waiting_for_any_threshold(
    tmp_path: Path,
) -> None:
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail_ending_transient(tmp_path, [], "Connection refused")

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == STOP_TRANSIENT_EXHAUSTED


def test_transient_exhausted_wins_even_when_structural_thresholds_also_trip(
    tmp_path: Path,
) -> None:
    """Uma sequência estrutural que já bateria `stop_same_failure` sozinha,
    seguida do esgotamento transiente: o veredito é o transiente — §8.3 vence
    §8.2, do mesmo jeito que `health.py` prioriza proteção sobre ferramenta."""
    _write_feature_list(tmp_path, typed=[{"type": "same_failure_signature", "n": 2}])
    _write_yaml(tmp_path, 12)
    _write_trail_ending_transient(tmp_path, ["a", "a"], "Read timed out")

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == STOP_TRANSIENT_EXHAUSTED


def test_transient_exhausted_reason_names_the_environment_not_the_approach(
    tmp_path: Path,
) -> None:
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail_ending_transient(tmp_path, [], "Connection refused")

    reason = check_budget(tmp_path, "T-01")["reason"]
    assert "Connection refused" in reason
    assert "abordagem" not in reason


# ---------------------------------------------------------------------------
# REGRA 2 — o teto efetivo: o contrato manda, a config é o default
#
# `max_green_iterations` do `harness.yaml` deixa de ser texto de orientação e
# vira o default do teto de iterações; a condição tipada do contrato, quando
# existe, vence — é a demanda declarando que ela é mais (ou menos) tolerante.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LimitCase:
    typed: list[dict]
    max_green: int | None
    expect_consecutive: int
    expect_same: int
    why: str


LIMIT_CASES = [
    LimitCase([], 12, 12, DEFAULT_SAME_SIGNATURE_LIMIT, "sem tipada: config manda no teto de iterações"),
    LimitCase([], 5, 5, DEFAULT_SAME_SIGNATURE_LIMIT, "config diferente do default do schema"),
    LimitCase([], None, 12, DEFAULT_SAME_SIGNATURE_LIMIT, "yaml sem a chave: default do schema (12)"),
    LimitCase(
        [{"type": "consecutive_verify_failures", "n": 3}], 12, 3, DEFAULT_SAME_SIGNATURE_LIMIT,
        "tipada vence a config",
    ),
    LimitCase(
        [{"type": "same_failure_signature", "n": 7}], 12, 12, 7,
        "tipada do padrão repetido não mexe no teto de iterações",
    ),
    LimitCase(
        [{"type": "consecutive_verify_failures", "n": 4}, {"type": "same_failure_signature", "n": 2}],
        12, 4, 2, "as duas tipadas juntas",
    ),
]


@pytest.mark.parametrize("case", LIMIT_CASES, ids=lambda c: c.why)
def test_effective_limits_prefer_the_contract_over_the_config(
    tmp_path: Path, case: LimitCase
) -> None:
    _write_feature_list(tmp_path, typed=case.typed)
    _write_yaml(tmp_path, case.max_green)
    _write_trail(tmp_path, [])

    limits = check_budget(tmp_path, "T-01")["limits"]
    assert limits["consecutive_verify_failures"] == case.expect_consecutive
    assert limits["same_failure_signature"] == case.expect_same


def test_missing_yaml_falls_back_to_the_schema_default(tmp_path: Path) -> None:
    """Mesma degradação graciosa de `branching.load_branch_per_contract`: sem
    yaml, o teto é o do schema — nunca "sem teto"."""
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [])

    assert check_budget(tmp_path, "T-01")["limits"]["consecutive_verify_failures"] == 12


def test_broken_yaml_falls_back_to_the_schema_default(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write(tmp_path / ".harness" / "harness.yaml", "governance: [isto não é um mapa\n")
    _write_trail(tmp_path, [])

    assert check_budget(tmp_path, "T-01")["limits"]["consecutive_verify_failures"] == 12


# ---------------------------------------------------------------------------
# REGRA 3 — o relatório carrega os contadores e uma razão para humano
#
# §4.2: "estourar budget nunca é silencioso — registra o que foi tentado, qual
# o último erro, e devolve controle ao humano com diagnóstico, não com
# 'falhou'".
# ---------------------------------------------------------------------------

def test_report_carries_counters_identity_and_the_last_raw_error(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, ["a", "P", "b", "b"])

    report = check_budget(tmp_path, "T-01")

    assert report["feature_id"] == "T-01"
    assert report["contract"] == "exemplo"
    assert report["attempts_total"] == 3
    assert report["consecutive_failures"] == 2
    assert report["same_signature_streak"] == 2
    assert report["last_failure_line"] == "b"
    assert report["last_failure_signature"] == failure_signature("b")


@dataclass(frozen=True)
class ReasonCase:
    sequence: list[str]
    max_green: int
    fragments: list[str]
    why: str


REASON_CASES = [
    ReasonCase([], 12, ["continuar"], "sem falha: razão diz que há folga"),
    ReasonCase(["a", "a", "a"], 12, ["3", "mesma"], "padrão repetido cita a contagem e a repetição"),
    ReasonCase(["a", "b", "c"], 3, ["3", "3"], "teto de iterações cita contagem e teto"),
]


@pytest.mark.parametrize("case", REASON_CASES, ids=lambda c: c.why)
def test_reason_is_a_sentence_for_a_person(tmp_path: Path, case: ReasonCase) -> None:
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, case.max_green)
    _write_trail(tmp_path, case.sequence)

    reason = check_budget(tmp_path, "T-01")["reason"]
    assert isinstance(reason, str) and reason
    for fragment in case.fragments:
        assert fragment in reason


def test_stop_reason_points_at_the_next_move(tmp_path: Path) -> None:
    """Parar sem dizer o que fazer devolve o problema ao humano sem
    diagnóstico — exatamente o que §8 proíbe."""
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, ["a", "a", "a"])

    reason = check_budget(tmp_path, "T-01")["reason"]
    assert "abordagem" in reason


# ---------------------------------------------------------------------------
# REGRA 4 — perguntar sobre o que não existe é erro, não veredito
#
# Devolver `continue` para uma feature inexistente faria um id digitado errado
# parecer autorização para seguir tentando.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ErrorCase:
    with_feature_list: bool
    feature_id: str
    fragment: str
    why: str


ERROR_CASES = [
    ErrorCase(False, "T-01", "feature_list", "contrato não compilado"),
    ErrorCase(True, "T-99", "T-99", "id que não existe no contrato"),
]


@pytest.mark.parametrize("case", ERROR_CASES, ids=lambda c: c.why)
def test_check_budget_refuses_unknown_targets(tmp_path: Path, case: ErrorCase) -> None:
    if case.with_feature_list:
        _write_feature_list(tmp_path)

    with pytest.raises(BudgetError) as excinfo:
        check_budget(tmp_path, case.feature_id)
    assert case.fragment in str(excinfo.value)


# ---------------------------------------------------------------------------
# REGRA 5 — consultar o disjuntor nunca muda o estado
#
# Mesma postura de `supervisor.dispatch_next` e `finish.audit_closure`: quem
# lê não escreve. Um disjuntor que altera o que mede é inútil como medida.
# ---------------------------------------------------------------------------

def test_the_agent_can_actually_run_the_verb(tmp_path: Path) -> None:
    """Um disjuntor que o agente não consegue consultar não é disjuntor.

    O passo 10 do lifecycle manda rodar `harness budget` a cada falha, e o
    `boundary_guard` só libera os subcomandos que estão em
    `_HARNESS_SUBCOMMANDS` — verbo novo fora dessa lista é negado em runtime,
    com a CLI aceitando o comando e o hook barrando. Foi exatamente o que
    aconteceu com `pr-draft`, entregue na v0.32.0 e nunca adicionado à lista:
    o passo 16 do lifecycle mandava rodar um comando que o guard negava. Os
    dois entram aqui, e este teste existe para que o próximo verbo não repita
    o esquecimento.
    """
    from harness.boundary_guard import render_boundary_guard

    generated = render_boundary_guard()
    for subcommand in ("budget", "pr-draft"):
        assert f'"{subcommand}"' in generated


def test_check_budget_writes_nothing(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, ["a", "a", "a"])

    before = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    check_budget(tmp_path, "T-01")
    after = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    assert before == after
