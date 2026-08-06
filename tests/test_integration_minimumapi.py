"""Teste de integração do issue #72: cópia real de `C:\\Projetos\\MinimumAPI`
(repo .NET real, já governado — tem `.harness/harness.yaml` próprio) prova a
correção contra um projeto real fora do fixture sintético de testes.

Dois cenários, sempre sobre uma CÓPIA em `tmp_path` — o projeto original
nunca é aberto para escrita:

    A. `harness.yaml` removido da cópia — simula o cenário do issue (rodou
       `/harness-creator:plan` sem `/harness-creator:init` antes). Prova que
       os 3 avisos (compile-session, doctor, allowlist_yaml_hint) disparam.
    B. `harness.yaml` intacto (estado real do MinimumAPI) — prova que o
       fluxo já governado continua saindo limpo, sem os avisos novos
       aparecendo onde não deveriam (zero regressão).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

MINIMUMAPI_SOURCE = Path(r"C:\Projetos\MinimumAPI")

pytestmark = pytest.mark.skipif(
    not MINIMUMAPI_SOURCE.is_dir(),
    reason=f"fixture externa {MINIMUMAPI_SOURCE} não encontrada nesta máquina",
)

# bin/obj/db/logs não são relevantes para o harness e só pesam a cópia.
_EXCLUDE_DIR_NAMES = {"bin", "obj"}
_EXCLUDE_SUFFIXES = (".db", ".db-shm", ".db-wal")
_EXCLUDE_NAME_PREFIXES = ("api_",)


def _copy_minimumapi(dest: Path) -> Path:
    def _ignore(dir_path: str, names: list[str]) -> list[str]:
        ignored = []
        for name in names:
            full = Path(dir_path) / name
            if full.is_dir() and name in _EXCLUDE_DIR_NAMES:
                ignored.append(name)
            elif full.is_file() and (
                name.endswith(_EXCLUDE_SUFFIXES) or name.startswith(_EXCLUDE_NAME_PREFIXES)
            ):
                ignored.append(name)
        return ignored

    shutil.copytree(MINIMUMAPI_SOURCE, dest, ignore=_ignore)
    return dest


def _write_feature_list(target: Path) -> None:
    path = target / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract": "smoke",
                "compiled_at": "2026-08-06T00:00:00+00:00",
                "features": [
                    {
                        "id": "T-01",
                        "desc": "smoke",
                        "files": ["Program.cs"],
                        "verify_cmd": "dotnet build",
                        "depends": [],
                        "passes": False,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


# ---------------- cenário A: sem harness.yaml (issue #72) ----------------

def test_compile_session_warns_on_real_repo_copy_without_harness_yaml(tmp_path: Path) -> None:
    from harness.session_permissions import compile_session_permissions, missing_harness_yaml_warning

    copy = _copy_minimumapi(tmp_path / "repo")
    (copy / ".harness" / "harness.yaml").unlink()
    _write_feature_list(copy)

    compile_session_permissions(copy)  # não levanta, mesmo sem harness.yaml
    warning = missing_harness_yaml_warning(copy)
    assert warning is not None
    assert "/harness-creator:init" in warning

    # a cópia foi mutada (unlink), o original não.
    original_yaml = MINIMUMAPI_SOURCE / ".harness" / "harness.yaml"
    assert original_yaml.is_file()
    assert "governance:" in original_yaml.read_text(encoding="utf-8")


def test_doctor_notes_partial_governance_on_real_repo_copy_without_harness_yaml(tmp_path: Path) -> None:
    from harness.doctor import run_doctor

    copy = _copy_minimumapi(tmp_path / "repo")
    (copy / ".harness" / "harness.yaml").unlink()
    _write_feature_list(copy)

    report = run_doctor(copy, plugins_file=tmp_path / "no-such-file.json")
    # nota (não issue) especificamente pela ausência de harness.yaml — outras
    # divergências de versão da cópia real (compiled_version desatualizado)
    # são um issue independente, fora do escopo desta correção.
    assert any("/harness-creator:init" in n for n in report.notes)


def test_allowlist_yaml_hint_includes_governance_on_real_repo_copy_without_harness_yaml(
    tmp_path: Path,
) -> None:
    from harness.boundary_guard import allowlist_yaml_hint

    copy = _copy_minimumapi(tmp_path / "repo")
    (copy / ".harness" / "harness.yaml").unlink()

    hint = allowlist_yaml_hint("dotnet ef migrations add Init", repo_root=copy)
    assert "governance:\n  extra_allowed_commands:" in hint


# ---------------- cenário B: harness.yaml intacto — sem regressão ----------------

def test_compile_session_no_warning_on_real_repo_copy_with_harness_yaml_intact(tmp_path: Path) -> None:
    from harness.session_permissions import compile_session_permissions, missing_harness_yaml_warning

    copy = _copy_minimumapi(tmp_path / "repo")
    assert (copy / ".harness" / "harness.yaml").is_file()
    _write_feature_list(copy)

    compile_session_permissions(copy)
    assert missing_harness_yaml_warning(copy) is None


def test_doctor_has_no_partial_governance_note_on_real_repo_copy_with_harness_yaml_intact(
    tmp_path: Path,
) -> None:
    from harness.doctor import run_doctor

    copy = _copy_minimumapi(tmp_path / "repo")
    _write_feature_list(copy)

    report = run_doctor(copy, plugins_file=tmp_path / "no-such-file.json")
    assert not any("/harness-creator:init" in n for n in report.notes)


def test_allowlist_yaml_hint_omits_governance_on_real_repo_copy_with_harness_yaml_intact(
    tmp_path: Path,
) -> None:
    from harness.boundary_guard import allowlist_yaml_hint

    copy = _copy_minimumapi(tmp_path / "repo")

    hint = allowlist_yaml_hint("dotnet ef migrations add Init", repo_root=copy)
    assert "\ngovernance:" not in hint
