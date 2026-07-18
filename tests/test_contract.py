"""Testes do contrato: spec.md + Plans.md -> feature_list.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.contract import (
    ContractError,
    ContractNotApprovedError,
    Task,
    compile_contract,
    get_stop_conditions,
    parse_plans,
    parse_spec,
)

APPROVED_SPEC = """---
slug: exemplo-feature
approved_by: alice
approved_at: 2026-07-15T10:00:00Z
---

# Spec: Exemplo de Feature

## Escopo
Descrição do que deve ser feito.
"""

SPEC_WITH_STOP_CONDITIONS = """---
slug: exemplo-feature
approved_by: alice
approved_at: 2026-07-15T10:00:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste"
  - "verify_cmd nao existe no profile do repo"
---

# Spec
"""

UNAPPROVED_SPEC = """---
slug: exemplo-feature
approved_by:
approved_at:
---

# Spec sem aprovacao
"""

BASIC_PLANS = """## [T-01] Criar modulo de configuracao
- files: `src/harness/config.py`, `tests/test_config.py`
- verify: `pytest tests/test_config.py -q`

## [T-02] Integrar configuracao no compilador
- files: `src/harness/compiler.py`
- verify: `pytest tests/test_compiler.py -q`
- depends: T-01
"""

PLANS_MISSING_VERIFY = """## [T-01] Tarefa sem verify
- files: `src/harness/x.py`
"""


def _write_contract(target: Path, slug: str, spec_text: str, plans_text: str) -> Path:
    contract_dir = target / ".harness" / "work" / slug
    contract_dir.mkdir(parents=True, exist_ok=True)
    (contract_dir / "spec.md").write_text(spec_text, encoding="utf-8")
    (contract_dir / "Plans.md").write_text(plans_text, encoding="utf-8")
    return contract_dir


# ---------------- parse_spec ----------------

def test_parse_spec_returns_frontmatter_dict(tmp_path: Path) -> None:
    contract_dir = _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, BASIC_PLANS)
    data = parse_spec(contract_dir / "spec.md")
    assert data["slug"] == "exemplo-feature"
    assert data["approved_by"] == "alice"
    assert data["approved_at"] is not None


def test_parse_spec_returns_stop_conditions_when_present(tmp_path: Path) -> None:
    contract_dir = _write_contract(
        tmp_path, "exemplo-feature", SPEC_WITH_STOP_CONDITIONS, BASIC_PLANS
    )
    data = parse_spec(contract_dir / "spec.md")
    assert "stop_conditions" in data
    assert len(data["stop_conditions"]) == 2


def test_parse_spec_malformed_missing_frontmatter(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("# Sem frontmatter\n", encoding="utf-8")
    with pytest.raises(ContractError):
        parse_spec(spec_path)


def test_parse_spec_malformed_unclosed_frontmatter(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text("---\nslug: x\n\n# corpo\n", encoding="utf-8")
    with pytest.raises(ContractError):
        parse_spec(spec_path)


def test_parse_spec_tolerates_utf8_bom(tmp_path: Path) -> None:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(APPROVED_SPEC, encoding="utf-8-sig")
    data = parse_spec(spec_path)
    assert data["slug"] == "exemplo-feature"


# ---------------- get_stop_conditions ----------------

def test_get_stop_conditions_returns_list_when_present(tmp_path: Path) -> None:
    contract_dir = _write_contract(
        tmp_path, "exemplo-feature", SPEC_WITH_STOP_CONDITIONS, BASIC_PLANS
    )
    conditions = get_stop_conditions(contract_dir / "spec.md")
    assert conditions == [
        "3 falhas consecutivas da mesma suite de teste",
        "verify_cmd nao existe no profile do repo",
    ]


def test_get_stop_conditions_returns_empty_list_when_key_absent(tmp_path: Path) -> None:
    contract_dir = _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, BASIC_PLANS)
    conditions = get_stop_conditions(contract_dir / "spec.md")
    assert conditions == []


# ---------------- parse_plans ----------------

def test_parse_plans_extracts_tasks_with_files_and_verify(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(BASIC_PLANS, encoding="utf-8")
    tasks = parse_plans(plans_path)
    assert [t.id for t in tasks] == ["T-01", "T-02"]
    assert tasks[0].files == ["src/harness/config.py", "tests/test_config.py"]
    assert tasks[0].verify_cmd == "pytest tests/test_config.py -q"
    assert tasks[0].desc == "Criar modulo de configuracao"


def test_parse_plans_tolerates_utf8_bom(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(BASIC_PLANS, encoding="utf-8-sig")
    tasks = parse_plans(plans_path)
    assert [t.id for t in tasks] == ["T-01", "T-02"]


def test_parse_plans_depends_present_is_parsed(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(BASIC_PLANS, encoding="utf-8")
    tasks = parse_plans(plans_path)
    task_by_id = {t.id: t for t in tasks}
    assert task_by_id["T-02"].depends == ["T-01"]


def test_parse_plans_depends_absent_defaults_to_empty_list(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(BASIC_PLANS, encoding="utf-8")
    tasks = parse_plans(plans_path)
    task_by_id = {t.id: t for t in tasks}
    assert task_by_id["T-01"].depends == []


def test_parse_plans_cwd_present_is_parsed(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(
        "## [T-03] Testar frontend\n"
        "- files: `frontend/src/x.ts`\n"
        "- verify: `ng test`\n"
        "- cwd: `frontend`\n",
        encoding="utf-8",
    )
    tasks = parse_plans(plans_path)
    assert tasks[0].cwd == "frontend"


def test_parse_plans_cwd_absent_defaults_to_none(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(BASIC_PLANS, encoding="utf-8")
    tasks = parse_plans(plans_path)
    assert tasks[0].cwd is None


def test_parse_plans_missing_verify_raises_naming_task(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(PLANS_MISSING_VERIFY, encoding="utf-8")
    with pytest.raises(ContractError, match="T-01"):
        parse_plans(plans_path)


def test_parse_plans_missing_files_raises_naming_task(tmp_path: Path) -> None:
    plans_path = tmp_path / "Plans.md"
    plans_path.write_text(
        "## [T-02] Tarefa sem files\n- verify: `pytest -q`\n", encoding="utf-8"
    )
    with pytest.raises(ContractError, match="T-02"):
        parse_plans(plans_path)


# ---------------- compile_contract ----------------

def test_compile_contract_approved_compiles_with_correct_schema(tmp_path: Path) -> None:
    _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, BASIC_PLANS)
    out_path = compile_contract(tmp_path, "exemplo-feature")

    assert out_path == tmp_path / ".harness" / "feature_list.json"
    data = json.loads(out_path.read_text(encoding="utf-8"))
    assert data["contract"] == "exemplo-feature"
    assert "compiled_at" in data
    assert len(data["features"]) == 2

    t01 = next(f for f in data["features"] if f["id"] == "T-01")
    assert t01["desc"] == "Criar modulo de configuracao"
    assert t01["files"] == ["src/harness/config.py", "tests/test_config.py"]
    assert t01["verify_cmd"] == "pytest tests/test_config.py -q"
    assert t01["depends"] == []
    assert t01["cwd"] is None
    assert t01["passes"] is False

    t02 = next(f for f in data["features"] if f["id"] == "T-02")
    assert t02["depends"] == ["T-01"]


def test_compile_contract_not_approved_raises_and_writes_nothing(tmp_path: Path) -> None:
    _write_contract(tmp_path, "exemplo-feature", UNAPPROVED_SPEC, BASIC_PLANS)
    with pytest.raises(ContractNotApprovedError):
        compile_contract(tmp_path, "exemplo-feature")

    assert not (tmp_path / ".harness" / "feature_list.json").exists()


def test_recompile_preserves_passes_for_unchanged_task_and_resets_changed(
    tmp_path: Path,
) -> None:
    _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, BASIC_PLANS)
    out_path = compile_contract(tmp_path, "exemplo-feature")

    # Simula evidencia registrada (harness verify) marcando as duas como passes:true.
    data = json.loads(out_path.read_text(encoding="utf-8"))
    for feature in data["features"]:
        feature["passes"] = True
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Muda o verify_cmd de T-02 (T-01 permanece identico).
    changed_plans = BASIC_PLANS.replace(
        "verify: `pytest tests/test_compiler.py -q`",
        "verify: `pytest tests/test_compiler.py -q --maxfail=1`",
    )
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    (contract_dir / "Plans.md").write_text(changed_plans, encoding="utf-8")

    compile_contract(tmp_path, "exemplo-feature")
    recompiled = json.loads(out_path.read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in recompiled["features"]}
    assert by_id["T-01"]["passes"] is True
    assert by_id["T-02"]["passes"] is False


def test_recompile_only_desc_change_preserves_passes(tmp_path: Path) -> None:
    _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, BASIC_PLANS)
    out_path = compile_contract(tmp_path, "exemplo-feature")

    data = json.loads(out_path.read_text(encoding="utf-8"))
    for feature in data["features"]:
        feature["passes"] = True
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # So a descricao de T-01 muda; id/files/verify_cmd permanecem iguais.
    changed_plans = BASIC_PLANS.replace(
        "## [T-01] Criar modulo de configuracao",
        "## [T-01] Criar modulo de configuracao (nome revisado)",
    )
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    (contract_dir / "Plans.md").write_text(changed_plans, encoding="utf-8")

    compile_contract(tmp_path, "exemplo-feature")
    recompiled = json.loads(out_path.read_text(encoding="utf-8"))
    by_id = {f["id"]: f for f in recompiled["features"]}
    assert by_id["T-01"]["passes"] is True
    assert by_id["T-01"]["desc"] == "Criar modulo de configuracao (nome revisado)"


def test_recompile_cwd_change_invalidates_passes(tmp_path: Path) -> None:
    plans_with_cwd = (
        "## [T-01] Testar frontend\n"
        "- files: `frontend/src/x.ts`\n"
        "- verify: `ng test`\n"
        "- cwd: `frontend`\n"
    )
    _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, plans_with_cwd)
    out_path = compile_contract(tmp_path, "exemplo-feature")

    data = json.loads(out_path.read_text(encoding="utf-8"))
    data["features"][0]["passes"] = True
    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # Muda so o cwd (id/files/verify_cmd permanecem iguais).
    changed_plans = plans_with_cwd.replace("- cwd: `frontend`\n", "- cwd: `frontend-v2`\n")
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    (contract_dir / "Plans.md").write_text(changed_plans, encoding="utf-8")

    compile_contract(tmp_path, "exemplo-feature")
    recompiled = json.loads(out_path.read_text(encoding="utf-8"))
    assert recompiled["features"][0]["cwd"] == "frontend-v2"
    assert recompiled["features"][0]["passes"] is False


def test_recompile_removed_task_disappears_from_output(tmp_path: Path) -> None:
    _write_contract(tmp_path, "exemplo-feature", APPROVED_SPEC, BASIC_PLANS)
    out_path = compile_contract(tmp_path, "exemplo-feature")

    only_t01_plans = """## [T-01] Criar modulo de configuracao
- files: `src/harness/config.py`, `tests/test_config.py`
- verify: `pytest tests/test_config.py -q`
"""
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    (contract_dir / "Plans.md").write_text(only_t01_plans, encoding="utf-8")

    compile_contract(tmp_path, "exemplo-feature")
    recompiled = json.loads(out_path.read_text(encoding="utf-8"))
    ids = [f["id"] for f in recompiled["features"]]
    assert ids == ["T-01"]


def test_task_dataclass_defaults_depends_to_empty_list() -> None:
    task = Task(id="T-01", desc="x", files=["a.py"], verify_cmd="pytest -q")
    assert task.depends == []
