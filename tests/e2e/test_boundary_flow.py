"""E2E: fluxo completo Fase 2 — contrato -> sessão compilada -> boundary_guard
em ação, num repo sintético Python criado em `tmp_path`.

Espelha o padrão de `tests/e2e/test_contract_flow.py` (subprocess real via
`python -m harness.cli ...`, env `PYTHONPATH=src`, cwd controlado, sem
rede/Docker) e reaproveita o padrão de `_run_hook` de `tests/test_compiler.py`
(invocar o hook standalone gerado via subprocess com payload JSON no stdin).

Cobre:
    1. `analyze --dir` -> `.harness/repo-profile.json`.
    2. `spec.md` já aprovado + `Plans.md` com 1 tarefa -> `compile-contract`
       -> `.harness/feature_list.json` com 1 feature.
    3. Colisão com o mecanismo antigo: `compile --dir` (harness.yaml com
       `enforce_tdd: false`) registra o hook `guard_tests.py`; a recompilação
       via `compile-session --dir` remove essa entrada (o `boundary_guard.py`
       já cobre a proteção de teste por-tarefa) e sobra só a entrada nova.
    4. `compile-session --dir` -> `.claude/settings.json` com a superfície
       `allow` derivada do contrato (nunca `git push`) e `boundary_guard.py`
       registrado em `hooks.PreToolUse`.
    5. Invocação DIRETA do `boundary_guard.py` gerado via subprocess: allow
       dentro do raio do contrato, deny fora dele, deny para `git push`, deny
       para enfraquecimento de teste (arquivo de teste fora de `files[]`).

Um teste à parte prova que o runtime floor do `boundary_guard.py` nunca
depende de contrato ativo: instalado isoladamente num diretório sem
`.harness/feature_list.json`, `git push` e escrita em `.env` continuam DENY.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"

PYPROJECT_TOML = '[project]\nname = "demo-app"\nversion = "0.1.0"\ndependencies = ["pytest>=8.0"]\n'

APP_PY = "def health() -> dict:\n    return {\"status\": \"ok\"}\n"

TEST_APP_PY = (
    "from app import health\n\n\n"
    "def test_health():\n"
    "    assert health() == {\"status\": \"ok\"}\n"
)

APPROVED_SPEC = """---
slug: demo
approved_by: qa
approved_at: 2026-07-15T10:00:00Z
---

# Spec: Demo App

## Escopo
Implementar endpoint de health check.

## Critérios de aceitação
- `pytest tests/test_app.py -q` passa.
"""

PLANS_ONE_TASK = """## [T-01] Implementar endpoint de health check
- files: `src/app.py`
- verify: `pytest tests/test_app.py -q`
"""

# Mecanismo antigo (compiler.py): enforce_tdd False -> só guard_tests.py
# (Write|Edit) entra em hooks.PreToolUse, sem guard_test_runner.py (Bash) —
# assim a comparação "só sobra a do boundary_guard.py" após compile-session
# fica exata (uma única entrada Bash/Edit/Write remanescente).
LEGACY_HARNESS_YAML = """
governance:
  approval_policy: balanced
verification:
  enforce_tdd: false
  test_glob: "tests/**/*.py"
