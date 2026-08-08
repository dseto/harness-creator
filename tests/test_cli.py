"""Testes de CLI: subcomandos `harness analyze` e `harness compile-contract`.

Arquivo dedicado (não anexado a test_analyzer.py/test_contract.py) para não
colidir com tarefas concorrentes que editam analyzer.py/contract.py."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.cli import main


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


APPROVED_SPEC = """---
slug: exemplo-feature
approved_by: alice
approved_at: 2026-07-15T10:00:00Z
---

# Spec: Exemplo de Feature
"""

UNAPPROVED_SPEC = """---
slug: exemplo-feature
approved_by:
approved_at:
---

# Spec sem aprovacao
"""

BASIC_PLANS = """## [T-01] Criar modulo de configuracao
- files: `src/harness/config.py`
- verify: `pytest tests/test_config.py -q`
"""


def test_analyze_subcommand_prints_profile_json_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample"\ndependencies = ["pytest>=8.0"]\n')
    _write(tmp_path / "uv.lock", "# lockfile fake\n")
    _write(tmp_path / "tests" / "test_sample.py", "def test_ok():\n    assert True\n")

    monkeypatch.setattr(sys, "argv", ["harness", "analyze", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert "languages" in data
    assert any(f["value"] == "python" for f in data["languages"])

    profile_path = tmp_path / ".harness" / "repo-profile.json"
    assert profile_path.is_file()


def test_analyze_subcommand_exits_zero_even_with_unknowns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Diretório vazio: nenhum manifest reconhecido -> só unknowns, não é erro.
    monkeypatch.setattr(sys, "argv", ["harness", "analyze", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["unknowns"]


def test_compile_contract_subcommand_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-contract", "--dir", str(tmp_path), "--slug", "exemplo-feature"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["contract"] == "exemplo-feature"
    assert data["features"] == 1
    assert data["feature_list"].endswith("feature_list.json")

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    assert feature_list_path.is_file()


def test_compile_contract_subcommand_not_approved_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", UNAPPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-contract", "--dir", str(tmp_path), "--slug", "exemplo-feature"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_compile_contract_subcommand_missing_spec_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-contract", "--dir", str(tmp_path), "--slug", "inexistente"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_task_add_file_subcommand_adds_and_recompiles(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "novo/path.ts",
         "--dir", str(tmp_path), "--slug", "exemplo-feature"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["contract"] == "exemplo-feature"
    assert data["task_id"] == "T-01"
    assert data["path"] == "novo/path.ts"
    assert data["added"] is True

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    t01 = next(f for f in feature_data["features"] if f["id"] == "T-01")
    assert "novo/path.ts" in t01["files"]


def test_task_add_file_subcommand_unknown_task_exits_one_and_leaves_plans_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)
    plans_path = contract_dir / "Plans.md"
    before = plans_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-99", "novo/path.ts",
         "--dir", str(tmp_path), "--slug", "exemplo-feature"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")
    assert plans_path.read_text(encoding="utf-8") == before
    assert not (tmp_path / ".harness" / "feature_list.json").exists()


def test_task_add_file_subcommand_path_already_present_is_noop_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)
    plans_path = contract_dir / "Plans.md"

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "src/harness/config.py",
         "--dir", str(tmp_path), "--slug", "exemplo-feature"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    err = capsys.readouterr().err
    assert "já está" in err

    tasks_after = plans_path.read_text(encoding="utf-8")
    # sem duplicação: o path só aparece uma vez no bullet files: de T-01
    assert tasks_after.count("src/harness/config.py") == 1


def test_task_add_file_subcommand_missing_contract_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "novo/path.ts",
         "--dir", str(tmp_path), "--slug", "inexistente"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_task_add_file_subcommand_unapproved_contract_edits_plans_but_blocks_recompile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", UNAPPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)
    plans_path = contract_dir / "Plans.md"

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "novo/path.ts",
         "--dir", str(tmp_path), "--slug", "exemplo-feature"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    # Plans.md É editado (não é o gate que essa etapa protege)...
    assert "novo/path.ts" in plans_path.read_text(encoding="utf-8")
    # ...mas a recompilação do feature_list.json continua barrada sem
    # aprovação — o gate approved_by/approved_at não é contornado.
    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")
    assert not (tmp_path / ".harness" / "feature_list.json").exists()


def test_task_add_file_subcommand_infers_slug_with_single_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "novo/path.ts", "--dir", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["contract"] == "exemplo-feature"

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    feature_data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    t01 = next(f for f in feature_data["features"] if f["id"] == "T-01")
    assert "novo/path.ts" in t01["files"]


def test_task_add_file_subcommand_without_slug_and_multiple_contracts_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for slug in ("exemplo-feature", "outra-feature"):
        contract_dir = tmp_path / ".harness" / "work" / slug
        _write(contract_dir / "spec.md", APPROVED_SPEC.replace("exemplo-feature", slug))
        _write(contract_dir / "Plans.md", BASIC_PLANS)

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "novo/path.ts", "--dir", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")
    assert "exemplo-feature" in err and "outra-feature" in err
    assert not (tmp_path / ".harness" / "feature_list.json").exists()


def test_task_add_file_subcommand_without_slug_and_no_contracts_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv",
        ["harness", "task", "add-file", "T-01", "novo/path.ts", "--dir", str(tmp_path)],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def _init_git_repo(target: Path) -> None:
    import subprocess

    def _git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=target, capture_output=True, text=True, check=True)

    _git("init", "-b", "main")
    _git("config", "user.email", "test@example.com")
    _git("config", "user.name", "Test")
    _git("add", "-A")
    _git("commit", "--allow-empty", "-m", "init")


def _prepare_compile_session_fixture(tmp_path: Path) -> None:
    from harness.analyzer import analyze_project, write_profile
    from harness.contract import compile_contract

    contract_dir = tmp_path / ".harness" / "work" / "exemplo-feature"
    _write(contract_dir / "spec.md", APPROVED_SPEC)
    _write(contract_dir / "Plans.md", BASIC_PLANS)
    _write(tmp_path / "pyproject.toml", '[project]\nname = "sample"\ndependencies = ["pytest>=8.0"]\n')
    _write(tmp_path / "uv.lock", "# lockfile fake\n")
    _write(tmp_path / "tests" / "test_config.py", "def test_ok():\n    assert True\n")

    compile_contract(tmp_path, "exemplo-feature")
    profile = analyze_project(tmp_path)
    write_profile(profile, tmp_path)


def test_compile_session_subcommand_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_git_repo(tmp_path)
    _prepare_compile_session_fixture(tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    # branch_per_contract default true: compile-session criou e mudou pra
    # branch de contrato antes de instalar qualquer coisa (finding C).
    assert data["branch"] == "contract/exemplo-feature"
    assert data["settings"].endswith("settings.local.json")
    assert data["boundary_guard"].endswith("boundary_guard.py")
    assert data["agents_md"].endswith("AGENTS.md")
    assert data["lifecycle_detail"].endswith("LIFECYCLE.md")
    assert data["session_start_hook"].endswith("session_start.py")
    assert data["stop_hook"].endswith("stop_hook.py")
    assert any(p.endswith("init.sh") for p in data["templates"])
    assert any(p.endswith("init.ps1") for p in data["templates"])

    assert (tmp_path / ".claude" / "settings.local.json").is_file()
    assert (tmp_path / ".harness" / "hooks" / "boundary_guard.py").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".harness" / "LIFECYCLE.md").is_file()
    assert (tmp_path / ".harness/progress.md").is_file()
    assert (tmp_path / ".harness" / "init.sh").is_file()
    assert (tmp_path / ".harness" / "init.ps1").is_file()
    # Item 6 do laudo de footprint: a raiz do alvo recebe só AGENTS.md.
    assert not (tmp_path / "init.sh").exists()
    assert not (tmp_path / "init.ps1").exists()
    assert not (tmp_path / "claude-progress.md").exists()
    assert data["templates_preserved"] == []
    assert (tmp_path / ".harness" / "hooks" / "session_start.py").is_file()
    assert (tmp_path / ".harness" / "hooks" / "stop_hook.py").is_file()


def test_compile_session_warns_when_harness_yaml_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Issue #72: repo que nunca rodou `/harness-creator:init` (sem
    `.harness/harness.yaml`) continua compilando a sessão — mas avisa em
    stderr que TDD/política de aprovação ficaram de fora."""
    _init_git_repo(tmp_path)
    _prepare_compile_session_fixture(tmp_path)
    assert not (tmp_path / ".harness" / "harness.yaml").exists()

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    err = capsys.readouterr().err
    assert ".harness/harness.yaml" in err
    assert "/harness-creator:init" in err


