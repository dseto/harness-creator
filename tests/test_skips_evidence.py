"""T-06: a prova gravada em `.harness/evidence/` registra o que pulou —
quem abrir a evidência semanas depois vê a mesma coisa que quem rodou viu.

Silêncio-no-verde pelo mesmo motivo do resto do módulo: sem skip e sem
"zero coletados", a chave `skips` nem aparece — não muda o schema de quem já
lê evidência hoje sobre uma passada limpa (ver `test_verify.py::
test_run_verify_success_writes_evidence_with_correct_schema`, que continua
batendo a lista EXATA de chaves)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from harness.verify import run_verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(tmp_path: Path, features: list[dict], contract: str = "exemplo-evidencia") -> None:
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


def test_evidence_without_any_skip_has_no_skips_key(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "ok.py", "5 passed in 0.02s\n", 0))

    path = run_verify(tmp_path, "T-01")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "skips" not in data


def test_evidence_with_visible_reasons_records_the_skipped_items(tmp_path: Path) -> None:
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: feature disabled by product decision\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))
    from harness.skips import SkippedTest, write_baseline

    write_baseline(
        tmp_path, "exemplo-evidencia", "T-01",
        [SkippedTest(nodeid="tests/test_s.py:8", reason="feature disabled by product decision")],
    )

    path = run_verify(tmp_path, "T-01")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["skips"]["count"] == 1
    assert data["skips"]["zero_collected"] is False
    assert data["skips"]["items"] == [{"nodeid": "tests/test_s.py:8", "reason": "feature disabled by product decision"}]
    assert "truncated" not in data["skips"]


def test_evidence_without_baseline_never_reaches_the_write_it_blocks_first(tmp_path: Path) -> None:
    """Sem baseline, T-04 bloqueia antes de qualquer evidência ser gravada —
    a fixture acima só chega ao verde porque baselineou primeiro. Este teste
    documenta a ordem: T-06 só entra em jogo depois que T-04/T-05 já
    deixaram passar."""
    stdout = "SKIPPED [1] tests/test_s.py:8: feature disabled by product decision\n1 passed, 1 skipped in 0.02s\n"
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))
    from harness.verify import VerifyFailedError, evidence_path
    import pytest

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")
    assert not evidence_path(tmp_path, "exemplo-evidencia", "T-01").is_file()


def test_evidence_zero_collected_records_it_with_no_items(tmp_path: Path) -> None:
    _feature(tmp_path, _script_cmd(tmp_path, "zero.py", "No tests found, exiting with code 1\n", 0))

    path = run_verify(tmp_path, "T-01")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["skips"] == {"count": 0, "zero_collected": True, "items": []}


def test_evidence_caps_the_item_list_and_marks_truncation(tmp_path: Path) -> None:
    lines = ["short test summary info"]
    for i in range(30):
        lines.append(f"SKIPPED [1] tests/test_s.py:{i}: feature disabled by product decision")
    lines.append("1 passed, 30 skipped in 0.02s")
    stdout = "\n".join(lines) + "\n"
    _feature(tmp_path, _script_cmd(tmp_path, "many.py", stdout, 0))
    from harness.skips import SkippedTest, write_baseline

    write_baseline(
        tmp_path, "exemplo-evidencia", "T-01",
        [SkippedTest(nodeid=f"tests/test_s.py:{i}", reason="feature disabled by product decision") for i in range(30)],
    )

    path = run_verify(tmp_path, "T-01")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["skips"]["count"] == 30
    assert len(data["skips"]["items"]) < 30
    assert data["skips"]["truncated"] is True


def test_evidence_with_no_visible_reasons_never_reaches_the_write_it_blocks_first(tmp_path: Path) -> None:
    """Motivo invisível bloqueia sempre (T-05/T-04) — evidência com `items`
    vazio "porque não dava para saber" nunca chega a ser gravada de verdade;
    o comportamento correto é o vermelho, não uma evidência capenga."""
    _feature(tmp_path, _script_cmd(tmp_path, "skipq.py", "1 passed, 2 skipped in 0.02s\n", 0))
    from harness.verify import VerifyFailedError, evidence_path
    import pytest

    with pytest.raises(VerifyFailedError):
        run_verify(tmp_path, "T-01")
    assert not evidence_path(tmp_path, "exemplo-evidencia", "T-01").is_file()
