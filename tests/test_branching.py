"""Testes do branching (finding C do dogfood 2026-07-22): fluxo branch-first
gerenciado pela CLI — `ensure_contract_branch` cria/muda para
`contract/<slug>` antes de o compile-session instalar o guard, e os loaders
de `governance.branch_per_contract`/`governance.protected_branches` leem o
`.harness/harness.yaml` com degradação graciosa."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from harness.boundary_guard import load_protected_branches
from harness.branching import (
    BranchingError,
    ensure_contract_branch,
    load_branch_per_contract,
)


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def _init_repo(target: Path) -> None:
    _git(target, "init", "-b", "main")
    _git(target, "config", "user.email", "test@example.com")
    _git(target, "config", "user.name", "Test")
    (target / "README.md").write_text("x", encoding="utf-8")
    _git(target, "add", "README.md")
    _git(target, "commit", "-m", "init")


def _current_branch(target: Path) -> str:
    return _git(target, "rev-parse", "--abbrev-ref", "HEAD")


# ---------------------------------------------------------------------------
# ensure_contract_branch
# ---------------------------------------------------------------------------

def test_ensure_contract_branch_creates_and_switches(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_is_idempotent(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    ensure_contract_branch(tmp_path, "exemplo-feature")
    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_switches_to_existing_branch(tmp_path: Path) -> None:
    """Recompile do mesmo contrato = continuação: a branch já existe, só muda
    pra ela (switch sem -c)."""
    _init_repo(tmp_path)
    ensure_contract_branch(tmp_path, "exemplo-feature")
    _git(tmp_path, "switch", "main")

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert _current_branch(tmp_path) == "contract/exemplo-feature"


def test_ensure_contract_branch_aborts_on_dirty_tracked_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("modificado", encoding="utf-8")

    with pytest.raises(BranchingError, match="suja"):
        ensure_contract_branch(tmp_path, "exemplo-feature")
    assert _current_branch(tmp_path) == "main"


def test_ensure_contract_branch_aborts_on_staged_file(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "novo.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", "novo.py")

    with pytest.raises(BranchingError, match="suja"):
        ensure_contract_branch(tmp_path, "exemplo-feature")


def test_ensure_contract_branch_ignores_untracked_files(tmp_path: Path) -> None:
    """Untracked NÃO conta como sujeira: o fluxo real compile-contract →
    compile-session deixa .harness/** untracked, e é na branch de contrato
    que esses artefatos devem ser commitados (git switch preserva untracked)."""
    _init_repo(tmp_path)
    harness_dir = tmp_path / ".harness"
    harness_dir.mkdir()
    (harness_dir / "feature_list.json").write_text("{}", encoding="utf-8")

    result = ensure_contract_branch(tmp_path, "exemplo-feature")

    assert result == "contract/exemplo-feature"
    assert (harness_dir / "feature_list.json").is_file()


def test_ensure_contract_branch_rejects_non_git_dir(tmp_path: Path) -> None:
    with pytest.raises(BranchingError, match="git"):
        ensure_contract_branch(tmp_path, "exemplo-feature")


def test_ensure_contract_branch_rejects_repo_without_initial_commit(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-b", "main")

    with pytest.raises(BranchingError, match="commit inicial"):
        ensure_contract_branch(tmp_path, "exemplo-feature")


def test_ensure_contract_branch_rejects_empty_slug(tmp_path: Path) -> None:
    _init_repo(tmp_path)

    with pytest.raises(BranchingError, match="slug"):
        ensure_contract_branch(tmp_path, "")


# ---------------------------------------------------------------------------
# loaders (.harness/harness.yaml, degradação graciosa)
# ---------------------------------------------------------------------------

def test_load_branch_per_contract_defaults_true_without_yaml(tmp_path: Path) -> None:
    assert load_branch_per_contract(tmp_path) is True


def test_load_branch_per_contract_reads_override(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "governance:\n  branch_per_contract: false\n", encoding="utf-8"
    )

    assert load_branch_per_contract(tmp_path) is False


def test_load_branch_per_contract_defaults_true_on_invalid_yaml(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(":: nao e yaml valido ::[", encoding="utf-8")

    assert load_branch_per_contract(tmp_path) is True


def test_load_protected_branches_defaults_without_yaml(tmp_path: Path) -> None:
    assert load_protected_branches(tmp_path) == ["main", "homolog", "develop"]


def test_load_protected_branches_reads_override(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text(
        "governance:\n  protected_branches:\n    - trunk\n", encoding="utf-8"
    )

    assert load_protected_branches(tmp_path) == ["trunk"]
