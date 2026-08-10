"""`harness verify` relata skips em TODA execução, verde ou vermelho, sem
flag e sem opt-in (T-02). Usa um `verify_cmd` fabricado (`python -c ...`)
que imprime saída no formato que `harness.skips.parse_skips` reconhece —
não depende de uma suíte pytest real pulando testes de verdade."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.skips import SkippedTest, write_baseline
from harness.verify import VerifyFailedError, run_verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(tmp_path: Path, features: list[dict], contract: str = "exemplo-skips") -> None:
    payload = {"contract": contract, "compiled_at": "2026-08-10T12:00:00+00:00", "features": features}
    _write(tmp_path / ".harness" / "feature_list.json", json.dumps(payload, ensure_ascii=False) + "\n")


def _script_cmd(tmp_path: Path, name: str, stdout: str, exit_code: int) -> str:
    """Grava um script Python que imprime `stdout` e sai com `exit_code` —
    fica igual em qualquer shell (cmd.exe no Windows, sh no POSIX)."""
    script = tmp_path / name
    script.write_text(
        f"import sys\nsys.stdout.write({stdout!r})\nsys.exit({exit_code})\n", encoding="utf-8"
    )
    return f'"{sys.executable}" "{script}"'


def test_run_verify_success_with_no_skips_prints_no_skip_message(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    verify_cmd = _script_cmd(tmp_path, "ok.py", "5 passed in 0.02s\n", 0)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "d", "files": ["src/x.py"], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01")

    assert "pulado" not in capsys.readouterr().err


def test_run_verify_reports_skips_without_visible_reasons_before_the_delta_blocks(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sem `-rs`, o skip não tem identidade — o delta (T-04) bloqueia SEMPRE
    nesse caso, baseline ou não (assimetria intencional). O que T-02 promete
    — o relato acontece de qualquer forma, antes do bloqueio — continua
    valendo, e é o que este teste prova."""
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    verify_cmd = _script_cmd(tmp_path, "skipq.py", "1 passed, 2 skipped in 0.02s\n", 0)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "d", "files": ["src/x.py"], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    err = capsys.readouterr().err
    assert "2" in err and "pulado" in err
    assert "-rs" in err


def test_run_verify_success_with_a_known_skip_reports_it_and_stays_green(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: feature disabled by product decision\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    verify_cmd = _script_cmd(tmp_path, "skiprs.py", stdout, 0)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "d", "files": ["src/x.py"], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )
    write_baseline(
        tmp_path, "exemplo-skips", "T-01",
        [SkippedTest(nodeid="tests/test_s.py:8", reason="feature disabled by product decision")],
    )

    run_verify(tmp_path, "T-01")

    err = capsys.readouterr().err
    assert "feature disabled by product decision" in err


def test_run_verify_zero_collected_warns_even_on_exit_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    verify_cmd = _script_cmd(tmp_path, "zero.py", "No tests found, exiting with code 1\n", 0)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "d", "files": ["src/x.py"], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )

    run_verify(tmp_path, "T-01")

    err = capsys.readouterr().err
    assert "nenhum teste" in err.lower()


def test_run_verify_failure_also_reports_skips_before_raising(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "src" / "x.py", "print('hi')\n")
    stdout = "F.s                                                                      [100%]\n1 failed, 1 skipped in 0.02s\n"
    verify_cmd = _script_cmd(tmp_path, "failskip.py", stdout, 1)
    _write_feature_list(
        tmp_path,
        [{"id": "T-01", "desc": "d", "files": ["src/x.py"], "verify_cmd": verify_cmd, "depends": [], "passes": False}],
    )

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")

    err = capsys.readouterr().err
    assert "1" in err and "pulado" in err
