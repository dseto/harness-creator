"""E2E dogfood real: cobaia NOVA — `C:/Projetos/miojo-simulator-3.0` (Python /
FastAPI / pytest), independente da cobaia MinimumAPI (C#) usada nos gates de
Fase 1-4. Prova que o harness generaliza para outra linguagem/stack: analyze
-> spec/Plans aprovado -> compile-contract -> Claude real headless
implementando -> `pytest` real.

Gap real corrigido: `GET /leaderboard` (`backend/main.py`) aceita `limit` sem
nenhum limite de faixa (`limit: int = 10`). SQLite trata `LIMIT` negativo como
"sem limite" — `GET /leaderboard?limit=-1` hoje devolve TODAS as linhas da
tabela, ignorando por completo o cap pretendido pela API. A tarefa do
contrato (T-01) pede que `limit` fora da faixa [1, 100] seja rejeitado com
422, igual ao comportamento já existente para os parâmetros da simulação
(`RecipeParams`, todos com `Field(..., ge=..., le=...)`).

Custa tokens reais e exige `claude` no PATH — por isso é OPT-IN via
`HARNESS_E2E_DOGFOOD=1`, mesmo padrão dos demais dogfood tests deste
diretório (nunca confiar no exit code/texto do Claude: cada assert usa prova
real de subprocess — `pytest` rodado por FORA do Claude é quem decide).
"""

from __future__ import annotations

import difflib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("HARNESS_E2E_DOGFOOD") != "1",
    reason="opt-in: custa tokens reais e exige claude no PATH "
           "(rode com HARNESS_E2E_DOGFOOD=1)",
)

from harness.compiler import compile_project  # noqa: E402

SRC_DIR = Path(__file__).resolve().parents[2] / "src"
EVIDENCE_DIR = Path(__file__).resolve().parent / "evidence"
EVIDENCE_PATH = EVIDENCE_DIR / "dogfood-miojo-simulator-leaderboard-limit.md"

MIOJO_SRC = Path(os.environ.get("HARNESS_E2E_MIOJO_SRC", "C:/Projetos/miojo-simulator-3.0"))

SLUG = "dogfood-miojo-leaderboard-limit"
MAIN_REL = "backend/main.py"
TESTS_REL = "tests/test_leaderboard_limit.py"

_EXCLUDE_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", "node_modules"}
_EXCLUDE_SUFFIXES = {".db", ".db-shm", ".db-wal", ".log", ".pyc"}

_PRE_EXISTING_TESTS = ["test_create_run_and_finish", "test_validation_error_returns_friendly_message"]
_NEW_TEST = "test_negative_limit_is_rejected"

_NEW_TEST_PY = '''"""Teste TDD novo: `GET /leaderboard` deve rejeitar `limit` fora de [1, 100].

SQLite trata `LIMIT -1` como "sem limite" — sem validação de faixa, um
cliente com `limit=-1` recebe a tabela inteira, não os top-N pretendidos.
"""

from fastapi.testclient import TestClient
from backend.main import app


def test_negative_limit_is_rejected():
    client = TestClient(app)
    res = client.get("/leaderboard", params={"limit": -1})
    assert res.status_code == 422


def test_oversized_limit_is_rejected():
    client = TestClient(app)
    res = client.get("/leaderboard", params={"limit": 999999})
    assert res.status_code == 422
'''

SPEC_MD_TEMPLATE = """---
slug: {slug}
approved_by: harness-e2e-dogfood
approved_at: {approved_at}
---

# Spec: `limit` do leaderboard deve ter faixa validada

## Escopo
`GET /leaderboard` (`backend/main.py`) declara `limit: int = 10` sem nenhuma
restrição de faixa. SQLite trata `LIMIT` negativo como "sem limite" — hoje
`GET /leaderboard?limit=-1` devolve a tabela inteira, ignorando o cap
pretendido pela API. Corrigir para que `limit` só aceite valores entre 1 e
100 (inclusive), rejeitando o resto com 422 — mesmo padrão já usado em
`RecipeParams` (`backend/schemas.py`), onde todo campo numérico tem
`Field(..., ge=..., le=...)`.

## Critérios de aceitação
- `python -m pytest tests/ -v` passa, incluindo os testes novos em
  `{tests_rel}` (`{new_test}` e `test_oversized_limit_is_rejected`).
- Os testes pré-existentes (`test_create_run_and_finish`,
  `test_validation_error_returns_friendly_message`) continuam passando —
  zero regressão.

## Unknowns
- Nenhum: gap confirmado por leitura direta de `{main_rel}` e `backend/db.py`
  (`LIMIT ?` sem clamp antes de chegar no SQL).
"""

PLANS_MD = f"""## [T-01] Validar faixa de `limit` no leaderboard
- files: `{MAIN_REL}`
- verify: `python -m pytest tests/ -v`
"""

