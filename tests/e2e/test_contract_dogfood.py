"""E2E dogfood real: gate final da Fase 1 — não um teste unitário sintético.

Prova de ponta a ponta, na cobaia real (`C:/Projetos/MinimumAPI`, cópia fresca
via fixture `api_project` de `conftest.py`): analyze -> spec/Plans aprovado ->
compile-contract -> Claude real headless implementando -> `dotnet test` real.

Gap real corrigido: `CreateCustomerRequestValidator` (`MinimumAPI/Validators/
CustomerValidators.cs`) valida `Document` só por tamanho — um documento como
`"1234567890a"` passa hoje. A tarefa do contrato (T-01) pede que o documento
só aceite dígitos.

Custa tokens reais e exige `claude` + `dotnet` no PATH — por isso é OPT-IN
via `HARNESS_E2E_DOGFOOD=1`, seguindo o mesmo padrão de `test_headless.py`
(nunca confiar no exit code/texto do Claude: cada assert usa prova real de
subprocess — `dotnet test` rodado por FORA do Claude é quem decide).
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("HARNESS_E2E_DOGFOOD") != "1",
    reason="opt-in: custa tokens reais e exige dotnet+claude no PATH "
           "(rode com HARNESS_E2E_DOGFOOD=1)",
)

from harness.compiler import compile_project  # noqa: E402

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "fase1-dogfood-document-digits.md"

SLUG = "dogfood-document-digits"
VALIDATOR_REL = "MinimumAPI/Validators/CustomerValidators.cs"
TESTS_REL = "MinimumAPI.Tests/CustomerValidatorTests.cs"

_TRX_NS = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}

_PRE_EXISTING_TESTS = ["Valid_request_passes", "Empty_name_fails", "Short_document_fails"]
_NEW_TEST = "Document_with_letters_fails"

_NEW_FACT_CS = '''
    [Fact]
    public void Document_with_letters_fails()
    {
        var request = new CreateCustomerRequest("Ana", "ana@example.com", "1234567890a");
        _validator.TestValidate(request).ShouldHaveValidationErrorFor(x => x.Document);
    }
'''

SPEC_MD_TEMPLATE = """---
slug: {slug}
approved_by: harness-e2e-dogfood
approved_at: {approved_at}
---

# Spec: Documento deve conter apenas dígitos

## Escopo
`CreateCustomerRequestValidator` valida `Document` só por tamanho
(`MinimumLength(11)`/`MaximumLength(20)`), sem checar que é só dígitos —
hoje um documento como `"1234567890a"` passa na validação. Corrigir para
que o documento aceite apenas dígitos.

## Critérios de aceitação
- `dotnet test MinimumAPI.Tests` passa, incluindo o teste
  `Document_with_letters_fails` (documento com letra deve falhar validação).
- Os testes pré-existentes (`Valid_request_passes`, `Empty_name_fails`,
  `Short_document_fails`) continuam passando — zero regressão.

## Unknowns
- Nenhum: gap confirmado por leitura direta de `{validator_rel}`.
"""

PLANS_MD = f"""## [T-01] Documento deve conter apenas dígitos
- files: `{VALIDATOR_REL}`
- verify: `dotnet test MinimumAPI.Tests`
"""

# `enforce_tdd: false` de propósito: o hook `guard_test_runner` gerado com
# `enforce_tdd: true` responde "ask" para QUALQUER invocação do test_command,
# em QUALQUER política (é gate de disciplina TDD, ortogonal a
# `approval_policy`) — e headless sem TTY nega todo "ask" automaticamente
# (achado documentado em `test_headless.py`). Isso bloquearia o próprio
# Claude de rodar `dotnet test` no passo 6. `approval_policy: auto` libera
# Edit/Bash em arquivos de produção; `edit_test` (hook `guard_tests.py`,
# sempre ativo independente de `enforce_tdd`) continua protegendo o arquivo
# de teste.
HARNESS_YAML = """\
governance:
  approval_policy: auto
verification:
  enforce_tdd: false
  test_command: "dotnet test MinimumAPI.Tests"
  test_glob: "MinimumAPI.Tests/**/*.cs"
