"""`harness skips baseline` (T-03): comando explícito que roda o
`verify_cmd` de uma feature, mostra ao humano o que pulou, e grava o
conjunto conhecido. `harness verify` NUNCA escreve baseline sozinho —
decisão registrada no spec (o primeiro verify virando baseline carimbaria
como conhecido justamente o skip que apareceu no meio do processo)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from harness.skips import BaselineError, SkippedTest, baseline_path, read_baseline, run_baseline
from harness.verify import run_verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(tmp_path: Path, features: list[dict], contract: str = "exemplo-baseline") -> None:
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


def test_run_baseline_with_visible_reasons_writes_the_known_set(tmp_path: Path) -> None:
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: env HARNESS_X not set\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))

    report, path = run_baseline(tmp_path, "T-01")

    assert report.skipped_count == 1
    assert path == baseline_path(tmp_path, "exemplo-baseline", "T-01")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved == [{"nodeid": "tests/test_s.py:8", "reason": "env HARNESS_X not set"}]

    known = read_baseline(tmp_path, "exemplo-baseline", "T-01")
    assert known == [SkippedTest(nodeid="tests/test_s.py:8", reason="env HARNESS_X not set")]


def test_run_baseline_with_no_skips_writes_an_empty_known_set(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "ok.py", "5 passed in 0.02s\n", 0))

    report, path = run_baseline(tmp_path, "T-01")

    assert report.skipped_count == 0
    assert json.loads(path.read_text(encoding="utf-8")) == []


def test_run_baseline_refuses_when_reasons_are_not_visible(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "skipq.py", "1 passed, 2 skipped in 0.02s\n", 0))

    with pytest.raises(BaselineError, match="-rs"):
        run_baseline(tmp_path, "T-01")

    assert not baseline_path(tmp_path, "exemplo-baseline", "T-01").is_file()


def test_run_baseline_never_runs_a_runtime_floor_command(tmp_path: Path) -> None:
    _feature(tmp_path, "git push origin main")

    with pytest.raises(BaselineError, match="floor"):
        run_baseline(tmp_path, "T-01")


def test_read_baseline_of_a_feature_never_baselined_is_empty(tmp_path: Path) -> None:
    assert read_baseline(tmp_path, "exemplo-baseline", "T-99") == []


def test_run_verify_never_writes_a_baseline_on_its_own(tmp_path: Path) -> None:
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: env HARNESS_X not set\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))

    # Sem baseline prévio, o skip é NOVO e o delta (T-04) bloqueia o verify —
    # o que este teste prova é que, mesmo assim, run_verify não grava
    # baseline sozinho: quem grava é só `harness skips baseline`.
    with pytest.raises(Exception):
        run_verify(tmp_path, "T-01")

    assert not baseline_path(tmp_path, "exemplo-baseline", "T-01").is_file()


def test_cli_skips_baseline_runs_end_to_end(tmp_path: Path) -> None:
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: env HARNESS_X not set\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))

    repo_src = Path(__file__).resolve().parent.parent / "src"
    proc = subprocess.run(
        [sys.executable, "-m", "harness.cli", "skips", "baseline", "--dir", str(tmp_path), "T-01"],
        cwd=repo_src, capture_output=True, text=True,
    )

    assert proc.returncode == 0, proc.stderr
    assert "env HARNESS_X not set" in proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["skipped_count"] == 1
    assert Path(payload["baseline"]).is_file()
