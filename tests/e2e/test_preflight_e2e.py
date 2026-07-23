"""E2E (gate final da demanda preflight): prova REAL, não sintética.

Regra permanente do ROADMAP: toda fase fecha com prova real (mock em disco +
CLI real via subprocess) e uma evidência legível commitada em markdown. Este
teste monta DOIS repositórios git de verdade em `tmp_path`, invoca
`python -m harness.cli preflight --dir <mock>` por `subprocess.run` DE VERDADE
(mesmo interpretador, `PYTHONPATH=src`) — NÃO chama `run_preflight()` direto —
e grava o laudo real de cada mock em
`tests/e2e/evidence/preflight-dogfood-2026-07-17.md`.

Não usa `HARNESS_E2E_DOGFOOD`: não invoca claude/dotnet, é barato e roda no
gate padrão da suíte.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# Raiz do repo do plugin = tests/e2e/ -> tests/ -> raiz; SRC_DIR = raiz/src.
REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = REPO_ROOT / "src"

# Evidência humana do PRÓPRIO repo do plugin (não do repo-alvo avaliado — a
# garantia read-only do preflight é sobre o ALVO, não sobre onde o teste grava).
EVIDENCE_PATH = Path(__file__).resolve().parent / "evidence" / "preflight-dogfood-2026-07-17.md"

# Mock (a): pyproject MÍNIMO — projeto Python válido, mas SEM pytest e SEM
# [tool.ruff]. Manifest reconhecido (PASS), porém nenhum runner de teste
# declarado (test_runner_detected FAIL) e nenhum linter configurado (WARNING).
_PYPROJECT_MINIMAL = """\
[project]
name = "mock-cru"
version = "0.1.0"
"""

# Mock (b): repo completo (padrão do AC-1) — pytest declarado + [tool.ruff].
_PYPROJECT_COMPLETE = """\
[project]
name = "mock-completo"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.ruff]
line-length = 100
"""


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(cwd: Path) -> None:
    """git init + config LOCAL (não depende de config global do ambiente)."""
    _git(cwd, "init")
    _git(cwd, "config", "user.email", "preflight-e2e@example.com")
    _git(cwd, "config", "user.name", "Preflight E2E")


def _build_mock_a(root: Path) -> Path:
    """Repo Python cru: git init + 1 commit, pyproject mínimo sem pytest/ruff,
    SEM diretório tests/."""
    root.mkdir()
    _init_repo(root)
    (root / "pyproject.toml").write_text(_PYPROJECT_MINIMAL, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "baseline")
    return root


def _build_mock_b(root: Path) -> Path:
    """Repo completo (AC-1): git+commit, .gitignore, pyproject com pytest +
    [tool.ruff], tests/test_x.py."""
    root.mkdir()
    _init_repo(root)
    (root / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(_PYPROJECT_COMPLETE, encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-m", "baseline pré-harness")
    return root


def _run_preflight_cli(target: Path) -> subprocess.CompletedProcess[str]:
    """Invoca o COMANDO REAL do CLI via subprocess (mesmo interpretador)."""
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", "preflight", "--dir", str(target)],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
        env=env,
    )


def _has_actionable_fix(report: dict, category_id: str) -> bool:
    """True se a categoria tem >=1 check não-PASS com `fix` não-vazio."""
    for cat in report["categories"]:
        if cat["id"] != category_id:
            continue
        return any(c["status"] != "PASS" and c["fix"].strip() for c in cat["checks"])
    return False


def _write_evidence(cmd_a: str, out_a: str, cmd_b: str, out_b: str) -> None:
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = f"""\
# Evidência dogfood — preflight (gate final da demanda)

**Data:** 2026-07-17
**Teste:** `tests/e2e/test_preflight_e2e.py::test_preflight_e2e_dogfood`

Prova REAL exigida pelo ROADMAP: dois repositórios git de verdade criados em
disco (num `tmp_path` efêmero gerado pelo próprio teste) e avaliados pelo
COMANDO REAL do CLI via `subprocess.run` — o mesmo caminho que a skill
`/harness-creator:preflight` percorre. Os blocos JSON abaixo são o laudo real
de cada subprocess, com o único campo variável por rodada (o path absoluto
efêmero do `tmp_path`) redigido para um placeholder estável — sem isso, o
arquivo versionado sujaria a cada execução da suíte só pelo path, mesmo sem
nenhuma mudança real de comportamento.

