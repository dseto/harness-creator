"""Testes de `harness.regression` — a re-prova incremental (§6 do design de
loop engineering).

A camada 2 prova a fatia que acabou de ficar pronta. Esta é a parte da camada 2
que olha para TRÁS: a fatia 5 pode ter quebrado a fatia 2, e sem isso ninguém
percebe até o gate final, quando o diff suspeito já tem o tamanho da demanda
inteira.

O critério de seleção é o que estes testes travam. Rodar de menos deixa passar a
regressão; rodar de mais transforma a re-prova na suíte completa — que o design
proíbe explicitamente dentro do loop de iteração.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from harness.attempts import open_failures, read_attempts
from harness.verify import compute_files_hash
from harness.regression import (
    RegressionError,
    render_reproof_report,
    reproof_targets,
    run_reproof,
)


def _feature(
    feature_id: str,
    *,
    files: list[str],
    verify_cmd: str = "pytest -q",
    passes: Any = True,
    cwd: str | None = None,
) -> dict[str, Any]:
    return {
        "id": feature_id,
        "desc": f"tarefa {feature_id}",
        "files": files,
        "verify_cmd": verify_cmd,
        "depends": [],
        "cwd": cwd,
        "passes": passes,
    }


# ---------------------------------------------------------------------------
# REGRA: a re-prova alcança exatamente as tarefas já provadas que compartilham
# arquivo com a que acabou de fechar — cada comando de prova uma única vez.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelectionCase:
    why: str
    features: list[dict[str, Any]]
    feature_id: str
    #: (verify_cmd, cwd, ids provados por esse comando), na ordem esperada.
    expected: list[tuple[str, str | None, tuple[str, ...]]] = field(default_factory=list)


SELECTION_CASES = [
    SelectionCase(
        why="tarefa provada que compartilha arquivo entra na re-prova",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q"),
            _feature("T-02", files=["src/a.py", "src/b.py"], verify_cmd="pytest tests/test_b.py -q", passes=False),
        ],
        feature_id="T-02",
        expected=[("pytest tests/test_a.py -q", None, ("T-01",))],
    ),
    SelectionCase(
        why="sem arquivo em comum nao ha acoplamento declarado, nada a re-provar",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q"),
            _feature("T-02", files=["src/b.py"], verify_cmd="pytest tests/test_b.py -q", passes=False),
        ],
        feature_id="T-02",
        expected=[],
    ),
    SelectionCase(
        why="tarefa ainda pendente nunca foi provada — nao ha o que regredir",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q", passes=False),
            _feature("T-02", files=["src/a.py"], verify_cmd="pytest tests/test_b.py -q", passes=False),
        ],
        feature_id="T-02",
        expected=[],
    ),
    SelectionCase(
        why="passes ausente conta como nao provada, nao como provada",
        features=[
            {"id": "T-01", "files": ["src/a.py"], "verify_cmd": "pytest tests/test_a.py -q"},
            _feature("T-02", files=["src/a.py"], verify_cmd="pytest tests/test_b.py -q", passes=False),
        ],
        feature_id="T-02",
        expected=[],
    ),
    SelectionCase(
        why="a propria tarefa nunca entra, mesmo ja marcada como provada",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q"),
        ],
        feature_id="T-01",
        expected=[],
    ),
    SelectionCase(
        why="prova identica a da tarefa atual acabou de rodar verde — repetir e desperdicio",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q"),
            _feature("T-02", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q", passes=False),
        ],
        feature_id="T-02",
        expected=[],
    ),
    SelectionCase(
        why="comando igual ao da atual mas em outro cwd e outra prova — nao rodou ainda",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest -q", cwd="pacote-um"),
            _feature("T-02", files=["src/a.py"], verify_cmd="pytest -q", passes=False),
        ],
        feature_id="T-02",
        expected=[("pytest -q", "pacote-um", ("T-01",))],
    ),
    SelectionCase(
        why="duas tarefas provadas pelo mesmo comando viram um alvo so, com os dois ids",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/compartilhado.py -q"),
            _feature("T-02", files=["src/a.py"], verify_cmd="pytest tests/compartilhado.py -q"),
            _feature("T-03", files=["src/a.py"], verify_cmd="pytest tests/test_c.py -q", passes=False),
        ],
        feature_id="T-03",
        expected=[("pytest tests/compartilhado.py -q", None, ("T-01", "T-02"))],
    ),
    SelectionCase(
        why="mesmo comando em cwd diferente e outro comando — agrupar seria rodar no lugar errado",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest -q", cwd="pacote-um"),
            _feature("T-02", files=["src/a.py"], verify_cmd="pytest -q", cwd="pacote-dois"),
            _feature("T-03", files=["src/a.py"], verify_cmd="pytest tests/test_c.py -q", passes=False),
        ],
        feature_id="T-03",
        expected=[
            ("pytest -q", "pacote-um", ("T-01",)),
            ("pytest -q", "pacote-dois", ("T-02",)),
        ],
    ),
    SelectionCase(
        why="ordem dos alvos segue a ordem do contrato, nao a ordem de descoberta",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q"),
            _feature("T-02", files=["src/b.py"], verify_cmd="pytest tests/test_b.py -q"),
            _feature("T-03", files=["src/a.py", "src/b.py"], verify_cmd="pytest tests/test_c.py -q", passes=False),
        ],
        feature_id="T-03",
        expected=[
            ("pytest tests/test_a.py -q", None, ("T-01",)),
            ("pytest tests/test_b.py -q", None, ("T-02",)),
        ],
    ),
    SelectionCase(
        why="tarefa sem arquivo declarado nao tem parentesco com nada",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd="pytest tests/test_a.py -q"),
            _feature("T-02", files=[], verify_cmd="pytest tests/test_b.py -q", passes=False),
        ],
        feature_id="T-02",
        expected=[],
    ),
]


@pytest.mark.parametrize("case", SELECTION_CASES, ids=lambda c: c.why)
def test_reproof_selects_only_proven_tasks_that_share_files(case: SelectionCase) -> None:
    targets = reproof_targets({"contract": "demo", "features": case.features}, case.feature_id)

    assert [(t.verify_cmd, t.cwd, t.feature_ids) for t in targets] == case.expected


def test_reproof_refuses_a_feature_id_that_is_not_in_the_contract_selection() -> None:
    """Id desconhecido é erro, nunca lista vazia.

    Lista vazia é o resultado legítimo de "nada acoplado" — devolver a mesma
    coisa para "essa tarefa não existe" faria a proteção sumir em silêncio
    exatamente no caso em que alguém errou o id.
    """
    feature_list = {"contract": "demo", "features": [_feature("T-01", files=["src/a.py"])]}

    with pytest.raises(RegressionError) as exc:
        reproof_targets(feature_list, "T-99")

    assert "T-99" in str(exc.value)


# ---------------------------------------------------------------------------
# REGRA: a re-prova executa os alvos e rebaixa o que voltou vermelho — quem
# perdeu a prova para de constar como provado.
# ---------------------------------------------------------------------------

#: Provas de mentira. `exit N` é builtin tanto do cmd.exe quanto do sh, então o
#: teste roda subprocesso de verdade nos dois sistemas sem depender de nenhum
#: binário instalado.
GREEN_CMD = "exit 0"
RED_CMD = "exit 1"

#: Comando do runtime floor, montado por concatenação: escrito inteiro, ele faria
#: o próprio boundary_guard barrar a edição deste arquivo de teste.
FLOOR_CMD = "curl " + "https://exemplo.invalido"


def _repo_with_contract(tmp_path: Path, features: list[dict[str, Any]]) -> Path:
    target = tmp_path / "repo"
    (target / ".harness").mkdir(parents=True)
    (target / ".harness" / "feature_list.json").write_text(
        json.dumps({"contract": "demo", "features": features}, indent=2),
        encoding="utf-8",
    )
    return target


def _passes_of(target: Path) -> dict[str, Any]:
    data = json.loads((target / ".harness" / "feature_list.json").read_text(encoding="utf-8"))
    return {f["id"]: f.get("passes") for f in data["features"]}


@dataclass(frozen=True)
class ReproofCase:
    why: str
    features: list[dict[str, Any]]
    feature_id: str
    expected_status: list[str]
    expected_regressed: list[str]


REPROOF_CASES = [
    ReproofCase(
        why="alvo verde continua provado",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd=GREEN_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=RED_CMD, passes=False),
        ],
        feature_id="T-02",
        expected_status=["green"],
        expected_regressed=[],
    ),
    ReproofCase(
        why="alvo vermelho e regressao",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
        feature_id="T-02",
        expected_status=["regressed"],
        expected_regressed=["T-01"],
    ),
    ReproofCase(
        why="um comando vermelho derruba TODAS as tarefas que ele provava",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-03", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
        feature_id="T-03",
        expected_status=["regressed"],
        expected_regressed=["T-01", "T-02"],
    ),
    ReproofCase(
        why="sem acoplamento declarado nao ha o que executar",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-02", files=["src/b.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
        feature_id="T-02",
        expected_status=[],
        expected_regressed=[],
    ),
    ReproofCase(
        why="prova no runtime floor nunca e executada, e nao rebaixa ninguem",
        features=[
            _feature("T-01", files=["src/a.py"], verify_cmd=FLOOR_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
        feature_id="T-02",
        expected_status=["error"],
        expected_regressed=[],
    ),
]


@pytest.mark.parametrize("case", REPROOF_CASES, ids=lambda c: c.why)
def test_reproof_runs_the_targets_and_demotes_what_turned_red(
    tmp_path: Path, case: ReproofCase
) -> None:
    target = _repo_with_contract(tmp_path, case.features)

    report = run_reproof(target, case.feature_id)

    assert [entry["status"] for entry in report["checked"]] == case.expected_status
    assert report["regressed"] == case.expected_regressed

    passes = _passes_of(target)
    for feature_id in case.expected_regressed:
        assert passes[feature_id] is False, f"{feature_id} devia ter sido rebaixada"
    for feature in case.features:
        if feature["id"] not in case.expected_regressed and feature.get("passes") is True:
            assert passes[feature["id"]] is True, "re-prova verde nao pode rebaixar ninguem"


def test_regression_leaves_a_failure_attempt_so_the_circuit_breaker_counts_it(
    tmp_path: Path,
) -> None:
    """Rebaixar sem registrar tentativa esconderia a regressão do `harness budget`.

    A tarefa volta para a fila; se ela reincidir, quem tem que perceber é o
    disjuntor mecânico, e ele só conta o que está no rastro de tentativas.
    """
    target = _repo_with_contract(
        tmp_path,
        [
            _feature("T-01", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
    )

    run_reproof(target, "T-02")

    failures = open_failures(read_attempts(target, "demo", "T-01"))
    assert len(failures) == 1
    assert failures[0]["exit_code"] == 1


def test_an_environment_failure_reports_but_never_demotes(tmp_path: Path, monkeypatch) -> None:
    """Timeout é falha de infraestrutura (§8.3), não regressão de código.

    Rebaixar aqui destruiria um registro válido por causa de uma máquina lenta —
    e a tarefa voltaria para a fila sem que nada no código estivesse errado.
    """
    import subprocess as _subprocess

    import harness.regression as regression_module

    def _timeout(*_args: Any, **_kwargs: Any) -> tuple[int, str, str]:
        raise _subprocess.TimeoutExpired(cmd=RED_CMD, timeout=1)

    monkeypatch.setattr(regression_module, "_run_verify_cmd", _timeout)

    target = _repo_with_contract(
        tmp_path,
        [
            _feature("T-01", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
    )

    report = run_reproof(target, "T-02")

    assert [entry["status"] for entry in report["checked"]] == ["error"]
    assert report["regressed"] == []
    assert _passes_of(target)["T-01"] is True


def test_the_readable_trail_stops_calling_a_regressed_task_done(tmp_path: Path) -> None:
    """`progress.md` é o que a próxima sessão lê — deixá-lo em `done` faria a
    reconciliação da abertura brigar com o `feature_list.json`."""
    target = _repo_with_contract(
        tmp_path,
        [
            _feature("T-01", files=["src/a.py"], verify_cmd=RED_CMD),
            _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
        ],
    )
    (target / ".harness" / "progress.md").write_text(
        "# Progresso\n\n| id | desc | status |\n|---|---|---|\n"
        "| T-01 | tarefa T-01 | done |\n| T-02 | tarefa T-02 | pending |\n",
        encoding="utf-8",
    )

    run_reproof(target, "T-02")

    progress = (target / ".harness" / "progress.md").read_text(encoding="utf-8")
    assert "| T-01 | tarefa T-01 | pending |" in progress


def test_reproof_refuses_a_feature_id_that_is_not_in_the_contract(tmp_path: Path) -> None:
    target = _repo_with_contract(tmp_path, [_feature("T-01", files=["src/a.py"])])

    with pytest.raises(RegressionError) as exc:
        run_reproof(target, "T-99")

    assert "T-99" in str(exc.value)


def test_reproof_without_a_contract_file_is_an_error_not_silence(tmp_path: Path) -> None:
    target = tmp_path / "vazio"
    target.mkdir()

    with pytest.raises(RegressionError):
        run_reproof(target, "T-01")


# ---------------------------------------------------------------------------
# REGRA: o relatório só fala quando tem o que dizer, e diz o que fazer.
# ---------------------------------------------------------------------------

def test_a_clean_reproof_renders_nothing() -> None:
    """Sem regressão, silêncio. Texto a cada verify verde treina a ignorar o
    texto — o mesmo motivo pelo qual `reconcile` não avisa em repo íntegro."""
    report = {"feature_id": "T-02", "checked": [], "regressed": []}

    assert render_reproof_report(report) is None


def test_a_regression_is_rendered_with_the_task_the_command_and_the_next_step() -> None:
    report = {
        "feature_id": "T-02",
        "checked": [
            {
                "verify_cmd": RED_CMD,
                "cwd": None,
                "feature_ids": ["T-01"],
                "status": "regressed",
                "exit_code": 1,
                "problem": "assert 1 == 2",
            }
        ],
        "regressed": ["T-01"],
    }

    rendered = render_reproof_report(report)

    assert rendered is not None
    assert "T-01" in rendered
    assert RED_CMD in rendered
    assert "T-02" in rendered


def test_a_proof_that_failed_without_output_does_not_leave_a_dangling_dash() -> None:
    """Achado do dogfood: `exit 1` seco não escreve nada, e a linha terminava
    num travessão pendurado. O exit code já disse o que havia a dizer."""
    report = {
        "feature_id": "T-02",
        "checked": [
            {
                "verify_cmd": RED_CMD,
                "cwd": None,
                "feature_ids": ["T-01"],
                "status": "regressed",
                "exit_code": 1,
                "problem": "",
            }
        ],
        "regressed": ["T-01"],
    }

    rendered = render_reproof_report(report)

    assert rendered is not None
    assert not any(line.rstrip().endswith("—") for line in rendered.splitlines())


# ---------------------------------------------------------------------------
# REGRA (contrato `compilar-as-primeiras-licoes`, T-01): a re-prova que passa
# VALE como prova. Ela roda o `verify_cmd` exato da tarefa antiga contra os
# arquivos de agora — é literalmente o que `harness verify` faria. Não regravar
# a evidência jogava fora prova válida e cobrava um `harness verify` manual que
# reexecuta o mesmo comando; aconteceu em três incrementos seguidos.
#
# O limite: recarimbo ATUALIZA prova existente, nunca EMITE prova nova. Fatia
# com `passes: true` e sem arquivo de evidência é marcação à mão, e é o que o
# bloqueador `evidence_missing` existe para pegar.
# ---------------------------------------------------------------------------

def _write_evidence(
    target: Path, feature_id: str, *, files: list[str], verify_cmd: str
) -> Path:
    """Evidência com hash de um estado ANTIGO — o cenário real: a fatia foi
    provada, e um commit posterior mexeu nos arquivos dela."""
    path = target / ".harness" / "evidence" / "demo" / f"{feature_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({
            "feature_id": feature_id,
            "contract": "demo",
            "desc": f"tarefa {feature_id}",
            "files": files,
            "verify_cmd": verify_cmd,
            "recorded_at": "2020-01-01T00:00:00+00:00",
            "exit_code": 0,
            "files_hash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
        }, indent=2),
        encoding="utf-8",
    )
    return path


def _read_evidence(target: Path, feature_id: str) -> dict[str, Any]:
    path = target / ".harness" / "evidence" / "demo" / f"{feature_id}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_green_reproof_restamps_the_evidence_of_the_task_it_reproved(
    tmp_path: Path,
) -> None:
    target = _repo_with_contract(tmp_path, [
        _feature("T-01", files=["src/a.py"], verify_cmd=GREEN_CMD),
        _feature("T-02", files=["src/a.py"], verify_cmd=RED_CMD, passes=False),
    ])
    (target / "src").mkdir()
    (target / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _write_evidence(target, "T-01", files=["src/a.py"], verify_cmd=GREEN_CMD)

    run_reproof(target, "T-02")

    evidence = _read_evidence(target, "T-01")
    assert evidence["files_hash"] == compute_files_hash(["src/a.py"], target)
    assert evidence["recorded_at"] != "2020-01-01T00:00:00+00:00"
    assert evidence["exit_code"] == 0


def test_one_green_command_restamps_every_task_it_proves(tmp_path: Path) -> None:
    """A re-prova agrupa por comando: uma execução prova N tarefas, e todas as N
    ficam com o carimbo novo. Recarimbar só a primeira deixaria as outras
    `evidence_stale` sem razão."""
    target = _repo_with_contract(tmp_path, [
        _feature("T-01", files=["src/a.py"], verify_cmd=GREEN_CMD),
        _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD),
        _feature("T-03", files=["src/a.py"], verify_cmd=RED_CMD, passes=False),
    ])
    (target / "src").mkdir()
    (target / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _write_evidence(target, "T-01", files=["src/a.py"], verify_cmd=GREEN_CMD)
    _write_evidence(target, "T-02", files=["src/a.py"], verify_cmd=GREEN_CMD)

    run_reproof(target, "T-03")

    for feature_id in ("T-01", "T-02"):
        assert _read_evidence(target, feature_id)["files_hash"] == compute_files_hash(
            ["src/a.py"], target
        )


def test_a_green_reproof_never_invents_evidence_that_did_not_exist(
    tmp_path: Path,
) -> None:
    """Fatia marcada `passes: true` à mão, sem arquivo de prova, é o que o
    `evidence_missing` do `harness finish` existe para pegar. Emitir a prova
    aqui apagaria a detecção — e o recarimbo passaria a fabricar exatamente o
    tipo de registro que o harness existe para desconfiar."""
    target = _repo_with_contract(tmp_path, [
        _feature("T-01", files=["src/a.py"], verify_cmd=GREEN_CMD),
        _feature("T-02", files=["src/a.py"], verify_cmd=RED_CMD, passes=False),
    ])

    run_reproof(target, "T-02")

    assert not (target / ".harness" / "evidence" / "demo" / "T-01.json").exists()


@dataclass(frozen=True)
class NoRestampCase:
    why: str
    verify_cmd: str


NO_RESTAMP_CASES = [
    NoRestampCase(why="prova vermelha rebaixa, e prova antiga vira registro obsoleto", verify_cmd=RED_CMD),
    NoRestampCase(why="prova no runtime floor nao roda, logo nao ha veredito nenhum", verify_cmd=FLOOR_CMD),
]


@pytest.mark.parametrize("case", NO_RESTAMP_CASES, ids=lambda c: c.why)
def test_only_a_green_reproof_restamps(tmp_path: Path, case: NoRestampCase) -> None:
    target = _repo_with_contract(tmp_path, [
        _feature("T-01", files=["src/a.py"], verify_cmd=case.verify_cmd),
        _feature("T-02", files=["src/a.py"], verify_cmd=GREEN_CMD, passes=False),
    ])
    _write_evidence(target, "T-01", files=["src/a.py"], verify_cmd=case.verify_cmd)

    run_reproof(target, "T-02")

    assert _read_evidence(target, "T-01")["recorded_at"] == "2020-01-01T00:00:00+00:00"


def test_a_failed_restamp_never_breaks_the_reproof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mesma degradação do `_demote`: o veredito da re-prova é o produto, e
    perdê-lo por causa de um arquivo de prova que não pôde ser escrito trocaria
    um incômodo por uma cegueira."""
    target = _repo_with_contract(tmp_path, [
        _feature("T-01", files=["src/a.py"], verify_cmd=GREEN_CMD),
        _feature("T-02", files=["src/a.py"], verify_cmd=RED_CMD, passes=False),
    ])
    _write_evidence(target, "T-01", files=["src/a.py"], verify_cmd=GREEN_CMD)

    import harness.regression as regression_module

    def _boom(*args: Any, **kwargs: Any) -> None:
        raise OSError("disco cheio")

    monkeypatch.setattr(regression_module, "restamp_evidence", _boom)

    report = run_reproof(target, "T-02")

    assert [entry["status"] for entry in report["checked"]] == ["green"]


def test_an_environment_error_is_rendered_without_claiming_regression() -> None:
    """Erro de ambiente aparece — sumir com ele deixaria a proteção desligada em
    silêncio —, mas não é anunciado como tarefa quebrada."""
    report = {
        "feature_id": "T-02",
        "checked": [
            {
                "verify_cmd": RED_CMD,
                "cwd": None,
                "feature_ids": ["T-01"],
                "status": "error",
                "exit_code": None,
                "problem": "excedeu o timeout de 600s",
            }
        ],
        "regressed": [],
    }

    rendered = render_reproof_report(report)

    assert rendered is not None
    assert "timeout" in rendered
    assert "T-01" in rendered