def test_compile_session_no_yaml_warning_when_harness_yaml_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _init_git_repo(tmp_path)
    _prepare_compile_session_fixture(tmp_path)
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.write_text("governance:\n  approval_policy: default\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    err = capsys.readouterr().err
    assert "harness.yaml" not in err


def test_compile_session_subcommand_missing_feature_list_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_compile_session_dirty_tree_aborts_before_writing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding C: com branch_per_contract ativo, tracked modificado no
    momento do compile-session aborta ANTES de qualquer escrita — nunca
    criar branch carregando sujeira de outro contexto."""
    _init_git_repo(tmp_path)
    _prepare_compile_session_fixture(tmp_path)
    (tmp_path / "pyproject.toml").write_text("# sujeira tracked... ", encoding="utf-8")
    import subprocess
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path,
                   capture_output=True, text=True, check=True)
    subprocess.run(["git", "commit", "-m", "track"], cwd=tmp_path,
                   capture_output=True, text=True, check=True)
    (tmp_path / "pyproject.toml").write_text("# modificado depois\n", encoding="utf-8")

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "suja" in err
    assert not (tmp_path / ".claude" / "settings.local.json").is_file()


def test_compile_session_branch_per_contract_false_skips_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _prepare_compile_session_fixture(tmp_path)
    _write(
        tmp_path / ".harness" / "harness.yaml",
        "governance:\n  branch_per_contract: false\n",
    )

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["branch"] is None


def test_compile_session_non_git_dir_warns_and_skips_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Diretório sem git com a flag ativa: aviso em stderr e segue sem
    branch (sandboxes/e2e sem git continuam funcionando)."""
    _prepare_compile_session_fixture(tmp_path)

    monkeypatch.setattr(sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["branch"] is None
    assert "aviso" in captured.err


def _current_branch(target: Path) -> str:
    import subprocess

    proc = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        cwd=target, capture_output=True, text=True, check=True,
    )
    return proc.stdout.strip()


def test_compile_session_no_branch_leaves_the_developer_where_they_were(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-02: `--no-branch` compila os mesmos artefatos sem tocar em git.

    Existe para a recompilação AUTOMÁTICA (T-03/T-05): disparada no início
    da sessão, a versão sem a flag moveria quem está em `main` para
    `contract/<slug>` sem ter pedido nada."""
    _init_git_repo(tmp_path)
    _prepare_compile_session_fixture(tmp_path)
    _write(tmp_path / ".harness" / "harness.yaml", "governance:\n  branch_per_contract: true\n")
    assert _current_branch(tmp_path) == "main"

    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path), "--no-branch"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["branch"] is None
    assert _current_branch(tmp_path) == "main"

    # Pular a branch não pode pular a compilação: os artefatos são os mesmos.
    assert (tmp_path / ".claude" / "settings.local.json").is_file()
    assert (tmp_path / ".harness" / "hooks" / "boundary_guard.py").is_file()
    assert (tmp_path / ".harness" / "hooks" / "session_start.py").is_file()
    assert (tmp_path / ".harness" / "hooks" / "stop_hook.py").is_file()
    assert (tmp_path / "AGENTS.md").is_file()


def test_compile_session_no_branch_does_not_abort_on_a_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O aborto por árvore suja protege a CRIAÇÃO da branch (finding C) —
    sem branch a criar, ele não se aplica. Se aplicasse, a recompilação
    automática só funcionaria com o repositório limpo, ou seja, quase nunca
    durante o trabalho."""
    _init_git_repo(tmp_path)
    _prepare_compile_session_fixture(tmp_path)
    _write(tmp_path / ".harness" / "harness.yaml", "governance:\n  branch_per_contract: true\n")
    import subprocess
    subprocess.run(["git", "add", "pyproject.toml"], cwd=tmp_path,
                   capture_output=True, text=True, check=True)
    subprocess.run(["git", "commit", "-m", "track"], cwd=tmp_path,
                   capture_output=True, text=True, check=True)
    (tmp_path / "pyproject.toml").write_text("# modificado depois\n", encoding="utf-8")

    monkeypatch.setattr(
        sys, "argv", ["harness", "compile-session", "--dir", str(tmp_path), "--no-branch"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert (tmp_path / ".claude" / "settings.local.json").is_file()
    assert _current_branch(tmp_path) == "main"


class _SyncSpy:
    """Substitui `autoupdate.sync_if_outdated` para registrar SE e COM QUE
    diretório o gatilho da CLI disparou."""

    def __init__(self) -> None:
        self.dirs: list[str] = []

    def __call__(self, target_dir, **_kwargs):  # noqa: ANN001, ANN003
        self.dirs.append(str(target_dir))

        class _Result:
            recompiled = False

        return _Result()


def _install_sync_spy(monkeypatch: pytest.MonkeyPatch) -> _SyncSpy:
    import harness.autoupdate as autoupdate

    spy = _SyncSpy()
    monkeypatch.setattr(autoupdate, "sync_if_outdated", spy)
    return spy


#: (argv do subcomando, dispara o auto-update?, por quê)
_AUTO_UPDATE_TRIGGER_CASES = [
    (["analyze"], True, "comando comum dispara"),
    (["audit"], True, "comando comum dispara"),
    (["status"], False, "kill-switch precisa funcionar em qualquer estado"),
    (["enable"], False, "kill-switch precisa funcionar em qualquer estado"),
    (["disable"], False, "kill-switch precisa funcionar em qualquer estado"),
    (["doctor"], False, "doctor mostra o estado real, não o corrige"),
    (["compile"], False, "é o próprio alvo da recompilação: recursão"),
    (["compile-session"], False, "é o próprio alvo da recompilação: recursão"),
]


@pytest.mark.parametrize(
    ("argv", "expect_trigger", "why"),
    _AUTO_UPDATE_TRIGGER_CASES,
    ids=[f"{c[0][0]}: {c[2]}" for c in _AUTO_UPDATE_TRIGGER_CASES],
)
def test_auto_update_runs_before_every_command_except_the_ones_that_must_see_the_real_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
    argv: list[str], expect_trigger: bool, why: str,
) -> None:
    spy = _install_sync_spy(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["harness", *argv, "--dir", str(tmp_path)])

    with pytest.raises(SystemExit):
        main()
    capsys.readouterr()

    assert bool(spy.dirs) is expect_trigger, why
    if expect_trigger:
        assert spy.dirs == [str(tmp_path.resolve())]


def test_auto_update_failure_never_breaks_the_command_that_triggered_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Cinto e suspensórios: `sync_if_outdated` já promete não levantar, mas o
    comando do usuário não pode depender dessa promessa para sair com o
    código certo."""
    import harness.autoupdate as autoupdate

    def explode(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("falha inesperada no auto-update")

    monkeypatch.setattr(autoupdate, "sync_if_outdated", explode)
    monkeypatch.setattr(sys, "argv", ["harness", "analyze", "--dir", str(tmp_path)])

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    assert json.loads(capsys.readouterr().out)["languages"] == []


def _write_feature_list(tmp_path: Path, verify_cmd: str) -> None:
    payload = {
        "contract": "exemplo-feature",
        "compiled_at": "2026-07-16T12:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "Criar modulo de configuracao",
                "files": [],
                "verify_cmd": verify_cmd,
                "depends": [],
                "passes": False,
            }
        ],
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def _true_cmd() -> str:
    return "exit 0" if sys.platform.startswith("win") else "true"


def _exit_code_cmd(code: int) -> str:
    return f"exit {code}" if sys.platform.startswith("win") else f"exit {code}"


def test_verify_subcommand_success_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["feature_id"] == "T-01"
    assert data["exit_code"] == 0

    evidence_path = tmp_path / ".harness" / "evidence" / "exemplo-feature" / "T-01.json"
    assert evidence_path.is_file()


def test_verify_subcommand_failure_propagates_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _exit_code_cmd(3))

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    evidence_path = tmp_path / ".harness" / "evidence" / "exemplo-feature" / "T-01.json"
    assert not evidence_path.is_file()


def test_verify_subcommand_msb3027_failure_prints_aviso_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 7 do backlog issue #1: quando o verify_cmd falha com um padrão
    de arquivo em uso (MSB3027), o dispatch do comando `verify` imprime a
    mensagem acionável ("aviso: ...") em stderr, além de stdout/stderr
    crus de sempre."""
    script = tmp_path / "fake_msbuild.py"
    _write(
        script,
        "import sys\n"
        "sys.stderr.write('error MSB3027: Could not copy bin/App.dll. "
        "The process cannot access the file because it is being used by "
        "another process.\\n')\n"
        "sys.exit(1)\n",
    )
    verify_cmd = f'"{sys.executable}" "{script}"'
    _write_feature_list(tmp_path, verify_cmd)

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "aviso:" in err
    assert "processo do próprio projeto-alvo" in err


def test_verify_subcommand_normal_failure_does_not_print_aviso_hint(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sem falso-positivo: falha comum (exit 3 sem menção a lock de arquivo)
    não deve imprimir a linha "aviso: ..."."""
    _write_feature_list(tmp_path, _exit_code_cmd(3))

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    err = capsys.readouterr().err
    assert "aviso:" not in err


def test_verify_subcommand_failure_truncates_verbose_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """T-06/onda-1: uma suíte verbosa que falha não pode despejar centenas de
    linhas no contexto do agente — só o fim relevante (últimas ~40 linhas),
    com aviso de quantas foram omitidas."""
    script = tmp_path / "fake_verbose_runner.py"
    _write(
        script,
        "import sys\n"
        "for i in range(200):\n"
        "    print(f'linha de stdout {i}')\n"
        "for i in range(200):\n"
        "    print(f'linha de stderr {i}', file=sys.stderr)\n"
        "sys.exit(1)\n",
    )
    verify_cmd = f'"{sys.executable}" "{script}"'
    _write_feature_list(tmp_path, verify_cmd)

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "linha de stdout 199" in err  # o FIM da saída sobrevive
    assert "linha de stdout 0" not in err  # o começo foi cortado
    assert "linha de stderr 199" in err
    assert "linha de stderr 0" not in err
    assert "omitida" in err  # aviso explícito de truncamento, não corte silencioso
    # a saída inteira nunca entra no contexto: bem menos que as 400 linhas originais
    assert err.count("\n") < 120


def test_verify_subcommand_failure_does_not_truncate_short_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Sem falso-positivo: saída curta passa inteira, sem aviso de corte."""
    script = tmp_path / "fake_short_runner.py"
    _write(script, "print('so uma linha')\nimport sys\nsys.exit(1)\n")
    verify_cmd = f'"{sys.executable}" "{script}"'
    _write_feature_list(tmp_path, verify_cmd)

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "so uma linha" in err
    assert "omitida" not in err


def test_verify_subcommand_missing_feature_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-99", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def _write_two_feature_list(tmp_path: Path, verify_cmd: str) -> None:
    payload = {
        "contract": "exemplo-feature",
        "compiled_at": "2026-07-16T12:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "Criar modulo de configuracao",
                "files": [],
                "verify_cmd": verify_cmd,
                "depends": [],
                "passes": False,
            },
            {
                "id": "T-02",
                "desc": "Outra feature",
                "files": [],
                "verify_cmd": verify_cmd,
                "depends": ["T-01"],
                "passes": False,
            },
        ],
    }
    _write(
        tmp_path / ".harness" / "feature_list.json",
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
    )


def test_verify_subcommand_with_mark_passed_flag_sets_passes_true(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_two_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(
        sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path), "--mark-passed"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    capsys.readouterr()

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    assert features_by_id["T-01"]["passes"] is True
    # feature irmã intacta -- --mark-passed não corrompe o resto do arquivo
    assert features_by_id["T-02"]["passes"] is False
    assert features_by_id["T-02"]["depends"] == ["T-01"]


def test_verify_subcommand_marks_passes_true_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Item 3 do backlog do dogfood miojo: verify verde FECHA a tarefa.

    Antes da v0.23.0 marcar era opt-in, e o resultado era evidência com
    `exit_code: 0` em disco enquanto `passes` continuava false — `harness
    supervise` devolvia a mesma tarefa para sempre."""
    _write_two_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    # o stdout continua sendo SÓ o JSON da evidência (consumido por json.loads
    # mundo afora); o aviso de estado vai para stderr
    assert json.loads(captured.out)["feature_id"] == "T-01"
    assert "passes:true gravado" in captured.err

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    assert features_by_id["T-01"]["passes"] is True
    assert features_by_id["T-02"]["passes"] is False


def test_verify_subcommand_no_mark_passed_leaves_feature_list_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`--no-mark-passed` mantém o comportamento antigo (fleet paralelo) — e a
    saída DIZ que a tarefa continua aberta, em vez de deixar o agente deduzir."""
    _write_two_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(
        sys, "argv",
        ["harness", "verify", "T-01", "--dir", str(tmp_path), "--no-mark-passed"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert "passes continua" in captured.err

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    assert features_by_id["T-01"]["passes"] is False
    assert features_by_id["T-02"]["passes"] is False


def test_verify_subcommand_with_mark_passed_flag_on_failure_does_not_mark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_two_feature_list(tmp_path, _exit_code_cmd(3))

    monkeypatch.setattr(
        sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path), "--mark-passed"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    capsys.readouterr()

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    # verify_cmd falhou -> run_verify levanta antes de qualquer lógica de
    # --mark-passed rodar -- feature_list.json inalterado
    assert features_by_id["T-01"]["passes"] is False
    assert features_by_id["T-02"]["passes"] is False


# ---------------- harness disable | enable | status (kill-switch) ----------------

def _sentinel(tmp_path: Path) -> Path:
    return tmp_path / ".harness" / "harness.disabled"


def test_killswitch_subcommands_round_trip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O ciclo inteiro do kill-switch pela CLI: `status` num repo intocado,
    `disable` com nota, `status` de novo (a nota tem que voltar), `enable`, e
    `enable` outra vez — que é no-op, não erro.

    Este é o comando que o humano usa quando o harness atrapalha; qualquer exit
    code diferente de 0 aqui empurra para apagar o sentinel na mão."""
    def rodar(*argv: str) -> dict:
        monkeypatch.setattr(sys, "argv", ["harness", *argv, "--dir", str(tmp_path)])
        with pytest.raises(SystemExit) as exc_info:
            main()
        assert exc_info.value.code == 0, argv
        return json.loads(capsys.readouterr().out)

    assert rodar("status")["disabled"] is False

    data = rodar("disable", "--note", "destravando deploy")
    assert data["disabled"] is True
    assert data["note"] == "destravando deploy"
    assert _sentinel(tmp_path).is_file()

    data = rodar("status")
    assert data["disabled"] is True
    assert data["note"] == "destravando deploy"

    data = rodar("enable")
    assert data["disabled"] is False
    assert not _sentinel(tmp_path).is_file()

    data = rodar("enable")
    assert data["disabled"] is False
    assert data["removed"] is False, "reativar o que ja esta ativo e no-op, nao erro"


def test_audit_runtime_subcommand_exit_code_follows_the_score(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O exit code é o contrato com o CI: 1 quando há finding crítico, 0 quando
    o runtime está saudável."""
    def rodar(alvo: Path) -> tuple[int, dict]:
        monkeypatch.setattr(sys, "argv", ["harness", "audit-runtime", "--dir", str(alvo)])
        with pytest.raises(SystemExit) as exc_info:
            main()
        return exc_info.value.code, json.loads(capsys.readouterr().out)

    # sem feature_list.json -> critical -> score baixo -> exit 1
    doente = tmp_path / "doente"
    doente.mkdir()
    code, data = rodar(doente)
    assert code == 1
    assert "missing_feature_list" in {f["code"] for f in data["findings"]}
    assert data["score"] <= 60

    _write_feature_list(tmp_path, _true_cmd())
    _write(tmp_path / ".harness/progress.md", "# Progresso\n")
    code, data = rodar(tmp_path)
    assert code == 0
    assert not any(f["severity"] == "critical" for f in data["findings"])
    assert data["score"] >= 60


# ---------------------------------------------------------------------------
# Fase 4 (SUBAGENTE 08): `team design|generate`, `review`, `supervise`,
# `audit-team`, e o efeito colateral de `verify` acionando
# `harness.supervisor.on_feature_verified`.
# ---------------------------------------------------------------------------

def test_team_design_subcommand_prints_valid_pattern(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["harness", "team", "design", "--dir", str(tmp_path), "--description", "quero revisão de qualidade"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pattern"] == "producer-reviewer"
    assert "justification" in data
    assert set(data["roles"]) == {"producer", "reviewer"}


def test_team_generate_subcommand_writes_artifacts_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["harness", "team", "generate", "--dir", str(tmp_path), "--pattern", "producer-reviewer"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["pattern"] == "producer-reviewer"
    assert data["mode"] == "subagents"
    assert set(data["roles"]) == {"producer", "reviewer"}

    assert (tmp_path / ".claude" / "agents" / "producer.md").is_file()
    assert (tmp_path / ".harness" / "team" / "manifest.json").is_file()


def test_team_generate_subcommand_unknown_pattern_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["harness", "team", "generate", "--dir", str(tmp_path), "--pattern", "padrao-inexistente"]
    )
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_review_submit_subcommand_writes_in_review_and_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "review", "T-01", "submit", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["status"] == "in_review"

    review_path = tmp_path / ".harness" / "review" / "T-01.json"
    assert review_path.is_file()
    assert json.loads(review_path.read_text(encoding="utf-8"))["status"] == "in_review"


def test_review_approve_without_prior_submit_exits_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "review", "T-01", "approve", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert err.startswith("erro: ")


def test_supervise_subcommand_without_contract_exits_zero_with_null(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "supervise", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["next"] is None


def test_audit_team_subcommand_without_team_exits_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["harness", "audit-team", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["score"] >= 60
    assert not any(f["severity"] == "critical" for f in data["findings"])


def test_verify_subcommand_with_team_auto_submits_for_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from harness.teams import generate_team

    _write_feature_list(tmp_path, _true_cmd())
    generate_team(tmp_path, "producer-reviewer")

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
    assert data["feature_id"] == "T-01"

    review_path = tmp_path / ".harness" / "review" / "T-01.json"
    assert review_path.is_file()
    review_data = json.loads(review_path.read_text(encoding="utf-8"))
    assert review_data["status"] == "in_review"
    assert review_data["iteration"] == 1


# ---------------------------------------------------------------------------
# --dir tem que apontar para diretório existente (D1/D2 do teste isento)
# ---------------------------------------------------------------------------

def _run(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["harness", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code


def test_analyze_with_nonexistent_dir_writes_nothing_and_exits_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D1: `analyze` criava a árvore inteira e gravava um `repo-profile.json`
    vazio com exit 0 — um erro de digitação no `--dir` materializava um
    projeto fantasma, e um path mutilado pelo shell escrevia DENTRO da raiz do
    repo-alvo."""
    ghost = tmp_path / "nao-existe"

    code = _run(monkeypatch, "analyze", "--dir", str(ghost))

    assert code == 2
    assert not ghost.exists(), "o comando criou o diretório que devia recusar"
    assert "não existe" in capsys.readouterr().err


def test_audit_with_nonexistent_dir_does_not_emit_a_plausible_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """D2: `audit` devolvia score 60 e "rode `/harness-creator:init`" sobre um
    caminho inexistente — laudo crível sobre nada, exit 0."""
    code = _run(monkeypatch, "audit", "--dir", str(tmp_path / "nao-existe"))

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "missing_harness_yaml" not in captured.out


def test_every_dir_taking_subcommand_refuses_a_nonexistent_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guarda é do parse, não de cada branch do dispatch: validar comando a
    comando é o que deixou `compile` certo e `analyze`/`audit` errados."""
    ghost = str(tmp_path / "nao-existe")
    for command in ("analyze", "compile", "audit", "audit-runtime", "preflight",
                    "compile-session", "supervise", "doctor", "status"):
        assert _run(monkeypatch, command, "--dir", ghost) == 2, command
    assert not Path(ghost).exists()


def test_existing_dir_still_passes_through(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """O outro lado da guarda: diretório que existe segue o fluxo normal —
    `analyze` num repo vazio continua devolvendo perfil com `unknowns`."""
    code = _run(monkeypatch, "analyze", "--dir", str(tmp_path))

    assert code == 0
    assert (tmp_path / ".harness" / "repo-profile.json").is_file()
    assert json.loads(capsys.readouterr().out)["unknowns"]


def test_audit_exits_one_when_a_critical_finding_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`skills/audit/SKILL.md` promete "exit 1 = algum finding crítico", mas o
    gate era só `score >= 60` — e UM critical custa exatamente 40, deixando o
    score em 60. Um repo sem harness nenhum passava por qualquer gate de CI que
    olhasse o exit code."""
    code = _run(monkeypatch, "audit", "--dir", str(tmp_path))

    report = json.loads(capsys.readouterr().out)
    assert report["score"] == 60
    assert any(f["severity"] == "critical" for f in report["findings"])
    assert code == 1, "critical com score exatamente 60 saía 0"