"""

CLAUDE_PROMPT = (
    "Existe um contrato de trabalho já aprovado em "
    ".harness/work/dogfood-document-digits/Plans.md. Implemente EXATAMENTE a "
    "tarefa \"## [T-01] Documento deve conter apenas dígitos\": no arquivo "
    "MinimumAPI/Validators/CustomerValidators.cs, ajuste o RuleFor(x => x.Document) "
    "de CreateCustomerRequestValidator para que, além das regras já existentes, o "
    "documento só seja aceito se contiver apenas dígitos — por exemplo adicionando "
    ".Matches(@\"^\\d+$\").WithMessage(\"O documento deve conter apenas dígitos.\") "
    "(ou equivalente). NÃO toque em nenhum arquivo dentro de MinimumAPI.Tests — o "
    "teste que prova o requisito já existe e não deve ser alterado. Depois de "
    "editar, rode `dotnet test MinimumAPI.Tests` você mesmo e só considere a tarefa "
    "concluída se o comando passar (exit 0, todos os testes verdes, incluindo o "
    "teste Document_with_letters_fails)."
)


@pytest.fixture(autouse=True)
def _require_toolchain():
    if shutil.which("claude") is None:
        pytest.skip("binário `claude` não encontrado no PATH")
    if shutil.which("dotnet") is None:
        pytest.skip("binário `dotnet` não encontrado no PATH")


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd),
    )


def _run_dotnet_test(
    cwd: Path, results_dir: Path, log_file_name: str, timeout: int = 300
) -> tuple[subprocess.CompletedProcess[str], Path]:
    trx_path = results_dir / log_file_name
    proc = subprocess.run(
        [
            "dotnet", "test", "MinimumAPI.Tests",
            "--logger", f"trx;LogFileName={log_file_name}",
            "--results-directory", str(results_dir),
        ],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout,
    )
    return proc, trx_path


def _parse_trx(trx_path: Path) -> dict[str, str]:
    """testName (substring-matchable) -> outcome ('Passed'/'Failed'/...)."""
    if not trx_path.is_file():
        return {}
    root = ET.parse(trx_path).getroot()
    results = {}
    for result in root.findall(".//t:UnitTestResult", _TRX_NS):
        name = result.get("testName", "")
        outcome = result.get("outcome", "")
        results[name] = outcome
    return results


def _outcome_for(trx_results: dict[str, str], method_name: str) -> str | None:
    for test_name, outcome in trx_results.items():
        if method_name in test_name:
            return outcome
    return None


def _add_new_fact(tests_path: Path) -> None:
    text = tests_path.read_text(encoding="utf-8")
    stripped = text.rstrip()
    assert stripped.endswith("}"), f"formato inesperado em {tests_path}"
    new_text = stripped[:-1] + _NEW_FACT_CS + "}\n"
    tests_path.write_text(new_text, encoding="utf-8")


def _write_evidence(sections: dict[str, str]) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    body = "# Evidência — dogfood `dogfood-document-digits`\n\n"
    for title in (
        "Regressão (testes pré-existentes)",
        "Nova funcionalidade",
        "Diff aplicado",
        "Execução do agente",
    ):
        body += f"## {title}\n\n{sections.get(title, '(não alcançado — teste parou antes deste ponto)')}\n\n"
    EVIDENCE_PATH.write_text(body, encoding="utf-8")


def test_contract_dogfood_document_digits(api_project: Path) -> None:
    sections: dict[str, str] = {}
    validator_path = api_project / VALIDATOR_REL
    tests_path = api_project / TESTS_REL
    before_text = validator_path.read_text(encoding="utf-8")

    try:
        # ---- (1) TDD real: adiciona o teste vermelho ANTES da correção ----
        _add_new_fact(tests_path)

        before_dir = api_project / "TestResults" / "before"
        before_proc, before_trx = _run_dotnet_test(api_project, before_dir, "before.trx")
        before_output = (before_proc.stdout or "") + "\n" + (before_proc.stderr or "")
        sections["Regressão (testes pré-existentes)"] = (
            "Execução ANTES da correção (deve estar vermelha):\n\n"
            f"```\n{before_output.strip()}\n```\n"
        )
        assert before_proc.returncode != 0, (
            "dotnet test deveria falhar ANTES da correção (TDD real)\n" + before_output
        )
        before_trx_results = _parse_trx(before_trx)
        if before_trx_results:
            new_outcome = _outcome_for(before_trx_results, _NEW_TEST)
            assert new_outcome != "Passed", (
                f"{_NEW_TEST} não deveria passar antes da correção: {before_trx_results}"
            )

        # ---- (2) analyze --dir sobre a cobaia real ----
        analyze_proc = _run_cli(["analyze", "--dir", str(api_project)], cwd=api_project)
        assert analyze_proc.returncode == 0, analyze_proc.stderr
        profile = json.loads(analyze_proc.stdout)
        assert "csharp" in {f["value"] for f in profile["languages"]}, profile
        profile_path = api_project / ".harness" / "repo-profile.json"
        assert profile_path.is_file()

        # ---- (3) escreve spec.md (pré-aprovado) + Plans.md com T-01 ----
        contract_dir = api_project / ".harness" / "work" / SLUG
        contract_dir.mkdir(parents=True, exist_ok=True)
        approved_at = datetime.now(timezone.utc).isoformat()
        (contract_dir / "spec.md").write_text(
            SPEC_MD_TEMPLATE.format(
                slug=SLUG, approved_at=approved_at, validator_rel=VALIDATOR_REL
            ),
            encoding="utf-8",
        )
        (contract_dir / "Plans.md").write_text(PLANS_MD, encoding="utf-8")

        # ---- (4) compile-contract -> feature_list.json ----
        compile_contract_proc = _run_cli(
            ["compile-contract", "--dir", str(api_project), "--slug", SLUG], cwd=api_project
        )
        assert compile_contract_proc.returncode == 0, compile_contract_proc.stderr
        feature_list_path = api_project / ".harness" / "feature_list.json"
        feature_list = json.loads(feature_list_path.read_text(encoding="utf-8"))
        assert len(feature_list["features"]) == 1
        assert feature_list["features"][0]["id"] == "T-01"
        assert feature_list["features"][0]["passes"] is False

        # ---- (5) compila governança nativa (auto + test_command real) ----
        harness_yaml_path = api_project / ".harness" / "harness.yaml"
        harness_yaml_path.write_text(HARNESS_YAML, encoding="utf-8")
        compile_project(api_project)

        # ---- (6) Claude real, headless, implementa T-01 ----
        claude_proc = subprocess.run(
            ["claude", "-p", CLAUDE_PROMPT, "--output-format", "json"],
            cwd=str(api_project), capture_output=True, text=True, timeout=300,
        )
        assert claude_proc.returncode == 0, claude_proc.stderr
        out = json.loads(claude_proc.stdout)

        result_text = str(out.get("result", ""))
        sections["Execução do agente"] = (
            f"- `is_error`: {out.get('is_error')}\n"
            f"- `permission_denials`: {out.get('permission_denials')}\n"
            f"- `num_turns`: {out.get('num_turns')}\n\n"
            f"Últimos ~500 caracteres da resposta:\n\n```\n{result_text[-500:]}\n```\n"
        )
        assert out["is_error"] is False, out

        # ---- (7) PROVA FINAL: dotnet test de novo, fora do Claude ----
        after_text = validator_path.read_text(encoding="utf-8")
        diff = "\n".join(
            difflib.unified_diff(
                before_text.splitlines(), after_text.splitlines(),
                fromfile=f"a/{VALIDATOR_REL}", tofile=f"b/{VALIDATOR_REL}", lineterm="",
            )
        )
        sections["Diff aplicado"] = f"```diff\n{diff or '(sem diferenças detectadas)'}\n```\n"

        after_dir = api_project / "TestResults" / "after"
        after_proc, after_trx = _run_dotnet_test(api_project, after_dir, "after.trx")
        after_output = (after_proc.stdout or "") + "\n" + (after_proc.stderr or "")
        sections["Nova funcionalidade"] = (
            "Execução DEPOIS da correção (deve estar verde, incluindo "
            f"{_NEW_TEST}):\n\n```\n{after_output.strip()}\n```\n"
        )
        assert after_proc.returncode == 0, (
            "dotnet test deveria passar DEPOIS da correção\n" + after_output
        )

        after_trx_results = _parse_trx(after_trx)
        new_outcome = _outcome_for(after_trx_results, _NEW_TEST)
        assert new_outcome == "Passed", f"{_NEW_TEST} deveria passar: {after_trx_results}"

        regressao = {}
        for name in _PRE_EXISTING_TESTS:
            outcome = _outcome_for(after_trx_results, name)
            regressao[name] = outcome
            assert outcome == "Passed", (
                f"regressão: {name} deveria continuar passando: {after_trx_results}"
            )
        sections["Regressão (testes pré-existentes)"] += (
            "\nResultado individual (via .trx) depois da correção — zero regressão:\n\n"
            f"```\n{json.dumps(regressao, indent=2, ensure_ascii=False)}\n```\n"
        )
    finally:
        _write_evidence(sections)