# `enforce_tdd: false` pelo mesmo motivo documentado em
# `test_contract_dogfood.py`: o hook `guard_test_runner` com `enforce_tdd:
# true` responde "ask" para QUALQUER invocação do test_command, e headless
# sem TTY nega todo "ask" automaticamente — bloquearia o próprio Claude de
# rodar `pytest` no passo de implementação. `edit_test` (guard_tests.py)
# continua protegendo o arquivo de teste independente de `enforce_tdd`.
HARNESS_YAML = """\
governance:
  approval_policy: auto
verification:
  enforce_tdd: false
  test_command: "python -m pytest tests/ -v"
  test_glob: "tests/**/*.py"
"""

CLAUDE_PROMPT = (
    "Existe um contrato de trabalho já aprovado em "
    ".harness/work/dogfood-miojo-leaderboard-limit/Plans.md. Implemente EXATAMENTE "
    "a tarefa \"## [T-01] Validar faixa de limit no leaderboard\": no arquivo "
    "backend/main.py, ajuste o parâmetro `limit` do endpoint `GET /leaderboard` "
    "(função get_leaderboard) para que só aceite valores entre 1 e 100 (inclusive) "
    "— por exemplo trocando `limit: int = 10` por "
    "`limit: int = Query(10, ge=1, le=100)` (importe Query de fastapi se precisar) "
    "— e valores fora dessa faixa devem ser rejeitados automaticamente com 422 pelo "
    "FastAPI. NÃO toque em nenhum arquivo dentro de tests/ — os testes que provam o "
    "requisito já existem e não devem ser alterados. Depois de editar, rode "
    "`python -m pytest tests/ -v` você mesmo e só considere a tarefa concluída se o "
    "comando passar (exit 0, todos os testes verdes, incluindo "
    "test_negative_limit_is_rejected e test_oversized_limit_is_rejected)."
)


@pytest.fixture(autouse=True)
def _require_toolchain():
    if shutil.which("claude") is None:
        pytest.skip("binário `claude` não encontrado no PATH")


# A cobaia real só tem requirements.txt (sem pyproject.toml/setup.py) — o
# analyzer só reconhece manifest Python via pyproject.toml/setup.py (ver
# `_PYTHON_MANIFESTS` em analyzer.py). Igual ao fixture da MinimumAPI, que
# adiciona um projeto de testes xUnit sintético à CÓPIA (nunca ao original),
# aqui adicionamos um pyproject.toml mínimo e real à cópia, declarando as
# mesmas dependências de requirements.txt + pytest, para que `analyze`
# detecte "python" e o test_command "pytest" de verdade.
PYPROJECT_TOML = """[project]
name = "miojo-simulator-3-0"
version = "0.1.0"
dependencies = [
    "fastapi==0.115.8",
    "uvicorn[standard]==0.30.6",
    "pydantic==2.12.0",
    "pytest",
    "httpx",
]
"""


def copy_miojo_source(dest_root: Path) -> Path:
    def ignore(directory: str, names: list[str]) -> set[str]:
        skip = {n for n in names if n in _EXCLUDE_DIRS}
        skip |= {n for n in names if Path(n).suffix in _EXCLUDE_SUFFIXES}
        return skip

    shutil.copytree(MIOJO_SRC, dest_root, ignore=ignore)
    (dest_root / "pyproject.toml").write_text(PYPROJECT_TOML, encoding="utf-8")
    return dest_root


@pytest.fixture()
def miojo_project(tmp_path: Path) -> Path:
    """Cobaia fresca por teste: cópia real de `C:/Projetos/miojo-simulator-3.0`."""
    if not MIOJO_SRC.is_dir():
        pytest.skip(f"miojo-simulator-3.0 não encontrado em {MIOJO_SRC} "
                    f"(defina HARNESS_E2E_MIOJO_SRC)")
    return copy_miojo_source(tmp_path / "cobaia")


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd),
    )


def _run_pytest(cwd: Path, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(cwd)}
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd=str(cwd), capture_output=True, text=True, timeout=timeout, env=env,
    )


def _write_evidence(sections: dict[str, str]) -> None:
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    body = (
        "# Evidência — dogfood `dogfood-miojo-leaderboard-limit` "
        "(cobaia nova: miojo-simulator-3.0, Python/FastAPI)\n\n"
    )
    for title in (
        "Regressão (testes pré-existentes)",
        "Nova funcionalidade",
        "Diff aplicado",
        "Execução do agente",
    ):
        body += f"## {title}\n\n{sections.get(title, '(não alcançado — teste parou antes deste ponto)')}\n\n"
    EVIDENCE_PATH.write_text(body, encoding="utf-8")


