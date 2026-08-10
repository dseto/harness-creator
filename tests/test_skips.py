"""Parsing da saída de runners de teste: quantos testes pularam, por quê
quando o motivo aparece na saída, e se nenhum teste chegou a ser coletado.

Puro texto-em, texto-fora — nenhuma execução de processo aqui (isso é
`verify.py`, T-02). Cobre os quatro runners que o harness precisa reconhecer
hoje: pytest (Python, o próprio harness), dotnet test (dogfood .NET),
jest (Node) e go test.
"""

from __future__ import annotations

from harness.skips import SkippedTest, SkipReport, parse_skips


class Case:
    def __init__(self, id: str, stdout: str, stderr: str, expect: SkipReport) -> None:
        self.id = id
        self.stdout = stdout
        self.stderr = stderr
        self.expect = expect

    def __repr__(self) -> str:
        return self.id


PYTEST_QUIET_NO_SKIPS = Case(
    "pytest -q sem skip",
    stdout=".....                                                                    [100%]\n5 passed in 0.02s\n",
    stderr="",
    expect=SkipReport(skipped_count=0, skipped=[], zero_collected=False, reasons_visible=True),
)

PYTEST_QUIET_WITH_SKIPS_NO_REASONS = Case(
    "pytest -q com skip, sem -rs (motivo invisível)",
    stdout=".ss                                                                      [100%]\n1 passed, 2 skipped in 0.02s\n",
    stderr="",
    expect=SkipReport(
        skipped_count=2,
        skipped=[],
        zero_collected=False,
        reasons_visible=False,
    ),
)

PYTEST_RS_WITH_REASONS = Case(
    "pytest -q -rs com skip e motivo visível",
    stdout=(
        ".ss                                                                      [100%]\n"
        "=========================== short test summary info ===========================\n"
        "SKIPPED [1] tests/test_s.py:8: env HARNESS_X not set\n"
        "SKIPPED [1] tests/test_s.py:13: fixture externa nao encontrada\n"
        "1 passed, 2 skipped in 0.02s\n"
    ),
    stderr="",
    expect=SkipReport(
        skipped_count=2,
        skipped=[
            SkippedTest(nodeid="tests/test_s.py:8", reason="env HARNESS_X not set"),
            SkippedTest(nodeid="tests/test_s.py:13", reason="fixture externa nao encontrada"),
        ],
        zero_collected=False,
        reasons_visible=True,
    ),
)

PYTEST_NO_TESTS_RAN = Case(
    "pytest sem nenhum teste coletado",
    stdout="no tests ran in 0.00s\n",
    stderr="",
    expect=SkipReport(skipped_count=0, skipped=[], zero_collected=True, reasons_visible=True),
)

DOTNET_SKIPPED = Case(
    "dotnet test com skip (formato moderno)",
    stdout="Passed!  - Failed:     0, Passed:    10, Skipped:     3, Total:    13, Duration: 900 ms\n",
    stderr="",
    expect=SkipReport(skipped_count=3, skipped=[], zero_collected=False, reasons_visible=False),
)

DOTNET_SKIPPED_LEGACY = Case(
    "dotnet test com skip (formato legado)",
    stdout="Total tests: 13. Passed: 10. Failed: 0. Skipped: 3.\n",
    stderr="",
    expect=SkipReport(skipped_count=3, skipped=[], zero_collected=False, reasons_visible=False),
)

DOTNET_ZERO_COLLECTED = Case(
    "dotnet test sem nenhum teste coletado",
    stdout="Total tests: 0. Passed: 0. Failed: 0. Skipped: 0.\n",
    stderr="",
    expect=SkipReport(skipped_count=0, skipped=[], zero_collected=True, reasons_visible=True),
)

JEST_SKIPPED = Case(
    "jest com skip",
    stdout="Tests:       1 skipped, 2 passed, 3 total\n",
    stderr="",
    expect=SkipReport(skipped_count=1, skipped=[], zero_collected=False, reasons_visible=False),
)

JEST_NO_TESTS = Case(
    "jest sem nenhum teste encontrado",
    stdout="No tests found, exiting with code 1\n",
    stderr="",
    expect=SkipReport(skipped_count=0, skipped=[], zero_collected=True, reasons_visible=True),
)

GO_SKIP_LINES = Case(
    "go test com skip",
    stdout=(
        "=== RUN   TestFoo\n"
        "--- SKIP: TestFoo (0.00s)\n"
        "    foo_test.go:10: env HARNESS_X not set\n"
        "=== RUN   TestBar\n"
        "--- PASS: TestBar (0.00s)\n"
        "PASS\n"
    ),
    stderr="",
    expect=SkipReport(
        skipped_count=1,
        skipped=[SkippedTest(nodeid="TestFoo", reason=None)],
        zero_collected=False,
        reasons_visible=False,
    ),
)

GO_NO_TEST_FILES = Case(
    "go test sem arquivos de teste",
    stdout="?   \tpkg/foo\t[no test files]\n",
    stderr="",
    expect=SkipReport(skipped_count=0, skipped=[], zero_collected=True, reasons_visible=True),
)

CASES = [
    PYTEST_QUIET_NO_SKIPS,
    PYTEST_QUIET_WITH_SKIPS_NO_REASONS,
    PYTEST_RS_WITH_REASONS,
    PYTEST_NO_TESTS_RAN,
    DOTNET_SKIPPED,
    DOTNET_SKIPPED_LEGACY,
    DOTNET_ZERO_COLLECTED,
    JEST_SKIPPED,
    JEST_NO_TESTS,
    GO_SKIP_LINES,
    GO_NO_TEST_FILES,
]


def test_parse_skips_reads_skip_count_reasons_and_zero_collected() -> None:
    for case in CASES:
        got = parse_skips(case.stdout, case.stderr)
        assert got == case.expect, f"{case.id}: esperado {case.expect}, veio {got}"


def test_parse_skips_on_empty_output_is_a_clean_zero() -> None:
    got = parse_skips("", "")
    assert got == SkipReport(skipped_count=0, skipped=[], zero_collected=False, reasons_visible=True)