Ambiente do subprocess: `PYTHONPATH={SRC_DIR.as_posix()}`,
interpretador `{sys.executable}`.

---

## Mock (a) — repo Python cru, sem runner de teste

`git init` + 1 commit, `pyproject.toml` mínimo (projeto Python válido, mas SEM
declarar `pytest` e SEM `[tool.ruff]`), SEM diretório `tests/`.

O `--dir` abaixo é um mock efêmero gerado pelo teste (path de `tmp_path`,
redigido para `<mock_a_cru>`), NÃO um caminho fixo do repositório:

```
{cmd_a}
```

Exit code: **1** — veredito **NOT_READY**.

Laudo real (stdout do subprocess):

```json
{out_a}
```

## Mock (b) — repo completo

`git init` + 1 commit, `.gitignore`, `pyproject.toml` com `pytest` em
`[project.optional-dependencies]` e `[tool.ruff]`, `tests/test_x.py`.

```
{cmd_b}
```

Exit code: **0** — veredito **READY**.

Laudo real (stdout do subprocess):

```json
{out_b}
```

---

## Interpretação

O **mock (a)** recebe veredito **NOT_READY** porque falta o runner de teste: o
analyzer não encontra `pytest` (nem qualquer runner) declarado no
`pyproject.toml`, então `test_runner_detected` é **FAIL** — um requisito
bloqueante do ciclo Plan→Work→Review, já que sem runner não há `verify_cmd`. O
laudo ainda acompanha fixes acionáveis nas categorias `tests` (declarar pytest)
e `lint` (configurar `[tool.ruff]`), provando que o veredito negativo vem com
próximos passos concretos, não só um "não".

O **mock (b)** recebe veredito **READY** (exit 0): git com baseline, manifest
reconhecido, runner de teste detectado e linter configurado — as quatro
categorias em PASS. O repositório tem o mínimo para o harness operar.
"""
    EVIDENCE_PATH.write_text(content, encoding="utf-8")


def test_preflight_e2e_dogfood(tmp_path: Path) -> None:
    # --- Mock (a): repo cru sem runner de teste ---
    mock_a = _build_mock_a(tmp_path / "mock_a_cru")
    proc_a = _run_preflight_cli(mock_a)

    assert proc_a.returncode == 1, f"esperado exit 1, veio {proc_a.returncode}\n{proc_a.stderr}"
    report_a = json.loads(proc_a.stdout)
    assert report_a["verdict"] == "NOT_READY"
    # fixes acionáveis presentes nas categorias tests e lint.
    assert _has_actionable_fix(report_a, "tests"), "categoria tests sem fix acionável"
    assert _has_actionable_fix(report_a, "lint"), "categoria lint sem fix acionável"

    # --- Mock (b): repo completo ---
    mock_b = _build_mock_b(tmp_path / "mock_b_completo")
    proc_b = _run_preflight_cli(mock_b)

    assert proc_b.returncode == 0, f"esperado exit 0, veio {proc_b.returncode}\n{proc_b.stderr}"
    report_b = json.loads(proc_b.stdout)
    assert report_b["verdict"] == "READY"

    # --- Evidência legível commitada (laudo real, path de tmp_path redigido
    # pra um placeholder estável — ver docstring de _write_evidence) ---
    cmd_a = f"{Path(sys.executable).name} -m harness.cli preflight --dir <mock_a_cru>"
    cmd_b = f"{Path(sys.executable).name} -m harness.cli preflight --dir <mock_b_completo>"
    redacted_a = {**report_a, "target": "<mock_a_cru>"}
    redacted_b = {**report_b, "target": "<mock_b_completo>"}
    _write_evidence(
        cmd_a, json.dumps(redacted_a, indent=2, ensure_ascii=False),
        cmd_b, json.dumps(redacted_b, indent=2, ensure_ascii=False),
    )

    assert EVIDENCE_PATH.is_file()
    written = EVIDENCE_PATH.read_text(encoding="utf-8")
    assert "NOT_READY" in written
    assert "READY" in written