"""


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd),
    )


def _run_hook(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def _bootstrap_python_repo(root: Path) -> None:
    (root / "pyproject.toml").write_text(PYPROJECT_TOML, encoding="utf-8")
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "app.py").write_text(APP_PY, encoding="utf-8")
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_app.py").write_text(TEST_APP_PY, encoding="utf-8")


def test_boundary_flow_end_to_end(tmp_path: Path) -> None:
    project = tmp_path / "demo-app"
    project.mkdir()
    _bootstrap_python_repo(project)

    # ---- (1) analyze --dir sobre o repo sintético python ----
    analyze_proc = _run_cli(["analyze", "--dir", str(project)], cwd=project)
    assert analyze_proc.returncode == 0, analyze_proc.stderr

    profile_path = project / ".harness" / "repo-profile.json"
    assert profile_path.is_file()
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    assert profile["test_glob"]["value"] == "tests/**/*.py"

    # ---- (2) spec.md aprovado + Plans.md com 1 tarefa -> compile-contract ----
    contract_dir = project / ".harness" / "work" / "demo"
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "spec.md").write_text(APPROVED_SPEC, encoding="utf-8")
    (contract_dir / "Plans.md").write_text(PLANS_ONE_TASK, encoding="utf-8")

    compile_contract_proc = _run_cli(
        ["compile-contract", "--dir", str(project), "--slug", "demo"], cwd=project
    )
    assert compile_contract_proc.returncode == 0, compile_contract_proc.stderr

    feature_list_path = project / ".harness" / "feature_list.json"
    assert feature_list_path.is_file()
    feature_list = json.loads(feature_list_path.read_text(encoding="utf-8"))
    assert feature_list["contract"] == "demo"
    assert len(feature_list["features"]) == 1
    assert feature_list["features"][0]["id"] == "T-01"
    assert feature_list["features"][0]["files"] == ["src/app.py"]
    assert feature_list["features"][0]["verify_cmd"] == "pytest tests/test_app.py -q"

    # ---- (3) CENÁRIO ADICIONAL: colisão com o mecanismo antigo ----
    # `compile --dir` (harness.yaml mínimo) registra o hook guard_tests.py.
    (project / ".harness" / "harness.yaml").write_text(LEGACY_HARNESS_YAML, encoding="utf-8")
    legacy_compile_proc = _run_cli(["compile", "--dir", str(project)], cwd=project)
    assert legacy_compile_proc.returncode == 0, legacy_compile_proc.stderr

    settings_path = project / ".claude" / "settings.json"
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    pre_tool_use_after_legacy = json.dumps(settings["hooks"]["PreToolUse"])
    assert "guard_tests.py" in pre_tool_use_after_legacy

    # ---- (4) compile-session --dir: settings/boundary_guard coerentes ----
    compile_session_proc = _run_cli(["compile-session", "--dir", str(project)], cwd=project)
    assert compile_session_proc.returncode == 0, compile_session_proc.stderr

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    assert "Edit(src/app.py)" in allow
    assert "Bash(pytest tests/test_app.py -q)" in allow
    assert not any("git push" in rule for rule in allow)

    pre_tool_use = settings["hooks"]["PreToolUse"]
    pre_tool_use_dump = json.dumps(pre_tool_use)
    # guard_tests.py (mecanismo antigo) foi removido — os dois mecanismos não
    # coexistem duplicando o gate de proteção de teste.
    assert "guard_tests.py" not in pre_tool_use_dump
    assert "boundary_guard.py" in pre_tool_use_dump
    # só sobra a entrada nova (Edit|Write|Bash) — nada mais em PreToolUse.
    assert len(pre_tool_use) == 1
    assert pre_tool_use[0]["matcher"] == "Edit|Write|Bash"

    boundary_guard_path = project / ".harness" / "hooks" / "boundary_guard.py"
    assert boundary_guard_path.is_file()

    # ---- (5) invocação DIRETA do boundary_guard.py gerado ----
    allow_edit = _run_hook(boundary_guard_path, {
        "tool_name": "Edit", "cwd": str(project),
        "tool_input": {"file_path": "src/app.py"},
    })
    assert allow_edit["permissionDecision"] == "allow"

    deny_edit_outro = _run_hook(boundary_guard_path, {
        "tool_name": "Edit", "cwd": str(project),
        "tool_input": {"file_path": "src/outro.py"},
    })
    assert deny_edit_outro["permissionDecision"] == "deny"

    allow_bash_verify = _run_hook(boundary_guard_path, {
        "tool_name": "Bash", "cwd": str(project),
        "tool_input": {"command": "pytest tests/test_app.py -q"},
    })
    assert allow_bash_verify["permissionDecision"] == "allow"

    deny_bash_push = _run_hook(boundary_guard_path, {
        "tool_name": "Bash", "cwd": str(project),
        "tool_input": {"command": "git push origin main"},
    })
    assert deny_bash_push["permissionDecision"] == "deny"

    # tests/test_app.py casa test_glob mas NÃO está em files[] da T-01 ->
    # proteção contra enfraquecimento de teste nega a edição.
    deny_edit_test = _run_hook(boundary_guard_path, {
        "tool_name": "Edit", "cwd": str(project),
        "tool_input": {"file_path": "tests/test_app.py"},
    })
    assert deny_edit_test["permissionDecision"] == "deny"


def test_boundary_guard_floor_without_contract(tmp_path: Path) -> None:
    """Prova que o runtime floor nunca depende de contrato ativo.

    Instala o `boundary_guard.py` isoladamente (copiando `render_boundary_guard()`)
    num diretório sem NENHUM `.harness/feature_list.json` — nunca rodou
    `compile-contract` — e confirma que `git push` e escrita em `.env`
    continuam DENY mesmo assim.
    """
    sys.path.insert(0, str(SRC_DIR))
    try:
        from harness.boundary_guard import render_boundary_guard
    finally:
        sys.path.remove(str(SRC_DIR))

    assert not (tmp_path / ".harness" / "feature_list.json").exists()

    script_path = tmp_path / "boundary_guard.py"
    script_path.write_text(render_boundary_guard(), encoding="utf-8")

    deny_push = _run_hook(script_path, {
        "tool_name": "Bash", "cwd": str(tmp_path),
        "tool_input": {"command": "git push origin main"},
    })
    assert deny_push["permissionDecision"] == "deny"

    deny_env = _run_hook(script_path, {
        "tool_name": "Edit", "cwd": str(tmp_path),
        "tool_input": {"file_path": ".env"},
    })
    assert deny_env["permissionDecision"] == "deny"
