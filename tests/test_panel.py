"""Testes de `harness.panel` — o placar de andamento (contrato `placar-de-andamento`).

T-01: o `--brief` do chat. Um teste por REGRA, tabela de casos.

`panel.py` é render PURO: lê os arquivos de estado que outros módulos já
gravam (`feature_list.json`, `attempts/`, métrica, sentinela do kill-switch) e
nunca escreve, nunca roda `verify_cmd`, nunca chama git. Os testes montam o
estado em disco na mão — é exatamente o que o painel vai encontrar em produção.
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from harness.attempts import attempts_path
from harness.cli import main
from harness.convergence import metric_path
from harness.panel import collect_state, render_brief, render_terminal, watch

ANSI_ESCAPE = re.compile(r"\x1b\[")
ANSI_SEQUENCE = re.compile(r"\x1b\[[0-9;]*m")


def strip_ansi(text: str) -> str:
    return ANSI_SEQUENCE.sub("", text)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _feature(
    feature_id: str,
    desc: str,
    *,
    passes: bool = False,
    depends: list[str] | None = None,
    metric_cmd: str | None = None,
    metric_target: str | None = None,
) -> dict[str, Any]:
    feature: dict[str, Any] = {
        "id": feature_id,
        "desc": desc,
        "files": ["src/x.py"],
        "verify_cmd": f"pytest tests/test_{feature_id.lower()}.py -q",
        "depends": depends or [],
        "passes": passes,
    }
    if metric_cmd:
        feature["metric_cmd"] = metric_cmd
        feature["metric_target"] = metric_target
    return feature


def _write_contract(tmp_path: Path, features: list[dict[str, Any]], contract: str = "demo") -> None:
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps({"contract": contract, "features": features}, ensure_ascii=False),
    )


def _write_attempts(tmp_path: Path, feature_id: str, records: list[dict[str, Any]]) -> None:
    lines = [json.dumps(record, ensure_ascii=False) for record in records]
    _write(attempts_path(tmp_path, "demo", feature_id), "\n".join(lines) + "\n")


def _fail(line: str, *, classification: str = "structural") -> dict[str, Any]:
    return {
        "result": "fail",
        "recorded_at": "2026-08-10T00:00:00Z",
        "verify_cmd": "pytest -q",
        "exit_code": 1,
        "failure_line": line,
        "failure_signature": "deadbeefcafe",
        "files_hash": "h",
        "classification": classification,
    }


# ---------------------------------------------------------------------------
# REGRA 1 — o placar é derivado do disco: progresso, estado por tarefa e a
# tarefa atual saem do `feature_list.json`, não de quem está narrando
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProgressCase:
    passes: list[bool]
    expect_done: int
    expect_total: int
    expect_current: str | None
    why: str


PROGRESS_CASES = [
    ProgressCase([False, False, False], 0, 3, "T-01", "nada pronto: a atual é a primeira"),
    ProgressCase([True, False, False], 1, 3, "T-02", "uma pronta: a atual é a seguinte"),
    ProgressCase([True, True, True], 3, 3, None, "tudo pronto: não há tarefa atual"),
    ProgressCase([True, False, True], 2, 3, "T-02", "buraco no meio: a atual é a que falta"),
]


@pytest.mark.parametrize("case", PROGRESS_CASES, ids=lambda c: c.why)
def test_progress_and_current_task_come_from_the_contract_on_disk(
    tmp_path: Path, case: ProgressCase
) -> None:
    _write_contract(
        tmp_path,
        [
            _feature(f"T-0{i + 1}", f"tarefa {i + 1}", passes=passes)
            for i, passes in enumerate(case.passes)
        ],
    )

    state = collect_state(tmp_path)

    assert state["done"] == case.expect_done
    assert state["total"] == case.expect_total
    assert (state["current"] or {}).get("id") == case.expect_current


def test_task_state_marks_done_current_blocked_and_pending(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        [
            _feature("T-01", "pronta", passes=True),
            _feature("T-02", "em andamento"),
            _feature("T-03", "livre"),
            _feature("T-04", "travada", depends=["T-02"]),
        ],
    )

    state = collect_state(tmp_path)
    by_id = {f["id"]: f["state"] for f in state["features"]}

    assert by_id == {
        "T-01": "done",
        "T-02": "current",
        "T-03": "pending",
        "T-04": "blocked",
    }


def test_collect_state_without_contract_reports_nothing_instead_of_raising(tmp_path: Path) -> None:
    state = collect_state(tmp_path)

    assert state["contract"] is None
    assert state["total"] == 0
    assert state["current"] is None
    assert state["next_step"]


# ---------------------------------------------------------------------------
# REGRA 2 — a última prova aparece com o erro CRU e a tentativa com o teto do
# disjuntor; nenhum resumo escrito pelo painel
# ---------------------------------------------------------------------------

def test_last_failed_proof_shows_the_raw_error_line_and_attempt_against_the_ceiling(
    tmp_path: Path,
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa única")])
    _write_attempts(
        tmp_path,
        "T-01",
        [_fail("E   AssertionError: assert 3 == 4"), _fail("E   AssertionError: assert 3 == 4")],
    )

    state = collect_state(tmp_path)

    assert state["last_proof"]["result"] == "fail"
    assert state["last_proof"]["failure_line"] == "E   AssertionError: assert 3 == 4"
    # duas falhas registradas -> a próxima é a 3ª tentativa, contra o teto.
    assert state["current"]["attempt"] == 3
    assert state["current"]["limit"] >= 1
    assert "AssertionError" in render_brief(state)


def test_green_proof_reports_pass_without_a_failure_line(tmp_path: Path) -> None:
    _write_contract(tmp_path, [_feature("T-01", "primeira"), _feature("T-02", "segunda")])
    _write_attempts(
        tmp_path,
        "T-01",
        [_fail("E   AssertionError: x"), {"result": "pass", "recorded_at": "t", "files_hash": "h"}],
    )

    state = collect_state(tmp_path)

    assert state["last_proof"]["result"] == "pass"
    assert state["last_proof"]["failure_line"] is None
    # verde encerra a sequência: a contagem de tentativas recomeça.
    assert state["current"]["attempt"] == 1


@dataclass(frozen=True)
class NextStepCase:
    records: list[dict[str, Any]]
    all_done: bool
    expect_fragment: str
    why: str


NEXT_STEP_CASES = [
    NextStepCase([], False, "pytest", "sem tentativa: rodar a prova da tarefa"),
    NextStepCase([_fail("E   AssertionError: x")], False, "corrigir", "prova vermelha: corrigir e re-rodar"),
    NextStepCase([], True, "finish", "tudo pronto: encerrar a demanda"),
]


@pytest.mark.parametrize("case", NEXT_STEP_CASES, ids=lambda c: c.why)
def test_next_step_is_derived_from_the_state_not_narrated(
    tmp_path: Path, case: NextStepCase
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa", passes=case.all_done)])
    if case.records:
        _write_attempts(tmp_path, "T-01", case.records)

    state = collect_state(tmp_path)

    assert case.expect_fragment in state["next_step"].lower()


def test_kill_switch_disabled_takes_over_the_next_step(tmp_path: Path) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa")])
    _write(
        tmp_path / ".harness" / "harness.disabled",
        json.dumps({"disabled_at": "2026-08-10T00:00:00Z", "note": "debug"}),
    )

    state = collect_state(tmp_path)

    assert state["disabled"] is True
    assert "enable" in state["next_step"]
    assert "desativado" in render_brief(state).lower()


# ---------------------------------------------------------------------------
# REGRA 3 — a linha da métrica só existe quando há rastro de métrica
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MetricCase:
    metric_cmd: str | None
    values: list[float]
    expect_line: bool
    why: str


METRIC_CASES = [
    MetricCase(None, [], False, "tarefa sem metric_cmd: linha não aparece"),
    MetricCase("cov", [], False, "com metric_cmd e sem rastro: linha não aparece"),
    MetricCase("cov", [0.7, 0.8, 0.75], True, "com rastro: linha aparece"),
]


@pytest.mark.parametrize("case", METRIC_CASES, ids=lambda c: c.why)
def test_metric_line_appears_only_with_a_trajectory_on_disk(
    tmp_path: Path, case: MetricCase
) -> None:
    _write_contract(
        tmp_path,
        [_feature("T-01", "tarefa", metric_cmd=case.metric_cmd, metric_target=">= 0.9")],
    )
    if case.values:
        _write(
            metric_path(tmp_path, "demo", "T-01"),
            "\n".join(
                json.dumps({"value": v, "recorded_at": "t", "commit": "abc", "dirty": False})
                for v in case.values
            )
            + "\n",
        )

    state = collect_state(tmp_path)
    brief = render_brief(state)

    if not case.expect_line:
        assert state["metric"] is None
        assert "melhor" not in brief.lower()
    else:
        assert [m["value"] for m in state["metric"]["series"]] == case.values
        assert state["metric"]["best"]["value"] == 0.8
        assert state["metric"]["target"] == ">= 0.9"
        assert "0.8" in brief
        assert ">= 0.9" in brief


# ---------------------------------------------------------------------------
# REGRA 4 — o `--brief` é markdown+unicode para o chat: nunca ANSI, e traz as
# quatro respostas (onde estou, o que faço, como vai, o que vem)
# ---------------------------------------------------------------------------

def test_brief_answers_the_four_questions_without_ansi(tmp_path: Path) -> None:
    _write_contract(
        tmp_path,
        [
            _feature("T-01", "primeira tarefa pronta", passes=True),
            _feature("T-02", "escrever o placar do chat"),
            _feature("T-03", "colorir o terminal"),
        ],
    )
    _write_attempts(tmp_path, "T-02", [_fail("E   ImportError: no module named panel")])

    brief = render_brief(collect_state(tmp_path))

    assert ANSI_ESCAPE.search(brief) is None      # o chat não renderiza ANSI
    assert "1/3" in brief                          # onde estou
    assert "escrever o placar do chat" in brief    # o que está sendo feito
    assert "ImportError" in brief                  # como está indo
    assert "T-01" in brief and "T-03" in brief     # a lista inteira
    assert brief.strip().splitlines()[0].startswith("#")  # bloco markdown colável


# ---------------------------------------------------------------------------
# REGRA 5 — `harness status` sem flag continua sendo o JSON estruturado de
# hoje; o placar é opt-in
# ---------------------------------------------------------------------------

def _run_cli(argv: list[str], monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc_info:
        main()
    return int(exc_info.value.code or 0)


def test_status_without_flag_still_prints_the_structured_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa")])
    _write(tmp_path / ".harness" / "harness.yaml", "governance:\n  approval_policy: balanced\n")

    code = _run_cli(["harness", "status", "--dir", str(tmp_path)], monkeypatch)

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["disabled"] is False
    assert "sentinel" in payload and "friction" in payload


def test_status_brief_prints_the_panel_instead_of_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa do placar")])

    code = _run_cli(["harness", "status", "--dir", str(tmp_path), "--brief"], monkeypatch)

    out = capsys.readouterr().out
    assert code == 0
    assert "tarefa do placar" in out
    assert ANSI_ESCAPE.search(out) is None
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_brief_and_panel_together_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa")])

    code = _run_cli(
        ["harness", "status", "--dir", str(tmp_path), "--brief", "--panel"], monkeypatch
    )

    assert code == 2


# ---------------------------------------------------------------------------
# T-02
# REGRA 6 — cor é para quem está olhando um terminal: ANSI só quando a saída
# é um TTY; em pipe/arquivo sai texto puro
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ColorCase:
    color: bool
    expect_ansi: bool
    why: str


COLOR_CASES = [
    ColorCase(False, False, "sem cor: texto puro"),
    ColorCase(True, True, "com cor: escape codes ANSI"),
]


@pytest.mark.parametrize("case", COLOR_CASES, ids=lambda c: c.why)
def test_terminal_render_emits_ansi_only_when_color_is_asked(
    tmp_path: Path, case: ColorCase
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "pronta", passes=True), _feature("T-02", "atual")])
    _write_attempts(tmp_path, "T-02", [_fail("E   AssertionError: falhou")])

    rendered = render_terminal(collect_state(tmp_path), color=case.color)

    assert bool(ANSI_ESCAPE.search(rendered)) is case.expect_ansi
    # A cor é decoração: o texto sem escape code é o MESMO nos dois modos —
    # senão o placar diria coisas diferentes conforme o destino da saída.
    assert strip_ansi(rendered) == render_terminal(collect_state(tmp_path), color=False)


@dataclass(frozen=True)
class TtyCase:
    isatty: bool
    expect_ansi: bool
    why: str


TTY_CASES = [
    TtyCase(False, False, "stdout em pipe: sem ANSI"),
    TtyCase(True, True, "stdout em TTY: com ANSI"),
]


@pytest.mark.parametrize("case", TTY_CASES, ids=lambda c: c.why)
def test_status_panel_decides_color_by_looking_at_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    case: TtyCase,
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa do painel")])
    monkeypatch.setattr(sys.stdout, "isatty", lambda: case.isatty, raising=False)

    code = _run_cli(["harness", "status", "--dir", str(tmp_path), "--panel"], monkeypatch)

    out = capsys.readouterr().out
    assert code == 0
    assert "tarefa do painel" in strip_ansi(out)
    assert bool(ANSI_ESCAPE.search(out)) is case.expect_ansi


def test_panel_render_has_no_markdown_syntax_left_over(tmp_path: Path) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa")])

    rendered = render_terminal(collect_state(tmp_path), color=False)

    assert "**" not in rendered
    assert "`" not in rendered


# ---------------------------------------------------------------------------
# REGRA 7 — `--watch N` re-renderiza no intervalo pedido, no terminal do DEV:
# um loop de render, nunca um processo residente
# ---------------------------------------------------------------------------

def test_watch_rerenders_at_the_requested_interval(tmp_path: Path) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa observada")])
    slept: list[float] = []
    chunks: list[str] = []

    class _Stream:
        def write(self, text: str) -> None:
            chunks.append(text)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    watch(tmp_path, 5, stream=_Stream(), iterations=3, sleep=slept.append)

    rendered = "".join(chunks)
    assert rendered.count("tarefa observada") == 3
    # Dorme ENTRE renders, não depois do último: o comando termina na hora.
    assert slept == [5, 5]


def test_watch_reflects_state_that_changed_between_renders(tmp_path: Path) -> None:
    _write_contract(tmp_path, [_feature("T-01", "primeira"), _feature("T-02", "segunda")])
    chunks: list[str] = []

    class _Stream:
        def write(self, text: str) -> None:
            chunks.append(text)

        def flush(self) -> None:
            pass

        def isatty(self) -> bool:
            return False

    def _advance(_seconds: float) -> None:
        _write_contract(
            tmp_path,
            [_feature("T-01", "primeira", passes=True), _feature("T-02", "segunda")],
        )

    watch(tmp_path, 1, stream=_Stream(), iterations=2, sleep=_advance)

    first, second = "".join(chunks).split("Placar")[1:3]
    assert "0/2" in first
    assert "1/2" in second


@dataclass(frozen=True)
class WatchArgCase:
    argv_extra: list[str]
    expect_code: int
    why: str


WATCH_ARG_CASES = [
    WatchArgCase(["--watch", "0"], 2, "intervalo zero não é intervalo"),
    WatchArgCase(["--watch", "-3"], 2, "intervalo negativo não é intervalo"),
    WatchArgCase(["--brief", "--watch", "2"], 2, "o chat não se auto-atualiza: --brief com --watch é erro"),
]


@pytest.mark.parametrize("case", WATCH_ARG_CASES, ids=lambda c: c.why)
def test_watch_rejects_arguments_that_cannot_mean_anything(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: WatchArgCase
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa")])

    code = _run_cli(
        ["harness", "status", "--dir", str(tmp_path), *case.argv_extra], monkeypatch
    )

    assert code == 2


def test_watch_implies_panel_and_never_prints_the_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_contract(tmp_path, [_feature("T-01", "tarefa observada")])
    calls: dict[str, Any] = {}

    def _fake_watch(target_dir: Any, interval: int, **kwargs: Any) -> None:
        calls["interval"] = interval
        calls["target_dir"] = Path(target_dir)

    monkeypatch.setattr("harness.panel.watch", _fake_watch)

    code = _run_cli(["harness", "status", "--dir", str(tmp_path), "--watch", "7"], monkeypatch)

    assert code == 0
    assert calls["interval"] == 7
    assert capsys.readouterr().out == ""