def test_contract_dogfood_miojo_leaderboard_limit(miojo_project: Path) -> None:
    sections: dict[str, str] = {}
    main_path = miojo_project / MAIN_REL
    tests_path = miojo_project / TESTS_REL
    before_text = main_path.read_text(encoding="utf-8")

    try:
        # ---- (1) TDD real: cria o teste vermelho ANTES da correção ----
        tests_path.write_text(_NEW_TEST_PY, encoding="utf-8")

        before_proc = _run_pytest(miojo_project)
        before_output = (before_proc.stdout or "") + "\n" + (before_proc.stderr or "")
        sections["Regressão (testes pré-existentes)"] = (
            "Execução ANTES da correção (deve estar vermelha no teste novo):\n\n"
            f"```\n{before_output.strip()}\n```\n"
        )
        assert before_proc.returncode != 0, (
            "pytest deveria falhar ANTES da correção (TDD real)\n" + before_output
        )
        assert _NEW_TEST in before_output and "FAILED" in before_output, before_output

        # ---- (2) analyze --dir sobre a cobaia real ----
        analyze_proc = _run_cli(["analyze", "--dir", str(miojo_project)], cwd=miojo_project)
        assert analyze_proc.returncode == 0, analyze_proc.stderr
        profile = json.loads(analyze_proc.stdout)
        assert "python" in {f["value"] for f in profile["languages"]}, profile
        profile_path = miojo_project / ".harness" / "repo-profile.json"
        assert profile_path.is_file()

        # ---- (3) escreve spec.md (pré-aprovado) + Plans.md com T-01 ----
        contract_dir = miojo_project / ".harness" / "work" / SLUG
        contract_dir.mkdir(parents=True, exist_ok=True)
        approved_at = datetime.now(timezone.utc).isoformat()
        (contract_dir / "spec.md").write_text(
            SPEC_MD_TEMPLATE.format(
                slug=SLUG, approved_at=approved_at, main_rel=MAIN_REL,
                tests_rel=TESTS_REL, new_test=_NEW_TEST,
            ),
            encoding="utf-8",
        )
        (contract_dir / "Plans.md").write_text(PLANS_MD, encoding="utf-8")

        # ---- (4) compile-contract -> feature_list.json ----
        compile_contract_proc = _run_cli(
            ["compile-contract", "--dir", str(miojo_project), "--slug", SLUG], cwd=miojo_project
        )
        assert compile_contract_proc.returncode == 0, compile_contract_proc.stderr
        feature_list_path = miojo_project / ".harness" / "feature_list.json"
        feature_list = json.loads(feature_list_path.read_text(encoding="utf-8"))
        assert len(feature_list["features"]) == 1
        assert feature_list["features"][0]["id"] == "T-01"
        assert feature_list["features"][0]["passes"] is False

        # ---- (5) compila governança nativa (auto + test_command real) ----
        harness_yaml_path = miojo_project / ".harness" / "harness.yaml"
        harness_yaml_path.write_text(HARNESS_YAML, encoding="utf-8")
        compile_project(miojo_project)

        # ---- (6) Claude real, headless, implementa T-01 ----
        claude_proc = subprocess.run(
            ["claude", "-p", CLAUDE_PROMPT, "--output-format", "json"],
            cwd=str(miojo_project), capture_output=True, text=True, timeout=300,
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

        # ---- (7) PROVA FINAL: pytest de novo, fora do Claude ----
        after_text = main_path.read_text(encoding="utf-8")
        diff = "\n".join(
            difflib.unified_diff(
                before_text.splitlines(), after_text.splitlines(),
                fromfile=f"a/{MAIN_REL}", tofile=f"b/{MAIN_REL}", lineterm="",
            )
        )
        sections["Diff aplicado"] = f"```diff\n{diff or '(sem diferenças detectadas)'}\n```\n"

        after_proc = _run_pytest(miojo_project)
        after_output = (after_proc.stdout or "") + "\n" + (after_proc.stderr or "")
        sections["Nova funcionalidade"] = (
            "Execução DEPOIS da correção (deve estar verde, incluindo "
            f"{_NEW_TEST} e test_oversized_limit_is_rejected):\n\n"
            f"```\n{after_output.strip()}\n```\n"
        )
        assert after_proc.returncode == 0, (
            "pytest deveria passar DEPOIS da correção\n" + after_output
        )
        for name in _PRE_EXISTING_TESTS + [_NEW_TEST, "test_oversized_limit_is_rejected"]:
            assert name in after_output, f"teste {name} não apareceu na saída: {after_output}"
        sections["Regressão (testes pré-existentes)"] += (
            f"\nResultado agregado depois da correção — zero regressão:\n\n"
            f"```\n{after_output.strip().splitlines()[-1]}\n```\n"
        )
    finally:
        _write_evidence(sections)
