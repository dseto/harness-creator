"""T-04: skip presente na execução e ausente do baseline derruba o verify,
pelo mesmo caminho do vermelho de hoje. Skip já no baseline passa mudo. Skip
que sumiu do baseline só informa, nunca bloqueia. Identidade = par
`(nodeid, reason)` — motivo diferente é skip diferente, mesmo no mesmo local."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.attempts import read_attempts
from harness.skips import SkippedTest, SkipReport, skip_delta_violation, write_baseline
from harness.verify import VerifyFailedError, evidence_path, run_verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(tmp_path: Path, features: list[dict], contract: str = "exemplo-delta") -> None:
    payload = {"contract": contract, "compiled_at": "2026-08-10T12:00:00+00:00", "features": features}
    _write(tmp_path / ".harness" / "feature_list.json", json.dumps(payload, ensure_ascii=False) + "\n")


def _script_cmd(tmp_path: Path, name: str, stdout: str, exit_code: int) -> str:
    script = tmp_path / name
    script.write_text(f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({exit_code})\n", encoding="utf-8")
    return f'"{sys.executable}" "{script}"'


def _feature(tmp_path: Path, verify_cmd: str, feature_id: str = "T-01") -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    _write_feature_list(
        tmp_path,
        [{"id": feature_id, "desc": "d", "files": ["src/x.py"], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )


#: Motivo deliberadamente NÃO acionável (nenhuma palavra do classificador de
#: T-05 — env/not set/credential/missing/etc.): T-04 testa o mecanismo de
#: DELTA, que precisa ficar decidível sem depender de liberação em
#: harness.yaml. O caso "motivo acionável" tem suíte própria em
#: tests/test_skips_actionable.py.
_SKIP_ONE = SkippedTest(nodeid="tests/test_s.py:8", reason="feature disabled by product decision")
_STDOUT_ONE_SKIP = (
    "=========================== short test summary info ===========================\n"
    "SKIPPED [1] tests/test_s.py:8: feature disabled by product decision\n"
    "1 passed, 1 skipped in 0.02s\n"
)


class Case:
    def __init__(self, id: str, report: SkipReport, known: list[SkippedTest], expect_violation: bool) -> None:
        self.id = id
        self.report = report
        self.known = known
        self.expect_violation = expect_violation

    def __repr__(self) -> str:
        return self.id


CASES = [
    Case("sem skip -> nunca bloqueia", SkipReport(skipped_count=0, skipped=[], zero_collected=False, reasons_visible=True), [], False),
    Case("skip conhecido -> passa mudo", SkipReport(skipped_count=1, skipped=[_SKIP_ONE], zero_collected=False, reasons_visible=True), [_SKIP_ONE], False),
    Case("skip novo, baseline vazio -> bloqueia", SkipReport(skipped_count=1, skipped=[_SKIP_ONE], zero_collected=False, reasons_visible=True), [], True),
    Case(
        "mesmo local, motivo mudou -> bloqueia (par muda)",
        SkipReport(skipped_count=1, skipped=[SkippedTest(nodeid="tests/test_s.py:8", reason="outro motivo")], zero_collected=False, reasons_visible=True),
        [_SKIP_ONE],
        True,
    ),
    Case(
        "skip do baseline sumiu -> só informa, não bloqueia",
        SkipReport(skipped_count=0, skipped=[], zero_collected=False, reasons_visible=True),
        [_SKIP_ONE],
        False,
    ),
    Case(
        "motivo invisível -> bloqueia mesmo sem poder comparar (assimetria: bloqueia a mais)",
        SkipReport(skipped_count=2, skipped=[], zero_collected=False, reasons_visible=False),
        [],
        True,
    ),
]


def test_skip_delta_violation_table() -> None:
    for case in CASES:
        got = skip_delta_violation(case.report, case.known)
        is_violation = got is not None
        assert is_violation == case.expect_violation, f"{case.id}: esperado violação={case.expect_violation}, veio {got!r}"


def test_run_verify_blocks_a_skip_new_that_is_absent_from_baseline(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", _STDOUT_ONE_SKIP, 0))

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    # Nada gravado em disco (mesmo caminho do vermelho de hoje).
    assert not evidence_path(tmp_path, "exemplo-delta", "T-01").is_file()
    # A tentativa em si É registrada — mesmo rastro de toda falha estrutural.
    attempts = read_attempts(tmp_path, "exemplo-delta", "T-01")
    assert attempts and attempts[-1]["result"] == "fail"
    assert attempts[-1]["classification"] == "structural"


def test_run_verify_passes_quietly_when_the_skip_is_already_known(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", _STDOUT_ONE_SKIP, 0))
    write_baseline(tmp_path, "exemplo-delta", "T-01", [_SKIP_ONE])

    path = run_verify(tmp_path, "T-01")

    assert path.is_file()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["exit_code"] == 0


def test_run_verify_does_not_block_when_a_known_skip_disappears(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "ok.py", "1 passed in 0.02s\n", 0))
    write_baseline(tmp_path, "exemplo-delta", "T-01", [_SKIP_ONE])

    path = run_verify(tmp_path, "T-01")

    assert path.is_file()
