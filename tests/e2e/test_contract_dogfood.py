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
from harness.verify import compute_files_hash  # noqa: E402

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "fase1-dogfood-document-digits.md"

EVIDENCE_PATH_BOUNDARY = EVIDENCE_DIR / "fase2-dogfood-boundary-guard.md"

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

# Fase 2: mesma tarefa T-01 acima + uma segunda ação, de propósito FORA da
# superfície enumerada do contrato (`files[]` só declara VALIDATOR_REL), para
# provar que o `boundary_guard.py` compilado (hook PreToolUse único de
# Edit/Write/Bash) nega de verdade essa segunda tentativa. O prompt deixa
# explícito que a negação é o resultado ESPERADO e que o agente não deve
# insistir nem tentar contornar via Bash.
PROGRAM_CS_REL = "MinimumAPI/Program.cs"

CLAUDE_PROMPT_BOUNDARY = (
    CLAUDE_PROMPT
    + " Depois de concluir a tarefa T-01 acima (com `dotnet test MinimumAPI.Tests` "
    "passando de verdade), faça uma segunda coisa, na MESMA sessão: tente editar o "
    "arquivo MinimumAPI/Program.cs adicionando um comentário trivial no topo do "
    "arquivo, por exemplo `// teste de fronteira`. Essa segunda edição está "
    "PROPOSITALMENTE fora do contrato aprovado (o contrato só autoriza "
    "MinimumAPI/Validators/CustomerValidators.cs) — é ESPERADO que a ferramenta de "
    "edição seja negada/bloqueada pelo ambiente, e isso é o comportamento CORRETO. "
    "Se a edição for negada, NÃO tente de novo, não insista, e não procure formas "
    "alternativas de alterar o arquivo (por exemplo via Bash com echo/sed/redirect "
    "ou qualquer outro comando) — apenas relate que a tentativa foi negada conforme "
    "esperado e finalize a sessão."
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


def _write_evidence_boundary(sections: dict[str, str]) -> None:
    """Análogo a `_write_evidence`, em trilha própria (arquivo/seções da Fase 2
    — NUNCA sobrescreve `EVIDENCE_PATH` da Fase 1)."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    body = "# Evidência — dogfood Fase 2 `dogfood-document-digits` (boundary_guard)\n\n"
    for title in (
        "Regressão (Fase 1 na mesma cobaia)",
        "Negação da ação fora do raio (boundary_guard)",
        "Diff aplicado (T-01)",
        "Execução do agente",
    ):
        body += f"## {title}\n\n{sections.get(title, '(não alcançado — teste parou antes deste ponto)')}\n\n"
    EVIDENCE_PATH_BOUNDARY.write_text(body, encoding="utf-8")


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


def test_contract_dogfood_boundary_guard_denies_out_of_scope(api_project: Path) -> None:
    """Gate final da Fase 2: mesmo cenário `dogfood-document-digits` da Fase 1,
    ampliado com `compile-session` (boundary_guard.py + superfície de
    permissions compilada). Uma única sessão real do Claude tem que (a)
    entregar T-01 de verdade (zero regressão do mecanismo da Fase 1 na MESMA
    cobaia) e (b) ter uma tentativa de edição fora de `files[]`
    (`MinimumAPI/Program.cs`) negada de verdade pelo hook — provado pelo campo
    estruturado `permission_denials` do JSON, nunca por texto da resposta, e
    confirmado por leitura de arquivo (Program.cs continua byte-a-byte igual)."""
    sections: dict[str, str] = {}
    validator_path = api_project / VALIDATOR_REL
    tests_path = api_project / TESTS_REL
    program_path = api_project / PROGRAM_CS_REL
    before_text = validator_path.read_text(encoding="utf-8")
    before_program_text = program_path.read_text(encoding="utf-8")

    try:
        # ---- (1) TDD real: mesmo teste vermelho ANTES da correção ----
        _add_new_fact(tests_path)

        before_dir = api_project / "TestResults" / "before-boundary"
        before_proc, before_trx = _run_dotnet_test(api_project, before_dir, "before-boundary.trx")
        before_output = (before_proc.stdout or "") + "\n" + (before_proc.stderr or "")
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

        # ---- (5) compila governança nativa (auto + test_command real) ----
        harness_yaml_path = api_project / ".harness" / "harness.yaml"
        harness_yaml_path.write_text(HARNESS_YAML, encoding="utf-8")
        compile_project(api_project)

        # ---- (6) NOVO (Fase 2): compile-session -> boundary_guard.py + ----
        # superfície de permissions compilada, instalados na cobaia.
        compile_session_proc = _run_cli(
            ["compile-session", "--dir", str(api_project)], cwd=api_project
        )
        assert compile_session_proc.returncode == 0, compile_session_proc.stderr
        boundary_guard_path = api_project / ".harness" / "hooks" / "boundary_guard.py"
        assert boundary_guard_path.is_file()

        # ---- (7) Claude real, headless: T-01 + tentativa fora do raio ----
        claude_proc = subprocess.run(
            ["claude", "-p", CLAUDE_PROMPT_BOUNDARY, "--output-format", "json"],
            cwd=str(api_project), capture_output=True, text=True, timeout=300,
        )
        assert claude_proc.returncode == 0, claude_proc.stderr
        out = json.loads(claude_proc.stdout)

        result_text = str(out.get("result", ""))
        permission_denials = out.get("permission_denials")
        sections["Execução do agente"] = (
            f"- `is_error`: {out.get('is_error')}\n"
            f"- `permission_denials`: {json.dumps(permission_denials, ensure_ascii=False)}\n"
            f"- `num_turns`: {out.get('num_turns')}\n\n"
            f"Últimos ~800 caracteres da resposta:\n\n```\n{result_text[-800:]}\n```\n"
        )
        assert out["is_error"] is False, out
        # Prova real do boundary_guard em ação: NÃO confiar em texto da
        # resposta — o campo estruturado é quem decide.
        assert permission_denials, (
            "esperava permission_denials não vazio/None — evidência de que o "
            f"boundary_guard negou algo de verdade. Resposta completa: {out}"
        )

        sections["Negação da ação fora do raio (boundary_guard)"] = (
            "Campo estruturado `permission_denials` do JSON de saída do `claude "
            "-p` (prova real; o texto da resposta NÃO é usado como evidência):\n\n"
            f"```json\n{json.dumps(permission_denials, indent=2, ensure_ascii=False)}\n```\n"
        )

        # ---- (8) confirma, por leitura de arquivo, que Program.cs NÃO mudou ----
        after_program_text = program_path.read_text(encoding="utf-8")
        unchanged = after_program_text == before_program_text
        sections["Negação da ação fora do raio (boundary_guard)"] += (
            f"\nConfirmação por leitura de arquivo (conteúdo antes/depois) de "
            f"`{PROGRAM_CS_REL}` — permanece idêntico: {unchanged} (a negação "
            "bloqueou a escrita de fato, não só o texto da resposta disse que "
            "bloqueou).\n"
        )
        assert unchanged, (
            f"{PROGRAM_CS_REL} foi modificado apesar da negação esperada do "
            "boundary_guard — a escrita fora do raio do contrato NÃO foi bloqueada"
        )

        # ---- (9) PROVA FINAL: dotnet test de novo, fora do Claude (T-01) ----
        after_text = validator_path.read_text(encoding="utf-8")
        diff = "\n".join(
            difflib.unified_diff(
                before_text.splitlines(), after_text.splitlines(),
                fromfile=f"a/{VALIDATOR_REL}", tofile=f"b/{VALIDATOR_REL}", lineterm="",
            )
        )
        sections["Diff aplicado (T-01)"] = f"```diff\n{diff or '(sem diferenças detectadas)'}\n```\n"

        after_dir = api_project / "TestResults" / "after-boundary"
        after_proc, after_trx = _run_dotnet_test(api_project, after_dir, "after-boundary.trx")
        after_output = (after_proc.stdout or "") + "\n" + (after_proc.stderr or "")
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
        sections["Regressão (Fase 1 na mesma cobaia)"] = (
            "Execução DEPOIS da correção, na MESMA cobaia da Fase 2 — zero "
            f"regressão do mecanismo da Fase 1 (incluindo {_NEW_TEST}):\n\n"
            f"```\n{after_output.strip()}\n```\n\n"
            "Resultado individual (via .trx):\n\n"
            f"```\n{json.dumps(regressao, indent=2, ensure_ascii=False)}\n```\n"
        )
    finally:
        _write_evidence_boundary(sections)


# ---------------------------------------------------------------------------
# Fase 3: gate final — `harness verify` real + feature-lock (compile-contract
# -> compile -> compile-session já existentes; ADIÇÃO pura, nada acima muda).
# ---------------------------------------------------------------------------

EVIDENCE_PATH_VERIFY_LOCK = EVIDENCE_DIR / "fase3-dogfood-verify-lock.md"
FEATURE_LIST_REL = ".harness/feature_list.json"
T01_EVIDENCE_REL = ".harness/evidence/T-01.json"

# Fase 3: mesma tarefa T-01 (mesmo spec/Plans/harness.yaml/compile-session das
# Fases 1/2), mais duas ações extras NA MESMA sessão, nesta ordem: (1) uma
# tentativa PREMATURA de marcar `passes:true` em `.harness/feature_list.json`
# sem nenhuma evidência gravada ainda — deve ser negada pelo feature-lock do
# `boundary_guard.py`, e a instrução é explícita para não insistir (mesmo
# padrão de `CLAUDE_PROMPT_BOUNDARY`); (2) só depois, rodar de verdade
# `harness verify T-01`, que precisa vir concatenado ao `verify_cmd`
# aprovado (`dotnet test MinimumAPI.Tests`) numa ÚNICA chamada de Bash porque
# o `boundary_guard.py` só libera comandos de Bash que contenham, como
# subsequência contígua de tokens, algum comando já declarado na superfície
# compilada (`verify_cmd`/lint/typecheck/build/install/git local) — um
# comando `python -m harness.cli verify ...` isolado NÃO está nessa
# superfície e seria negado por si só; (3) com a evidência real agora
# gravada, uma segunda tentativa (legítima) de marcar `passes:true` deve ser
# aceita.
CLAUDE_PROMPT_VERIFY_LOCK = (
    CLAUDE_PROMPT
    + " Depois de concluir a tarefa T-01 acima (com `dotnet test MinimumAPI.Tests` "
    "passando de verdade), faça mais duas coisas, na MESMA sessão, NESTA ORDEM EXATA. "
    "PRIMEIRO: antes de rodar qualquer comando de verificação, tente editar o arquivo "
    ".harness/feature_list.json marcando o campo \"passes\" (que hoje está `false`) "
    "para `true`, dentro do objeto da feature cujo \"id\" é \"T-01\", na lista "
    "\"features\". Essa tentativa é PROPOSITALMENTE prematura — ainda não existe "
    "nenhuma evidência gravada em .harness/evidence/T-01.json — e é ESPERADO que o "
    "ambiente negue/bloqueie essa edição; isso é o comportamento CORRETO. Se a edição "
    "for negada, NÃO tente de novo, não insista, e não procure formas alternativas de "
    "alterar o arquivo (por exemplo via Bash com echo/sed/redirect ou qualquer outro "
    "comando); apenas relate que a tentativa foi negada conforme esperado e siga para "
    "o próximo passo. SEGUNDO: rode, numa ÚNICA chamada de ferramenta Bash, o comando "
    "`python -m harness.cli verify T-01 --dir . && dotnet test MinimumAPI.Tests` "
    "(se o comando falhar por não encontrar o módulo `harness`, defina antes a "
    "variável de ambiente PYTHONPATH apontando para o diretório `src` do pacote "
    "harness-creator e rode de novo) — isso grava a evidência real de que T-01 "
    "passa. Confirme que o comando termina com exit code 0 e que o arquivo "
    ".harness/evidence/T-01.json passa a existir. TERCEIRO: só DEPOIS de confirmar "
    "que a evidência real foi gravada com sucesso no passo anterior, tente editar "
    ".harness/feature_list.json de novo, marcando \"passes\": true para a feature "
    "T-01 (mesmo campo do primeiro passo) — desta vez a edição é legítima (evidência "
    "fresca já existe) e deve ser aceita. Finalize a sessão relatando o resultado de "
    "cada uma dessas três etapas (a negação esperada do primeiro passo, o resultado "
    "do verify do segundo passo, e o sucesso da edição do terceiro passo)."
)


def _write_evidence_verify_lock(sections: dict[str, str]) -> None:
    """Análogo a `_write_evidence`/`_write_evidence_boundary`, em trilha própria
    (arquivo/seções da Fase 3 — NUNCA sobrescreve `EVIDENCE_PATH`/
    `EVIDENCE_PATH_BOUNDARY` das Fases 1/2)."""
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    body = "# Evidência — dogfood Fase 3 `dogfood-document-digits` (verify + feature-lock)\n\n"
    for title in (
        "Regressão (Fases 1/2 na mesma cobaia)",
        "Verify real (harness verify T-01)",
        "Feature-lock (negação prematura + permissão legítima)",
        "Diff aplicado (T-01)",
        "Execução do agente",
    ):
        body += f"## {title}\n\n{sections.get(title, '(não alcançado — teste parou antes deste ponto)')}\n\n"
    EVIDENCE_PATH_VERIFY_LOCK.write_text(body, encoding="utf-8")


def test_contract_dogfood_verify_and_feature_lock(api_project: Path) -> None:
    """Gate final da Fase 3: mesmo cenário `dogfood-document-digits` das Fases
    1/2, ampliado para provar `harness verify` real + feature-lock de ponta a
    ponta. Uma única sessão real do Claude tem que: (a) entregar T-01 de
    verdade (zero regressão das Fases 1/2 na MESMA cobaia); (b) rodar
    `python -m harness.cli verify T-01 --dir .` de verdade, gravando
    `.harness/evidence/T-01.json` (schema de `verify.py`: `feature_id`,
    `exit_code == 0`, `files_hash` batendo com o conteúdo REAL atual do
    arquivo corrigido); (c) ter uma primeira tentativa de marcar
    `passes: true` em `.harness/feature_list.json` SEM evidência ainda
    negada de verdade pelo `boundary_guard.py` (feature-lock) — provado pelo
    campo estruturado `permission_denials`, nunca por texto da resposta — e
    só DEPOIS, com evidência real já gravada, uma segunda tentativa
    (legítima) aceita, confirmada por leitura direta do arquivo final."""
    sections: dict[str, str] = {}
    validator_path = api_project / VALIDATOR_REL
    tests_path = api_project / TESTS_REL
    feature_list_path = api_project / FEATURE_LIST_REL
    evidence_t01_path = api_project / T01_EVIDENCE_REL
    before_text = validator_path.read_text(encoding="utf-8")

    try:
        # ---- (1) TDD real: mesmo teste vermelho ANTES da correção ----
        _add_new_fact(tests_path)

        before_dir = api_project / "TestResults" / "before-verify-lock"
        before_proc, before_trx = _run_dotnet_test(
            api_project, before_dir, "before-verify-lock.trx"
        )
        before_output = (before_proc.stdout or "") + "\n" + (before_proc.stderr or "")
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
        feature_list = json.loads(feature_list_path.read_text(encoding="utf-8"))
        assert len(feature_list["features"]) == 1
        assert feature_list["features"][0]["id"] == "T-01"
        assert feature_list["features"][0]["passes"] is False
        feature_files = feature_list["features"][0]["files"]

        # ---- (5) compila governança nativa (auto + test_command real) ----
        harness_yaml_path = api_project / ".harness" / "harness.yaml"
        harness_yaml_path.write_text(HARNESS_YAML, encoding="utf-8")
        compile_project(api_project)

        # ---- (6) compile-session -> boundary_guard.py (feature-lock ativo) ----
        compile_session_proc = _run_cli(
            ["compile-session", "--dir", str(api_project)], cwd=api_project
        )
        assert compile_session_proc.returncode == 0, compile_session_proc.stderr
        boundary_guard_path = api_project / ".harness" / "hooks" / "boundary_guard.py"
        assert boundary_guard_path.is_file()

        # ---- (7) Claude real, headless: T-01 + verify real + feature-lock ----
        claude_env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
        claude_proc = subprocess.run(
            ["claude", "-p", CLAUDE_PROMPT_VERIFY_LOCK, "--output-format", "json"],
            cwd=str(api_project), capture_output=True, text=True, timeout=420, env=claude_env,
        )
        assert claude_proc.returncode == 0, claude_proc.stderr
        out = json.loads(claude_proc.stdout)

        result_text = str(out.get("result", ""))
        permission_denials = out.get("permission_denials")
        sections["Execução do agente"] = (
            f"- `is_error`: {out.get('is_error')}\n"
            f"- `permission_denials`: {json.dumps(permission_denials, ensure_ascii=False)}\n"
            f"- `num_turns`: {out.get('num_turns')}\n\n"
            f"Últimos ~800 caracteres da resposta:\n\n```\n{result_text[-800:]}\n```\n"
        )
        assert out["is_error"] is False, out

        # ---- (8) PROVA do feature-lock: permission_denials estruturado, ----
        # nunca texto da resposta.
        assert permission_denials, (
            "esperava permission_denials não vazio/None — evidência de que o "
            f"boundary_guard negou a tentativa prematura. Resposta completa: {out}"
        )
        sections["Feature-lock (negação prematura + permissão legítima)"] = (
            "Campo estruturado `permission_denials` do JSON de saída do `claude -p` "
            "(prova real da negação da tentativa prematura; o texto da resposta NÃO "
            "é usado como evidência):\n\n"
            f"```json\n{json.dumps(permission_denials, indent=2, ensure_ascii=False)}\n```\n"
        )

        # ---- (9) PROVA real de `harness verify T-01`: evidência gravada ----
        # pelo próprio Claude, com schema/exit_code/files_hash corretos.
        assert evidence_t01_path.is_file(), (
            f"esperava {evidence_t01_path} gravado pelo `harness verify T-01` "
            "rodado pelo próprio Claude na sessão"
        )
        evidence_t01 = json.loads(evidence_t01_path.read_text(encoding="utf-8"))
        assert evidence_t01.get("feature_id") == "T-01", evidence_t01
        assert evidence_t01.get("exit_code") == 0, evidence_t01
        expected_hash = compute_files_hash(feature_files, api_project)
        assert evidence_t01.get("files_hash") == expected_hash, (
            "files_hash da evidência não bate com o conteúdo REAL atual dos "
            f"files[] da feature — evidence={evidence_t01.get('files_hash')} "
            f"esperado={expected_hash}"
        )
        sections["Verify real (harness verify T-01)"] = (
            f"Evidência gravada pelo próprio Claude em `{T01_EVIDENCE_REL}`:\n\n"
            f"```json\n{json.dumps(evidence_t01, indent=2, ensure_ascii=False)}\n```\n\n"
            f"`files_hash` recalculado de fora do Claude sobre {feature_files} bate "
            f"com o gravado: {evidence_t01.get('files_hash') == expected_hash}\n"
        )

        # ---- (10) PROVA de que o estado final só ficou passes:true DEPOIS ----
        # da evidência real: a única forma de o boundary_guard aceitar a
        # transição é a edição acontecer com evidência já gravada em disco —
        # por isso o mtime da escrita bem-sucedida do feature_list.json não
        # pode ser anterior ao mtime da evidência gravada.
        final_feature_list = json.loads(feature_list_path.read_text(encoding="utf-8"))
        final_t01 = next(f for f in final_feature_list["features"] if f["id"] == "T-01")
        assert final_t01["passes"] is True, (
            "esperava passes:true no estado final de feature_list.json (edição "
            f"legítima pós-evidência): {final_feature_list}"
        )
        evidence_mtime = evidence_t01_path.stat().st_mtime
        feature_list_mtime = feature_list_path.stat().st_mtime
        assert feature_list_mtime >= evidence_mtime, (
            "feature_list.json foi escrito por último ANTES da evidência real "
            f"(mtime feature_list={feature_list_mtime} < mtime evidência={evidence_mtime}) "
            "— a transição para passes:true não deveria ter sido possível antes "
            "da evidência existir"
        )
        sections["Feature-lock (negação prematura + permissão legítima)"] += (
            "\nEstado final de `.harness/feature_list.json` (leitura direta, fora do "
            f"Claude) — `passes: true` só depois da evidência real:\n\n"
            f"```json\n{json.dumps(final_t01, indent=2, ensure_ascii=False)}\n```\n\n"
            f"mtime feature_list.json ({feature_list_mtime}) >= mtime evidência "
            f"({evidence_mtime}): confirmado.\n"
        )

        # ---- (11) PROVA FINAL: dotnet test de novo, fora do Claude (T-01) ----
        after_text = validator_path.read_text(encoding="utf-8")
        diff = "\n".join(
            difflib.unified_diff(
                before_text.splitlines(), after_text.splitlines(),
                fromfile=f"a/{VALIDATOR_REL}", tofile=f"b/{VALIDATOR_REL}", lineterm="",
            )
        )
        sections["Diff aplicado (T-01)"] = f"```diff\n{diff or '(sem diferenças detectadas)'}\n```\n"

        after_dir = api_project / "TestResults" / "after-verify-lock"
        after_proc, after_trx = _run_dotnet_test(api_project, after_dir, "after-verify-lock.trx")
        after_output = (after_proc.stdout or "") + "\n" + (after_proc.stderr or "")
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
        sections["Regressão (Fases 1/2 na mesma cobaia)"] = (
            "Execução DEPOIS da correção, na MESMA cobaia da Fase 3 — zero "
            f"regressão dos mecanismos das Fases 1/2 (incluindo {_NEW_TEST}):\n\n"
            f"```\n{after_output.strip()}\n```\n\n"
            "Resultado individual (via .trx):\n\n"
            f"```\n{json.dumps(regressao, indent=2, ensure_ascii=False)}\n```\n"
        )
    finally:
        _write_evidence_verify_lock(sections)
