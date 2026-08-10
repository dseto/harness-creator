"""T-05: skip pulado por falta de algo do lado de fora do código (variável
de ambiente, credencial, ferramenta) bloqueia `harness verify` já na
PRIMEIRA execução, sem esperar delta, com veredito INFRA — mesma família de
`governance_stale`. Liberação em `.harness/harness.yaml`
(`verification.allowed_skips`) destrava de vez, sem precisar entrar no
baseline por feature."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.attempts import read_attempts
from harness.skips import (
    SkippedTest,
    SkipReport,
    actionable_skip_violation,
    is_actionable_skip_reason,
    load_allowed_skips,
    without_liberated_actionable_skips,
)
from harness.verify import VerifyError, VerifyFailedError, evidence_path, run_verify


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_feature_list(tmp_path: Path, features: list[dict], contract: str = "exemplo-acionavel") -> None:
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


class Case:
    def __init__(self, id: str, reason: str, expect_actionable: bool) -> None:
        self.id = id
        self.reason = reason
        self.expect_actionable = expect_actionable

    def __repr__(self) -> str:
        return self.id


CASES = [
    Case("env var em ingles", "env HARNESS_X not set", True),
    Case("nao definida em portugues", "variavel HARNESS_X nao definida", True),
    Case("not installed", "docker not installed", True),
    Case("not found", "fixture externa not found", True),
    # Caso real deste repositório (tests/test_integration_minimumapi.py:27).
    Case("nao encontrada em portugues", "fixture externa C:\\Projetos\\MinimumAPI nao encontrada nesta maquina", True),
    Case("credential", "missing AWS credential", True),
    Case("missing generico", "missing dependency xyz", True),
    Case("path ausente", "path ausente: /opt/tool", True),
    # Caso real deste repositório (tests/test_verify.py:663) — plataforma,
    # NÃO acionável: nenhuma palavra do classificador aparece no texto.
    Case("plataforma", "normalizacao so se aplica ao cmd.exe", False),
    Case("decisao de produto", "feature disabled by product decision", False),
    Case("motivo vazio", "", False),
]


def test_is_actionable_skip_reason_table() -> None:
    for case in CASES:
        got = is_actionable_skip_reason(case.reason)
        assert got == case.expect_actionable, f"{case.id}: esperado {case.expect_actionable}, veio {got}"


def test_actionable_skip_violation_blocks_unliberated_and_ignores_liberated() -> None:
    skip = SkippedTest(nodeid="tests/test_s.py:8", reason="env HARNESS_X not set")
    report = SkipReport(skipped_count=1, skipped=[skip], zero_collected=False, reasons_visible=True)

    assert actionable_skip_violation(report, allowed=[]) is not None
    assert actionable_skip_violation(report, allowed=["HARNESS_X not set"]) is None


def test_actionable_skip_violation_ignores_non_actionable_skips() -> None:
    skip = SkippedTest(nodeid="tests/test_s.py:8", reason="feature disabled by product decision")
    report = SkipReport(skipped_count=1, skipped=[skip], zero_collected=False, reasons_visible=True)

    assert actionable_skip_violation(report, allowed=[]) is None


def test_actionable_skip_violation_is_silent_when_reasons_are_not_visible() -> None:
    """Sem `-rs`/equivalente não há texto para classificar — T-02/T-04 já
    cobrem esse caso pedindo a mesma flag; T-05 não duplica o aviso."""
    report = SkipReport(skipped_count=2, skipped=[], zero_collected=False, reasons_visible=False)

    assert actionable_skip_violation(report, allowed=[]) is None


def test_without_liberated_actionable_skips_removes_only_the_liberated_ones() -> None:
    liberated = SkippedTest(nodeid="a.py:1", reason="env HARNESS_X not set")
    kept = SkippedTest(nodeid="b.py:2", reason="feature disabled by product decision")
    report = SkipReport(skipped_count=2, skipped=[liberated, kept], zero_collected=False, reasons_visible=True)

    result = without_liberated_actionable_skips(report, allowed=["HARNESS_X not set"])

    assert result.skipped == [kept]
    assert result.skipped_count == 1


def test_load_allowed_skips_missing_harness_yaml_is_empty(tmp_path: Path) -> None:
    assert load_allowed_skips(tmp_path) == []


def test_load_allowed_skips_reads_verification_allowed_skips(tmp_path: Path) -> None:
    _write(
        tmp_path / ".harness" / "harness.yaml",
        "verification:\n  allowed_skips:\n    - HARNESS_X not set\n    - nao encontrada\n",
    )

    assert load_allowed_skips(tmp_path) == ["HARNESS_X not set", "nao encontrada"]


def test_load_allowed_skips_invalid_yaml_degrades_to_empty(tmp_path: Path) -> None:
    _write(tmp_path / ".harness" / "harness.yaml", "verification: [not a mapping\n")

    assert load_allowed_skips(tmp_path) == []


def test_run_verify_blocks_an_actionable_skip_on_the_first_run_with_infra_verdict(tmp_path: Path) -> None:
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: env HARNESS_X not set\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))

    with pytest.raises(VerifyError) as excinfo:
        run_verify(tmp_path, "T-01")

    assert "HARNESS_X" in str(excinfo.value)
    # INFRA nunca entra no rastro de tentativas — não é falha estrutural,
    # "tentar de novo" não resolve env var ausente.
    assert read_attempts(tmp_path, "exemplo-acionavel", "T-01") == []
    assert not evidence_path(tmp_path, "exemplo-acionavel", "T-01").is_file()


def test_run_verify_never_raises_verify_failed_error_for_an_actionable_skip(tmp_path: Path) -> None:
    """INFRA (VerifyError) é uma classe de erro diferente de vermelho comum
    (VerifyFailedError) — quem lê run_verify precisa poder distinguir."""
    stdout = (
        "SKIPPED [1] tests/test_s.py:8: credential AWS_SECRET missing\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))

    with pytest.raises(VerifyError):
        try:
            run_verify(tmp_path, "T-01")
        except VerifyFailedError:
            pytest.fail("skip acionável não pode virar VerifyFailedError (vermelho comum)")


def test_run_verify_passes_when_the_actionable_skip_is_liberated_in_harness_yaml(tmp_path: Path) -> None:
    stdout = (
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: env HARNESS_X not set\n"
        "1 passed, 1 skipped in 0.02s\n"
    )
    _feature(tmp_path, _script_cmd(tmp_path, "skiprs.py", stdout, 0))
    _write(tmp_path / ".harness" / "harness.yaml", "verification:\n  allowed_skips:\n    - HARNESS_X not set\n")

    # Liberado destrava direto, SEM precisar também de baseline — decisão do
    # spec: os dois skips legítimos deste repositório se declaram uma vez.
    path = run_verify(tmp_path, "T-01")

    assert path.is_file()


def test_this_repository_own_legitimate_skips_are_not_actionable_or_are_liberatable() -> None:
    """Caso de teste real (spec, seção "casos de teste reais"): os dois skips
    legítimos DESTE repositório continuam passando depois de tudo isto.

    tests/test_verify.py:663 (skipif not is_windows) não bate o classificador
    — é sobre plataforma, não sobre ação do usuário. tests/test_integration_
    minimumapi.py:27 (fixture externa "nao encontrada") BATE o classificador
    de propósito — é o caso que prova que a liberação em harness.yaml
    funciona para uma frase real deste repositório.
    """
    platform_reason = "normalizacao so se aplica ao cmd.exe"
    fixture_reason = (
        "fixture externa C:\\Projetos\\MinimumAPI nao encontrada nesta maquina"
    )

    assert is_actionable_skip_reason(platform_reason) is False
    assert is_actionable_skip_reason(fixture_reason) is True

    report = SkipReport(
        skipped_count=1,
        skipped=[SkippedTest(nodeid="tests/test_integration_minimumapi.py:26", reason=fixture_reason)],
        zero_collected=False,
        reasons_visible=True,
    )
    assert actionable_skip_violation(report, allowed=[]) is not None
    assert actionable_skip_violation(report, allowed=["nao encontrada"]) is None
