"""E2E: fluxo de contrato completo — analyze -> spec/Plans -> gate de
aprovação -> aprovação -> compile-contract — via subprocess, num repo
sintético Node criado em tmp_path.

Simula o ciclo de vida real de um contrato (Fase 1 do ROADMAP): primeiro o
`analyze` lê fatos do repo-alvo (linguagem, package manager, test_command);
depois um `spec.md`/`Plans.md` é escrito à mão (como faria a skill `plan`);
o gate de aprovação barra a compilação até `approved_by`/`approved_at`
serem preenchidos; por fim a recompilação preserva `passes: true` de
tarefas cuja identidade (`id`/`files`/`verify_cmd`) não mudou.

Roda a CLI real via subprocess (`python -m harness.cli ...`), como na vida
real — sem rede, sem Docker, mesmo padrão de `test_minimumapi.py`.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SRC_DIR = Path(__file__).resolve().parents[2] / "src"

PACKAGE_JSON = json.dumps({
    "name": "cobaia-node",
    "version": "1.0.0",
    "scripts": {"test": "node --test src"},
})

INDEX_TEST_JS = "test('ok', () => {});\n"

UNAPPROVED_SPEC = """---
slug: demo
approved_by:
approved_at:
---

# Spec: Demo Feature

## Escopo
Adicionar endpoint de health check e cobrir com teste.

## Critérios de aceitação
- `npm test` passa.
"""

APPROVED_SPEC = """---
slug: demo
approved_by: qa
approved_at: 2026-07-15T10:00:00Z
---

# Spec: Demo Feature

## Escopo
Adicionar endpoint de health check e cobrir com teste.

## Critérios de aceitação
- `npm test` passa.
"""

PLANS_TWO_TASKS = """## [T-01] Criar endpoint de health check
- files: `src/index.js`
- verify: `npm test`

## [T-02] Cobrir endpoint com teste
- files: `src/index.test.js`
- verify: `npm test`
"""


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(SRC_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=60, env=env, cwd=str(cwd),
    )


def _bootstrap_node_repo(root: Path) -> None:
    (root / "package.json").write_text(PACKAGE_JSON, encoding="utf-8")
    (root / "package-lock.json").write_text("{}", encoding="utf-8")
    src_dir = root / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    (src_dir / "index.test.js").write_text(INDEX_TEST_JS, encoding="utf-8")


def _write_contract(root: Path, slug: str, spec_text: str, plans_text: str) -> None:
    contract_dir = root / ".harness" / "work" / slug
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    (contract_dir / "Plans.md").write_text(plans_text, encoding="utf-8")


def test_contract_flow_end_to_end(tmp_path: Path) -> None:
    project = tmp_path / "cobaia-node"
    project.mkdir()
    _bootstrap_node_repo(project)

    # ---- (1) analyze --dir sobre o repo sintético node ----
    analyze_proc = _run(["analyze", "--dir", str(project)], cwd=project)
    assert analyze_proc.returncode == 0, analyze_proc.stderr

    profile = json.loads(analyze_proc.stdout)
    assert "javascript" in {f["value"] for f in profile["languages"]}
    assert profile["package_manager"]["value"] == "npm"
    assert profile["test_command"]["value"] == "node --test src"

    profile_path = project / ".harness" / "repo-profile.json"
    assert profile_path.is_file()
    on_disk = json.loads(profile_path.read_text(encoding="utf-8"))
    assert on_disk["test_command"]["value"] == "node --test src"

    # ---- (2) spec.md SEM aprovação + Plans.md válido -> gate reprova ----
    _write_contract(project, "demo", UNAPPROVED_SPEC, PLANS_TWO_TASKS)

    reproved_proc = _run(
        ["compile-contract", "--dir", str(project), "--slug", "demo"], cwd=project
    )
    assert reproved_proc.returncode == 1
    assert "não aprovado" in reproved_proc.stderr

    feature_list_path = project / ".harness" / "feature_list.json"
    assert not feature_list_path.exists()

    # ---- (3) preenche approved_by/approved_at -> recompila com sucesso ----
    _write_contract(project, "demo", APPROVED_SPEC, PLANS_TWO_TASKS)

    approved_proc = _run(
        ["compile-contract", "--dir", str(project), "--slug", "demo"], cwd=project
    )
    assert approved_proc.returncode == 0, approved_proc.stderr

    assert feature_list_path.is_file()
    feature_list = json.loads(feature_list_path.read_text(encoding="utf-8"))
    assert feature_list["contract"] == "demo"
    assert len(feature_list["features"]) == 2
    by_id = {f["id"]: f for f in feature_list["features"]}
    assert by_id["T-01"]["passes"] is False
    assert by_id["T-02"]["passes"] is False

    # ---- (4) marca T-01 passes:true à mão, muda desc da T-02, recompila ----
    feature_list["features"] = [
        {**f, "passes": True} if f["id"] == "T-01" else f
        for f in feature_list["features"]
    ]
    feature_list_path.write_text(
        json.dumps(feature_list, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    plans_desc_changed = PLANS_TWO_TASKS.replace(
        "## [T-02] Cobrir endpoint com teste",
        "## [T-02] Cobrir endpoint com teste (revisado)",
    )
    _write_contract(project, "demo", APPROVED_SPEC, plans_desc_changed)

    recompiled_proc = _run(
        ["compile-contract", "--dir", str(project), "--slug", "demo"], cwd=project
    )
    assert recompiled_proc.returncode == 0, recompiled_proc.stderr

    recompiled = json.loads(feature_list_path.read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in recompiled["features"]}
    assert by_id["T-01"]["passes"] is True
    assert by_id["T-02"]["passes"] is False
    assert by_id["T-02"]["desc"] == "Cobrir endpoint com teste (revisado)"
