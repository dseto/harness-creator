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
    STOP_PLATEAU,
    STOP_TRANSIENT_EXHAUSTED,
    STOP_WORSENING,
    BudgetError,
    check_budget,
)
from harness.convergence import metric_path


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
# REGRA 1.6 — trajetória de métrica (§4.3, contrato `convergencia-opt-in`):
# `stop_worsening`/`stop_plateau` só existem para tarefa com `metric_cmd` E
# `metric_target`, e ficam ATRÁS de qualquer veredito estrutural na ordem de
# precedência.
# ---------------------------------------------------------------------------

def _write_feature_list_with_metric(
    tmp_path: Path,
    metric_cmd: str | None = "python metric.py",
    metric_target: str | None = ">= 0.85",
    typed: list[dict] | None = None,
    contract: str = "exemplo",
    feature_id: str = "T-01",
) -> None:
    feature = {
        "id": feature_id, "desc": "Fazer alguma coisa", "files": ["src/x.py"],
        "verify_cmd": "pytest -q", "depends": [], "passes": False,
    }
    if metric_cmd:
        feature["metric_cmd"] = metric_cmd
        if metric_target:
            feature["metric_target"] = metric_target
    payload = {
        "contract": contract,
        "compiled_at": "2026-08-09T04:00:00+00:00",
        "stop_conditions": {"typed": typed or [], "advisory": []},
        "features": [feature],
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _write_measurements(tmp_path: Path, values: list[float], contract: str = "exemplo") -> None:
    lines = [
        json.dumps({"value": v, "recorded_at": "t", "commit": "abc1234", "dirty": False})
        for v in values
    ]
    _write(metric_path(tmp_path, contract, "T-01"), "\n".join(lines) + ("\n" if lines else ""))


@dataclass(frozen=True)
class TrajectoryVerdictCase:
    values: list[float]
    verdict: str
    why: str


TRAJECTORY_VERDICT_CASES = [
    TrajectoryVerdictCase([], "continue", "sem medição: nada para julgar"),
    TrajectoryVerdictCase([0.9], "continue", "uma medição não é pior que si mesma"),
    TrajectoryVerdictCase([0.9, 0.7], "continue", "uma piora só não fecha o teto de 2"),
    TrajectoryVerdictCase([0.9, 0.7, 0.6], "stop_worsening", "duas seguidas piores que o melhor"),
    TrajectoryVerdictCase(
        [0.9, 0.5, 0.9, 0.5, 0.9], STOP_PLATEAU,
        "oscilação sem nunca bater recorde: só o platô pega, não a piora",
    ),
    TrajectoryVerdictCase([0.9, 0.95], "continue", "bateu recorde: nem piora nem platô"),
]


@pytest.mark.parametrize("case", TRAJECTORY_VERDICT_CASES, ids=lambda c: c.why)
def test_trajectory_verdicts_from_metric_measurements(
    tmp_path: Path, case: TrajectoryVerdictCase
) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, case.values)

    assert check_budget(tmp_path, "T-01")["verdict"] == case.verdict


def test_structural_verdicts_win_over_trajectory_verdicts(tmp_path: Path) -> None:
    """Falha repetida é sinal sobre a EXECUÇÃO do loop; piora de trajetória é
    sinal sobre o ARTEFATO. Os dois podem estourar juntos — o estrutural
    vence, mesma ordem que já vale para o transiente."""
    _write_feature_list_with_metric(
        tmp_path, typed=[{"type": "same_failure_signature", "n": 2}]
    )
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, ["a", "a"])
    _write_measurements(tmp_path, [0.9, 0.5, 0.4])  # também dispararia stop_worsening

    assert check_budget(tmp_path, "T-01")["verdict"] == "stop_same_failure"


def test_worsening_wins_over_plateau_when_both_trip(tmp_path: Path) -> None:
    """'piora antes de platô' (spec): quando as duas condições estouram
    juntas, o veredito reportado é o de piora."""
    _write_feature_list_with_metric(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, [0.9, 0.8, 0.7, 0.6])  # worsening=3, plateau=3

    assert check_budget(tmp_path, "T-01")["verdict"] == STOP_WORSENING


def test_metric_without_target_never_trips_trajectory_verdicts(tmp_path: Path) -> None:
    """Sem `metric_target` não há direção de 'melhor' — mesmo silêncio de
    uma tarefa sem métrica nenhuma (ver docstring de `convergence.py`)."""
    _write_feature_list_with_metric(tmp_path, metric_target=None)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, [0.9, 0.7, 0.6])  # dispararia stop_worsening se houvesse target

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == "continue"
    assert report["target_met"] is False


def test_feature_without_metric_cmd_has_target_met_false(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == "continue"
    assert report["target_met"] is False


def test_target_met_is_informational_and_never_changes_the_verdict(tmp_path: Path) -> None:
    """Anti-Goodhart do §4.3 como invariante: bater o alvo não é `passes`,
    nem sequer um veredito diferente — `verify_cmd` continua sendo quem
    decide. Aqui a medição mais recente bate o alvo E é o melhor valor (sem
    piora nem platô), então o veredito segue `continue` de qualquer jeito —
    o teste existe para o campo aparecer certo, não para provar isolamento."""
    _write_feature_list_with_metric(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, [0.5, 0.9])

    report = check_budget(tmp_path, "T-01")
    assert report["target_met"] is True
    assert report["verdict"] == "continue"


def test_stop_worsening_reason_names_the_best_state(tmp_path: Path) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, [0.9, 0.7, 0.6])

    reason = check_budget(tmp_path, "T-01")["reason"]
    assert "0.9" in reason
    assert "abc1234" in reason


def test_stop_plateau_reason_names_the_lack_of_a_new_record(tmp_path: Path) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, [0.9, 0.5, 0.9, 0.5, 0.9])

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == STOP_PLATEAU
    assert "platô" in report["reason"] or "recorde" in report["reason"]


def test_check_budget_still_writes_nothing_with_metric_configured(tmp_path: Path) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_yaml(tmp_path, 12)
    _write_trail(tmp_path, [])
    _write_measurements(tmp_path, [0.9, 0.7, 0.6])

    before = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}
    check_budget(tmp_path, "T-01")
    after = {p: p.read_bytes() for p in sorted(tmp_path.rglob("*")) if p.is_file()}

    assert before == after


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
