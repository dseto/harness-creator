"""Testes do audit (pivot plugin): score + findings + detecção de drift."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.audit import audit_project
from harness.boundary_guard import install_boundary_guard
from harness.compiler import compile_project

BASIC_YAML = """
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "pytest -x --tb=short"
  test_glob: "tests/**/*.py"
"""


def _bootstrap(target: Path, yaml_content: str = BASIC_YAML) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_content, encoding="utf-8")
    # arquivo de teste real para o check no_test_files não disparar
    tests_dir = target / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def _codes(report) -> set[str]:
    return {f.code for f in report.findings}


def test_freshly_compiled_project_scores_high(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)

    report = audit_project(tmp_path)

    assert report.score >= 85
    assert not any(f.severity == "critical" for f in report.findings)


def test_missing_yaml_is_critical(tmp_path: Path) -> None:
    report = audit_project(tmp_path)
    assert "missing_harness_yaml" in _codes(report)
    assert report.score <= 60


def test_invalid_yaml_is_critical(tmp_path: Path) -> None:
    path = tmp_path / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("governance:\n  approval_policy: modo_inexistente\n", encoding="utf-8")

    report = audit_project(tmp_path)
    assert "invalid_harness_yaml" in _codes(report)


def test_missing_hooks_and_settings_detected(tmp_path: Path) -> None:
    _bootstrap(tmp_path)  # yaml presente, mas nunca compilou

    report = audit_project(tmp_path)
    codes = _codes(report)
    assert "missing_hook" in codes
    assert "missing_settings" in codes


def test_hook_drift_detected_after_manual_edit(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)
    hook = tmp_path / ".harness" / "hooks" / "guard_tests.py"
    hook.write_text(hook.read_text(encoding="utf-8") + "\n# editado à mão\n", encoding="utf-8")

    report = audit_project(tmp_path)
    assert "hook_drift" in _codes(report)


def test_settings_drift_detected_when_rule_removed(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.local.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    settings["permissions"]["ask"].remove("Bash")
    settings_path.write_text(json.dumps(settings), encoding="utf-8")

    report = audit_project(tmp_path)
    assert "permissions_drift" in _codes(report)


def test_yaml_change_without_recompile_is_drift(tmp_path: Path) -> None:
    _bootstrap(tmp_path)
    compile_project(tmp_path)
    # muda a política no yaml sem recompilar -> settings antigo diverge
    (tmp_path / ".harness" / "harness.yaml").write_text(
        BASIC_YAML.replace("balanced", "paranoid"), encoding="utf-8"
    )

    report = audit_project(tmp_path)
    assert "permissions_drift" in _codes(report)  # paranoid exige Read em ask


def test_auto_policy_flagged_as_warning(tmp_path: Path) -> None:
    _bootstrap(tmp_path, BASIC_YAML.replace("balanced", "auto"))
    compile_project(tmp_path)

    report = audit_project(tmp_path)
    assert "auto_policy" in _codes(report)


def _harness_compile(target: Path) -> None:
    """A sequência REAL do subcomando `compile` — as duas chamadas, na ordem.

    `compile_project` sozinho não é o que roda em produção: `cli.py` chama
    `install_boundary_guard` logo depois, no mesmo `try`, e é essa segunda
    chamada que desregistra o `guard_tests.py`. Os testes que exercitam só a
    primeira metade auditam um estado que nenhum usuário tem — foi essa lacuna
    que deixou a issue #61 passar com a suíte verde.
    """
    compile_project(target)
    install_boundary_guard(target)


def test_real_compile_sequence_leaves_no_critical(tmp_path: Path) -> None:
    """Issue #61: repositório recém-compilado não tem finding `critical`.

    Antes da correção, `harness audit` acusava `hook_not_registered` para o
    `guard_tests.py` em TODO repositório compilado — o estado normal do
    produto — e o `fix` sugerido (`Rode harness compile`) reproduzia
    exatamente o achado. Com um `critical` custando 40 pontos, todo repo
    saudável nascia com teto de 60 e a faixa de score perdia significado.
    """
    _bootstrap(tmp_path)
    _harness_compile(tmp_path)

    report = audit_project(tmp_path)

    criticals = [f for f in report.findings if f.severity == "critical"]
    assert not criticals, [f"{f.code}: {f.message}" for f in criticals]
    assert report.score >= 85


@pytest.mark.parametrize(
    ("case", "unregister", "expect_finding"),
    [
        ("registro intacto", False, False),
        ("registro removido à mão", True, True),
    ],
    ids=["registro-intacto", "registro-removido"],
)
def test_hook_not_registered_fires_only_when_genuinely_absent(
    tmp_path: Path, case: str, unregister: bool, expect_finding: bool
) -> None:
    """O detector de hook ausente sobrevive à correção da issue #61.

    A correção barata daquele bug — parar de exigir o registro do
    `guard_tests.py` — poderia apagar o único detector que existe para o caso
    legítimo: um hook que o compilador manda registrar e que REALMENTE não
    está no settings. `hook_not_registered` não tinha nenhuma ocorrência em
    `tests/` antes desta tabela, então não havia o que regredir — a cobertura
    é nova de propósito.

    O par de casos é o teste, não cada linha isolada: a mesma asserção nas
    duas direções é o que distingue "o achado sumiu porque o bug foi
    corrigido" de "o achado sumiu porque foi silenciado".
    """
    _bootstrap(tmp_path)
    _harness_compile(tmp_path)
    settings_path = tmp_path / ".claude" / "settings.local.json"

    if unregister:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        entries = settings["hooks"]["PreToolUse"]
        settings["hooks"]["PreToolUse"] = [
            e for e in entries if "guard_test_runner.py" not in json.dumps(e)
        ]
        assert len(settings["hooks"]["PreToolUse"]) < len(entries), (
            "pré-condição do caso: o guard_test_runner tinha de estar registrado"
        )
        settings_path.write_text(json.dumps(settings), encoding="utf-8")

    report = audit_project(tmp_path)

    assert ("hook_not_registered" in _codes(report)) is expect_finding, (
        f"caso {case!r}: findings={sorted(_codes(report))}"
    )


def test_no_test_files_is_info_finding(tmp_path: Path) -> None:
    path = tmp_path / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(BASIC_YAML, encoding="utf-8")  # sem criar tests/
    compile_project(tmp_path)

    report = audit_project(tmp_path)
    assert "no_test_files" in _codes(report)
