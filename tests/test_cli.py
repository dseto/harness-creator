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
    assert data["settings"].endswith("settings.json")
    assert data["boundary_guard"].endswith("boundary_guard.py")
    assert data["agents_md"].endswith("AGENTS.md")
    assert data["lifecycle_detail"].endswith("LIFECYCLE.md")
    assert data["session_start_hook"].endswith("session_start.py")
    assert data["stop_hook"].endswith("stop_hook.py")
    assert any(p.endswith("init.sh") for p in data["templates"])
    assert any(p.endswith("init.ps1") for p in data["templates"])

    assert (tmp_path / ".claude" / "settings.json").is_file()
    assert (tmp_path / ".harness" / "hooks" / "boundary_guard.py").is_file()
    assert (tmp_path / "AGENTS.md").is_file()
    assert (tmp_path / ".harness" / "LIFECYCLE.md").is_file()
    assert (tmp_path / "claude-progress.md").is_file()
    assert (tmp_path / "init.sh").is_file()
    assert (tmp_path / "init.ps1").is_file()
    assert (tmp_path / ".harness" / "hooks" / "session_start.py").is_file()
    assert (tmp_path / ".harness" / "hooks" / "stop_hook.py").is_file()


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
    assert not (tmp_path / ".claude" / "settings.json").is_file()


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

    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
    assert evidence_path.is_file()


def test_verify_subcommand_failure_propagates_exit_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _exit_code_cmd(3))

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 3
    evidence_path = tmp_path / ".harness" / "evidence" / "T-01.json"
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


def test_verify_subcommand_without_mark_passed_flag_leaves_feature_list_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_two_feature_list(tmp_path, _true_cmd())

    monkeypatch.setattr(sys, "argv", ["harness", "verify", "T-01", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    capsys.readouterr()

    feature_list_path = tmp_path / ".harness" / "feature_list.json"
    data = json.loads(feature_list_path.read_text(encoding="utf-8"))
    features_by_id = {f["id"]: f for f in data["features"]}
    # comportamento atual preservado: sem a flag, feature_list.json não muda
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


def test_audit_runtime_subcommand_exits_one_when_score_low(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # nenhum feature_list.json -> critical -> score baixo -> exit 1
    monkeypatch.setattr(sys, "argv", ["harness", "audit-runtime", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 1
    data = json.loads(capsys.readouterr().out)
    assert "missing_feature_list" in {f["code"] for f in data["findings"]}
    assert data["score"] <= 60


def test_audit_runtime_subcommand_exits_zero_when_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _write_feature_list(tmp_path, _true_cmd())
    _write(tmp_path / "claude-progress.md", "# Progresso\n")

    monkeypatch.setattr(sys, "argv", ["harness", "audit-runtime", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 0
    data = json.loads(capsys.readouterr().out)
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
