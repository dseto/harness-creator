"""Teste de integração do issue #72 / contrato `setup-fail-closed-sem-init`
(T-05): cópia real de `C:\\Projetos\\MinimumAPI` (repo .NET real, já
governado — tem `.harness/harness.yaml` próprio) prova a correção contra um
projeto real fora do fixture sintético de testes.

Dois cenários, sempre sobre uma CÓPIA em `tmp_path` — o projeto original
nunca é aberto para escrita:

    A. `harness.yaml` removido da cópia — simula o cenário do issue (rodou
       `/harness-creator:plan` sem `/harness-creator:init` antes).
       - `compile-session` (via `harness.cli.main`): a v0.30.0 compilava com
         defaults e só avisava em stderr; o contrato `setup-fail-closed-sem-init`
         (T-02) reverteu isso — agora RECUSA (exit 1) com mensagem didática,
         ANTES de escrever qualquer artefato.
       - `harness status`/`harness doctor` (via `run_doctor`) e o hint de
         `allowlist_yaml_hint`: continuam apenas REPORTANDO a governança
         parcial (read-only, exit 0) — essa parte do contrato v0.30.0
         segue valendo, não foi revertida.
    B. `harness.yaml` intacto (estado real do MinimumAPI) — prova que o
       fluxo já governado continua saindo limpo, sem os erros/avisos novos
       aparecendo onde não deveriam (zero regressão).
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from harness.cli import main

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

def test_compile_session_refuses_real_repo_copy_without_harness_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-05 (contrato `setup-fail-closed-sem-init`): substitui o antigo teste
    de aviso (v0.30.0) pela prova da recusa fail-closed que o gate de setup
    (T-02, `require_harness_yaml_installed`) introduziu em `compile-session`.

    A cópia do MinimumAPI já É um repo governado de verdade — já tem
    `.claude/settings.local.json`, `.harness/hooks/*.py` e `AGENTS.md`
    gravados por um `/harness-creator:init` real anterior. Por isso a prova
    de "nada foi escrito" não pode ser ausência de arquivo (eles já
    existem); é CONTEÚDO inalterado: tira um retrato de bytes desses
    artefatos antes de rodar `compile-session` e confere que nenhum foi
    regravado depois da recusa."""
    copy = _copy_minimumapi(tmp_path / "repo")
    (copy / ".harness" / "harness.yaml").unlink()
    _write_feature_list(copy)

    watched_paths = [
        copy / ".claude" / "settings.local.json",
        copy / ".harness" / "hooks" / "boundary_guard.py",
        copy / "AGENTS.md",
    ]
    # os três já existem na cópia real (repo já governado antes deste teste).
    before = {path: path.read_bytes() for path in watched_paths}
    assert len(before) == len(watched_paths)

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(copy)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")
    assert ".harness/harness.yaml" in err
    assert "/harness-creator:init" in err

    # nenhum artefato foi regravado -- o gate dispara antes de qualquer escrita.
    for path, content_before in before.items():
        assert path.read_bytes() == content_before

    # a cópia foi mutada (unlink), o original não.
    original_yaml = MINIMUMAPI_SOURCE / ".harness" / "harness.yaml"
    assert original_yaml.is_file()
    assert "governance:" in original_yaml.read_text(encoding="utf-8")


def test_doctor_notes_partial_governance_on_real_repo_copy_without_harness_yaml(tmp_path: Path) -> None:
    """Preservado do contrato v0.30.0 (T-05 não reverte esta parte): `harness
    doctor` é diagnóstico, read-only, e continua apenas REPORTANDO governança
    parcial (nota, exit 0) — o gate fail-closed do T-02 é só para os
    comandos que ESCREVEM (`compile-contract`/`compile-session`)."""
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
