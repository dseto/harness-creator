"""Testes de `harness.escalation` — o formato obrigatório de escalada do §8.

T-04 do contrato `falha-transiente-e-escalada`. `render_escalation` monta,
a partir de um `report` de `budget.check_budget`, um bloco com as SEIS partes
que a §8 exige, na ordem que ela exige. Um teste por REGRA, tabela de casos.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from harness.attempts import attempts_path, failure_signature
from harness.budget import STOP_PLATEAU, STOP_WORSENING, check_budget
from harness.convergence import metric_path
from harness.escalation import EscalationError, render_escalation


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)


def _write_feature_list(tmp_path: Path, contract: str = "exemplo", desc: str = "Fazer alguma coisa") -> None:
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(
            {
                "contract": contract,
                "stop_conditions": {"typed": [], "advisory": []},
                "features": [
                    {
                        "id": "T-01",
                        "desc": desc,
                        "files": ["src/x.py"],
                        "verify_cmd": "pytest -q",
                        "depends": [],
                        "passes": False,
                    }
                ],
            },
            indent=2,
            ensure_ascii=False,
        ),
    )


def _write_trail(tmp_path: Path, sequence: list[tuple[str, str]], contract: str = "exemplo") -> None:
    """`sequence` é uma lista de `(failure_line, classification)`."""
    lines = [
        json.dumps({
            "result": "fail", "contract": contract, "feature_id": "T-01",
            "recorded_at": "t", "verify_cmd": "pytest -q", "exit_code": 1,
            "failure_line": line, "failure_signature": failure_signature(line),
            "files_hash": "h", "classification": classification,
        })
        for line, classification in sequence
    ]
    _write(attempts_path(tmp_path, contract, "T-01"), "\n".join(lines) + ("\n" if lines else ""))


# ---------------------------------------------------------------------------
# REGRA 1 — as seis partes aparecem, nesta ordem, sempre que o veredito para
# ---------------------------------------------------------------------------

def test_escalation_has_the_six_sections_of_section_8_in_order(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, desc="Fechar a lacuna X")
    _write_trail(tmp_path, [("a", "structural"), ("a", "structural"), ("a", "structural")])

    report = check_budget(tmp_path, "T-01")
    text = render_escalation(tmp_path, report)

    order = [
        "O que estava sendo tentado",
        "O que foi tentado",
        "Último erro (cru)",
        "Classificação",
        "Estado da spine",
        "Sugestão de próximo passo",
    ]
    positions = [text.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_escalation_names_the_slice_and_its_proof(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, desc="Fechar a lacuna X")
    _write_trail(tmp_path, [("a", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))

    assert "Fechar a lacuna X" in text
    assert "pytest -q" in text


# ---------------------------------------------------------------------------
# REGRA 2 — a classificação reportada bate com o veredito do disjuntor
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ClassificationCase:
    sequence: list[tuple[str, str]]
    typed: list[dict]
    expect_label: str
    why: str


CLASSIFICATION_CASES = [
    ClassificationCase(
        [("a", "structural")] * 3, [], "estrutural no teto",
        "padrão repetido (stop_same_failure) rotula como estrutural",
    ),
    ClassificationCase(
        [("a", "structural"), ("b", "structural"), ("c", "structural"), ("d", "structural")],
        [{"type": "consecutive_verify_failures", "n": 4}], "estrutural no teto",
        "teto de iterações (stop_iterations) também rotula como estrutural",
    ),
    ClassificationCase(
        [("Connection refused", "transient")], [], "transiente esgotado",
        "esgotamento transiente rotula como transiente esgotado, não infra genérico",
    ),
]


@pytest.mark.parametrize("case", CLASSIFICATION_CASES, ids=lambda c: c.why)
def test_escalation_classification_label_matches_the_verdict(
    tmp_path: Path, case: ClassificationCase
) -> None:
    _write_feature_list(tmp_path)
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(
            {
                "contract": "exemplo",
                "stop_conditions": {"typed": case.typed, "advisory": []},
                "features": [{
                    "id": "T-01", "desc": "x", "files": [], "verify_cmd": "pytest -q",
                    "depends": [], "passes": False,
                }],
            },
            indent=2, ensure_ascii=False,
        ),
    )
    _write_trail(tmp_path, case.sequence)

    report = check_budget(tmp_path, "T-01")
    text = render_escalation(tmp_path, report)
    assert case.expect_label in text.split("Classificação:")[1].split("Estado da spine:")[0]


# ---------------------------------------------------------------------------
# REGRA 3 — o último erro cru vem exatamente como o disjuntor registrou
# ---------------------------------------------------------------------------

def test_escalation_carries_the_raw_last_error(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("E   assert 1 == 2", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    assert "E   assert 1 == 2" in text.split("Último erro (cru):")[1].split("Classificação:")[0]


def test_escalation_error_trail_lists_every_open_failure_in_order(tmp_path: Path) -> None:
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(
            {
                "contract": "exemplo",
                "stop_conditions": {"typed": [{"type": "consecutive_verify_failures", "n": 2}], "advisory": []},
                "features": [{
                    "id": "T-01", "desc": "x", "files": [], "verify_cmd": "pytest -q",
                    "depends": [], "passes": False,
                }],
            },
            indent=2, ensure_ascii=False,
        ),
    )
    _write_trail(tmp_path, [("primeira", "structural"), ("segunda", "structural")])

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    trail = text.split("O que foi tentado")[1].split("Último erro (cru):")[0]
    assert trail.index("primeira") < trail.index("segunda")


def test_escalation_error_trail_declares_intent_is_not_captured(tmp_path: Path) -> None:
    """O bloco de "abordagens" só tem o ERRO — a INTENÇÃO de cada tentativa
    não é gravada em lugar nenhum do harness, e o texto precisa dizer isso em
    vez de fingir que sabe."""
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    trail = text.split("O que foi tentado")[1].split("Último erro (cru):")[0]
    assert "intenç" in trail or "intencao" in trail.lower()


# ---------------------------------------------------------------------------
# REGRA 4 — a spine é lida do git de verdade (só-leitura)
# ---------------------------------------------------------------------------

def test_escalation_reports_clean_tree(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    spine = text.split("Estado da spine:")[1].split("Sugestão de próximo passo:")[0]
    assert "limpa" in spine


def test_escalation_reports_dirty_tree_with_the_files(tmp_path: Path) -> None:
    _write(tmp_path / "src" / "x.py", "x = 1\n")
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "T")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-m", "init")
    # `-uno` (mesmo escopo de `finish._tracked_dirty_paths`) não vê arquivo
    # NOVO e não rastreado — só modificação de algo já commitado.
    _write(tmp_path / "src" / "x.py", "x = 2\n")

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    spine = text.split("Estado da spine:")[1].split("Sugestão de próximo passo:")[0]
    assert "suja" in spine
    assert "src/x.py" in spine or "src\\x.py" in spine


def test_escalation_without_git_repo_names_the_absence(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    spine = text.split("Estado da spine:")[1].split("Sugestão de próximo passo:")[0]
    assert "git" in spine


# ---------------------------------------------------------------------------
# REGRA 5 — a sugestão de próximo passo é a razão que o disjuntor já produziu
# ---------------------------------------------------------------------------

def test_escalation_next_step_is_the_budget_reason(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)

    report = check_budget(tmp_path, "T-01")
    text = render_escalation(tmp_path, report)
    assert report["reason"] in text


# ---------------------------------------------------------------------------
# REGRA 6 — escalar um `continue` é erro, não texto vazio
# ---------------------------------------------------------------------------

def test_escalating_a_continue_verdict_raises(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [])

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == "continue"
    with pytest.raises(EscalationError):
        render_escalation(tmp_path, report)


# ---------------------------------------------------------------------------
# REGRA 7 — tarefa com métrica ganha a linha de trajetória no "Estado da
# spine" (§4.3, contrato `convergencia-opt-in`), e um rótulo de classificação
# próprio — nunca forçada em "estrutural no teto"
# ---------------------------------------------------------------------------

def _write_feature_list_with_metric(
    tmp_path: Path,
    metric_target: str = ">= 0.85",
    typed: list[dict] | None = None,
    contract: str = "exemplo",
) -> None:
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(
            {
                "contract": contract,
                "stop_conditions": {"typed": typed or [], "advisory": []},
                "features": [{
                    "id": "T-01", "desc": "Fechar a lacuna X", "files": ["src/x.py"],
                    "verify_cmd": "pytest -q", "metric_cmd": "python metric.py",
                    "metric_target": metric_target, "depends": [], "passes": False,
                }],
            },
            indent=2, ensure_ascii=False,
        ),
    )


def _write_measurements(tmp_path: Path, values: list[float], contract: str = "exemplo") -> None:
    lines = [
        json.dumps({"value": v, "recorded_at": f"2026-08-09T0{i}:00:00+00:00", "commit": f"c{i}", "dirty": False})
        for i, v in enumerate(values)
    ]
    _write(metric_path(tmp_path, contract, "T-01"), "\n".join(lines) + ("\n" if lines else ""))


def test_escalation_classification_label_for_worsening(tmp_path: Path) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_measurements(tmp_path, [0.9, 0.7, 0.6])

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == STOP_WORSENING
    text = render_escalation(tmp_path, report)
    assert "trajetória em piora" in text.split("Classificação:")[1].split("Estado da spine:")[0]


def test_escalation_classification_label_for_plateau(tmp_path: Path) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_measurements(tmp_path, [0.9, 0.5, 0.9, 0.5, 0.9])

    report = check_budget(tmp_path, "T-01")
    assert report["verdict"] == STOP_PLATEAU
    text = render_escalation(tmp_path, report)
    assert "trajetória em platô" in text.split("Classificação:")[1].split("Estado da spine:")[0]


def test_escalation_spine_gains_the_trajectory_line_with_recent_series_and_best(
    tmp_path: Path,
) -> None:
    _write_feature_list_with_metric(tmp_path)
    _write_measurements(tmp_path, [0.9, 0.7, 0.6])

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    spine = text.split("Estado da spine:")[1].split("Sugestão de próximo passo:")[0]
    assert "0.9" in spine and "0.7" in spine and "0.6" in spine
    assert "c0" in spine  # commit da medição que é o melhor valor (0.9, índice 0)


def test_escalation_spine_has_no_trajectory_line_without_metric(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    spine = text.split("Estado da spine:")[1].split("Sugestão de próximo passo:")[0]
    assert "Trajetória" not in spine


def test_escalation_spine_has_no_trajectory_line_without_any_measurement_yet(
    tmp_path: Path,
) -> None:
    """Tarefa com metric_cmd/metric_target declarados mas ainda sem nenhuma
    medição gravada (contrato recém-compilado) — mesmo silêncio de tarefa
    sem métrica, não uma linha vazia ou quebrada."""
    _write_feature_list_with_metric(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    spine = text.split("Estado da spine:")[1].split("Sugestão de próximo passo:")[0]
    assert "Trajetória" not in spine


# ---------------------------------------------------------------------------
# Contrato `placar-de-andamento`, T-05 — o canal humano fala RESULTADO
# ---------------------------------------------------------------------------

def test_escalation_opens_with_what_happened_in_plain_words(tmp_path: Path) -> None:
    """Quem lê a escalada precisa saber, na PRIMEIRA linha, o que aconteceu —
    antes das seis seções do §8, que são o dossiê. Sem a manchete, a leitura
    começa por "O que estava sendo tentado" e o resultado só aparece no fim."""
    _write_feature_list(tmp_path, desc="Fechar a lacuna X")
    _write_trail(tmp_path, [("E   AssertionError: 1 != 2", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))
    headline = text.strip().splitlines()[0]

    assert "PAROU" in headline
    assert "mesmo erro" in headline.lower()
    # A manchete vem ANTES do dossiê do §8, que continua inteiro logo abaixo.
    assert text.index(headline) < text.index("O que estava sendo tentado")


@dataclass(frozen=True)
class JargonCase:
    token: str
    why: str


JARGON_CASES = [
    JargonCase("stop_same_failure", "nome interno de veredito não é resultado"),
    JargonCase("stop_iterations", "nome interno de veredito não é resultado"),
    JargonCase("verify_cmd", "o humano não sabe o que é verify_cmd — é 'a prova'"),
    JargonCase("feature_list.json", "arquivo interno não diz nada a quem lê"),
]


@pytest.mark.parametrize("case", JARGON_CASES, ids=lambda c: c.token)
def test_escalation_never_shows_raw_mechanism_names_to_the_human(
    tmp_path: Path, case: JargonCase
) -> None:
    _write_feature_list(tmp_path, desc="Fechar a lacuna X")
    _write_trail(tmp_path, [("E   AssertionError: 1 != 2", "structural")] * 3)

    text = render_escalation(tmp_path, check_budget(tmp_path, "T-01"))

    assert case.token not in text


def test_escalating_a_feature_removed_from_the_contract_raises(tmp_path: Path) -> None:
    _write_feature_list(tmp_path)
    _write_trail(tmp_path, [("a", "structural")] * 3)
    report = check_budget(tmp_path, "T-01")

    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps({"contract": "exemplo", "features": []}, indent=2, ensure_ascii=False),
    )
    with pytest.raises(EscalationError, match="T-01"):
        render_escalation(tmp_path, report)
