"""Testes do preflight — laudo de prontidão de repositório cru.

T-01 cobre apenas o núcleo de dados + agregação: dataclasses
`PreflightCheck`/`PreflightCategory`/`PreflightReport`, invariante do `fix`,
status agregado da categoria, veredito global e serialização JSON.
Detectores (Git/manifest/tests/lint) e `run_preflight()` são T-02..T-05.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

import harness.cli as cli_mod
import harness.preflight as preflight_mod
from harness.analyzer import analyze_project
from harness.preflight import (
    PreflightCategory,
    PreflightCheck,
    PreflightError,
    PreflightReport,
    _check_git,
    _check_lint,
    _check_manifest,
    _check_tests,
    compute_verdict,
    run_preflight,
)


# ---------------------------------------------------------------------------
# Invariante do check: não-PASS sem `fix` é erro de construção do laudo
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("status", ["WARNING", "FAIL"])
def test_check_non_pass_without_fix_raises(status: str) -> None:
    with pytest.raises(ValueError):
        PreflightCheck(code="x", status=status, message="algo", fix="", evidence=None)


def test_check_pass_without_fix_is_allowed() -> None:
    # PASS não precisa de fix — não deve levantar.
    check = PreflightCheck(code="x", status="PASS", message="ok", fix="", evidence="pyproject.toml")
    assert check.status == "PASS"
    assert check.fix == ""


def test_check_non_pass_with_fix_is_allowed() -> None:
    check = PreflightCheck(code="git_repo", status="FAIL", message="sem repo", fix="git init", evidence=None)
    assert check.fix == "git init"


# ---------------------------------------------------------------------------
# Agregação de status da categoria: pior status entre os checks
# ---------------------------------------------------------------------------

def _pass(code: str = "c") -> PreflightCheck:
    return PreflightCheck(code=code, status="PASS", message="ok", fix="", evidence=None)


def _warning(code: str = "c") -> PreflightCheck:
    return PreflightCheck(code=code, status="WARNING", message="alerta", fix="conserte", evidence=None)


def _fail(code: str = "c") -> PreflightCheck:
    return PreflightCheck(code=code, status="FAIL", message="falhou", fix="conserte", evidence=None)


def test_category_status_all_pass() -> None:
    cat = PreflightCategory(id="git", title="Git", checks=[_pass("a"), _pass("b")])
    assert cat.status == "PASS"


def test_category_status_with_one_warning() -> None:
    cat = PreflightCategory(id="git", title="Git", checks=[_pass("a"), _warning("b")])
    assert cat.status == "WARNING"


def test_category_status_fail_beats_warning() -> None:
    cat = PreflightCategory(
        id="git", title="Git", checks=[_warning("a"), _fail("b"), _warning("c")]
    )
    assert cat.status == "FAIL"


def test_category_status_empty_is_pass() -> None:
    cat = PreflightCategory(id="git", title="Git", checks=[])
    assert cat.status == "PASS"


# ---------------------------------------------------------------------------
# Veredito global
# ---------------------------------------------------------------------------

def test_compute_verdict_ready_all_pass() -> None:
    cats = [
        PreflightCategory(id="git", title="Git", checks=[_pass()]),
        PreflightCategory(id="manifest", title="Manifest", checks=[_pass()]),
    ]
    assert compute_verdict(cats) == "READY"


def test_compute_verdict_ready_with_warnings() -> None:
    cats = [
        PreflightCategory(id="git", title="Git", checks=[_pass()]),
        PreflightCategory(id="lint", title="Lint", checks=[_warning()]),
    ]
    assert compute_verdict(cats) == "READY_WITH_WARNINGS"


def test_compute_verdict_not_ready_on_any_fail() -> None:
    cats = [
        PreflightCategory(id="git", title="Git", checks=[_warning()]),
        PreflightCategory(id="manifest", title="Manifest", checks=[_fail()]),
    ]
    assert compute_verdict(cats) == "NOT_READY"


def test_compute_verdict_empty_is_ready() -> None:
    assert compute_verdict([]) == "READY"


# ---------------------------------------------------------------------------
# Serialização — chaves exatas do contrato
# ---------------------------------------------------------------------------

def _sample_report() -> PreflightReport:
    git = PreflightCategory(
        id="git",
        title="Controle de Versão (Git)",
        checks=[
            PreflightCheck(
                code="git_repo",
                status="FAIL",
                message="diretório não é um repositório git",
                fix="git init",
                evidence=None,
            ),
        ],
    )
    manifest = PreflightCategory(
        id="manifest",
        title="Manifestos",
        checks=[
            PreflightCheck(
                code="manifest_present",
                status="PASS",
                message="manifest reconhecido",
                fix="",
                evidence="pyproject.toml",
            ),
        ],
    )
    return PreflightReport(
        verdict="NOT_READY",
        target="/abs/target",
        categories=[git, manifest],
    )


def test_report_to_dict_has_contract_keys() -> None:
    data = _sample_report().to_dict()

    assert set(data.keys()) == {"verdict", "target", "categories"}
    assert data["verdict"] == "NOT_READY"
    assert data["target"] == "/abs/target"

    cat = data["categories"][0]
    assert set(cat.keys()) == {"id", "title", "status", "checks"}
    assert cat["id"] == "git"
    assert cat["title"] == "Controle de Versão (Git)"
    assert cat["status"] == "FAIL"  # status agregado espelhado no dict

    check = cat["checks"][0]
    assert set(check.keys()) == {"code", "status", "message", "fix", "evidence"}
    assert check["code"] == "git_repo"
    assert check["status"] == "FAIL"
    assert check["fix"] == "git init"
    assert check["evidence"] is None

    # evidence preservado quando presente
    assert data["categories"][1]["checks"][0]["evidence"] == "pyproject.toml"


def test_report_to_json_roundtrips() -> None:
    report = _sample_report()
    text = report.to_json()

    # indentado e sem escapar não-ASCII (igual ao AuditReport.to_json)
    assert "\n" in text
    assert "diretório não é um repositório git" in text

    parsed = json.loads(text)
    assert parsed == report.to_dict()


def test_preflight_error_is_exception() -> None:
    assert issubclass(PreflightError, Exception)


# ---------------------------------------------------------------------------
# T-02 — Categoria 1: detector Git
# ---------------------------------------------------------------------------

def _git(cwd: Path, *args: str) -> None:
    """Roda git de verdade no fixture (não mock de subprocess)."""
    subprocess.run(
        ["git", "-C", str(cwd), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(cwd: Path) -> None:
    """git init + config local (não depende de config global do ambiente)."""
    _git(cwd, "init")
    _git(cwd, "config", "user.email", "test@example.com")
    _git(cwd, "config", "user.name", "Preflight Test")


def _codes(category: PreflightCategory) -> list[str]:
    return [c.code for c in category.checks]


def _by_code(category: PreflightCategory, code: str) -> PreflightCheck:
    for c in category.checks:
        if c.code == code:
            return c
    raise AssertionError(f"check '{code}' ausente da categoria; presentes: {_codes(category)}")


def test_git_category_identity(tmp_path: Path) -> None:
    cat = _check_git(tmp_path)
    assert cat.id == "git"
    assert cat.title == "Controle de Versão (Git)"


def test_git_binary_absent_omits_subprocess_checks(tmp_path: Path, monkeypatch) -> None:
    # git ausente do PATH → git_binary FAIL; git_repo e gitignore_present AINDA
    # avaliados; baseline/worktree (os 2 de subprocess) OMITIDOS.
    monkeypatch.setattr(preflight_mod.shutil, "which", lambda _name: None)
    _init_repo(tmp_path)  # tem .git, mas não deve rodar subprocess

    cat = _check_git(tmp_path)

    assert _codes(cat) == ["git_binary", "git_repo", "gitignore_present"]
    assert _by_code(cat, "git_binary").status == "FAIL"
    assert _by_code(cat, "git_binary").fix
    assert "git_baseline_commit" not in _codes(cat)
    assert "git_worktree_clean" not in _codes(cat)


def test_git_repo_absent_omits_baseline_and_worktree(tmp_path: Path) -> None:
    # dir sem .git → git_repo FAIL; baseline/worktree omitidos; gitignore avaliado.
    cat = _check_git(tmp_path)

    assert _codes(cat) == ["git_binary", "git_repo", "gitignore_present"]
    assert _by_code(cat, "git_binary").status == "PASS"
    assert _by_code(cat, "git_repo").status == "FAIL"
    assert _by_code(cat, "git_repo").fix == "git init"
    assert "git_baseline_commit" not in _codes(cat)
    assert "git_worktree_clean" not in _codes(cat)


def test_git_repo_zero_commits_baseline_warning(tmp_path: Path) -> None:
    # git init só, sem commit → git_baseline_commit WARNING (não FAIL).
    _init_repo(tmp_path)

    cat = _check_git(tmp_path)

    baseline = _by_code(cat, "git_baseline_commit")
    assert baseline.status == "WARNING"
    assert baseline.fix
    # worktree é avaliado (repo existe); com git init vazio a árvore está limpa.
    assert "git_worktree_clean" in _codes(cat)


def test_git_worktree_dirty_warning(tmp_path: Path) -> None:
    # repo com 1 commit + arquivo modificado não-commitado → worktree WARNING.
    _init_repo(tmp_path)
    f = tmp_path / "arquivo.txt"
    f.write_text("v1", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "commit inicial")
    f.write_text("v2 modificado", encoding="utf-8")  # suja a árvore

    cat = _check_git(tmp_path)

    assert _by_code(cat, "git_baseline_commit").status == "PASS"
    worktree = _by_code(cat, "git_worktree_clean")
    assert worktree.status == "WARNING"
    assert worktree.fix


def test_git_repo_clean_with_commit_all_pass(tmp_path: Path) -> None:
    # repo com 1 commit, árvore limpa, .gitignore presente → tudo PASS.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    (tmp_path / "arquivo.txt").write_text("conteúdo", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "commit inicial")

    cat = _check_git(tmp_path)

    assert cat.status == "PASS"
    assert _by_code(cat, "git_binary").status == "PASS"
    assert _by_code(cat, "git_repo").status == "PASS"
    assert _by_code(cat, "git_repo").evidence == ".git"
    assert _by_code(cat, "git_baseline_commit").status == "PASS"
    assert _by_code(cat, "git_worktree_clean").status == "PASS"
    assert _by_code(cat, "gitignore_present").status == "PASS"
    assert _by_code(cat, "gitignore_present").evidence == ".gitignore"


def test_gitignore_absent_is_warning(tmp_path: Path) -> None:
    _init_repo(tmp_path)
    (tmp_path / "arquivo.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "inicial")

    cat = _check_git(tmp_path)
    gi = _by_code(cat, "gitignore_present")
    assert gi.status == "WARNING"
    assert gi.fix


def test_gitignore_present_is_pass(tmp_path: Path) -> None:
    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    cat = _check_git(tmp_path)  # sem .git aqui é irrelevante p/ este check
    gi = _by_code(cat, "gitignore_present")
    assert gi.status == "PASS"
    assert gi.evidence == ".gitignore"


def test_git_subdir_without_own_dotgit_fails_despite_parent_repo(tmp_path: Path) -> None:
    # Decisão fixada do spec: presença por (alvo/.git).exists(), NÃO por
    # "está dentro de uma work tree". Um subdiretório SEM .git próprio, ainda
    # que sob a work tree de um repo-pai, deve dar git_repo FAIL — não pode
    # passar de carona no repo-pai.
    _init_repo(tmp_path)  # repo-pai em tmp_path
    (tmp_path / "arquivo.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "inicial")

    child = tmp_path / "mock_dentro_do_pai"
    child.mkdir()

    cat = _check_git(child)

    assert _by_code(cat, "git_repo").status == "FAIL"
    # como git_repo FAIL, baseline/worktree são omitidos (não medem o repo-pai).
    assert "git_baseline_commit" not in _codes(cat)
    assert "git_worktree_clean" not in _codes(cat)


def test_git_worktree_clean_fail_on_subprocess_error(tmp_path: Path, monkeypatch) -> None:
    # F-02: ramo FAIL de git_worktree_clean. Falha INESPERADA do subprocess de
    # `status` (returncode != 0) vira FAIL — comportamento CONTRATADO por
    # Plans.md T-02 (não WARNING, que é reservado à árvore suja normal). Só o
    # branch de `status` é mockado; `rev-parse` (baseline) delega ao _run_git real.
    _init_repo(tmp_path)
    (tmp_path / "arquivo.txt").write_text("x", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "inicial")

    real_run_git = preflight_mod._run_git

    def fake_run_git(target_dir: Path, *args: str) -> subprocess.CompletedProcess:
        if "status" in args:
            return subprocess.CompletedProcess(
                args=list(args), returncode=129, stdout="", stderr="unknown option"
            )
        return real_run_git(target_dir, *args)

    monkeypatch.setattr(preflight_mod, "_run_git", fake_run_git)

    cat = _check_git(tmp_path)

    # baseline não é afetado (delega ao real): há 1 commit → PASS.
    assert _by_code(cat, "git_baseline_commit").status == "PASS"
    worktree = _by_code(cat, "git_worktree_clean")
    assert worktree.status == "FAIL"
    assert "unknown option" in worktree.message
    assert worktree.fix
    # categoria git como um todo herda o pior status (FAIL).
    assert cat.status == "FAIL"


def test_git_worktree_child_gitfile_repo_present_and_pass(tmp_path: Path) -> None:
    # F-03: caminho GITFILE. Um worktree secundário criado por `git worktree add`
    # tem `.git` como ARQUIVO (gitfile), não diretório. A decisão fixada do spec
    # (presença por `.git.exists()`, dir OU gitfile) deve reconhecê-lo como repo
    # e avaliar baseline/worktree normalmente.
    pai = tmp_path / "pai"
    pai.mkdir()
    _init_repo(pai)
    (pai / "arquivo.txt").write_text("x", encoding="utf-8")
    _git(pai, "add", "-A")
    _git(pai, "commit", "-m", "inicial")

    wt_child = tmp_path / "wt_child"
    _git(pai, "worktree", "add", str(wt_child))

    # prova de que git worktree gera um GITFILE (arquivo, não diretório).
    assert (wt_child / ".git").is_file()

    cat = _check_git(wt_child)

    git_repo = _by_code(cat, "git_repo")
    assert git_repo.status == "PASS"
    assert git_repo.evidence == ".git"
    # baseline/worktree PRESENTES (não omitidos) e ambos PASS.
    assert "git_baseline_commit" in _codes(cat)
    assert "git_worktree_clean" in _codes(cat)
    assert _by_code(cat, "git_baseline_commit").status == "PASS"
    assert _by_code(cat, "git_worktree_clean").status == "PASS"


# ---------------------------------------------------------------------------
# T-03 — Categorias 2/3/4: política de severidade sobre o RepoProfile.
# Fixtures REAIS em tmp_path (manifest/teste/lint de verdade), sem mockar
# analyze_project.
# ---------------------------------------------------------------------------

_PYPROJECT_COMPLETE = """\
[project]
name = "mock"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.ruff]
line-length = 100
"""

_PYPROJECT_PYTEST_NO_RUFF = """\
[project]
name = "mock"
version = "0.1.0"

[project.optional-dependencies]
dev = ["pytest>=8.0"]
"""


def _write_python_repo_complete(root: Path) -> None:
    """pyproject com pytest + [tool.ruff] e um teste na convenção tests/**/*.py."""
    (root / "pyproject.toml").write_text(_PYPROJECT_COMPLETE, encoding="utf-8")
    tests_dir = root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def test_manifest_present_pass_python(tmp_path: Path) -> None:
    _write_python_repo_complete(tmp_path)
    profile = analyze_project(tmp_path)

    cat = _check_manifest(profile)
    assert cat.id == "manifest"
    assert cat.title == "Manifestos de Projeto Estruturados"
    check = _by_code(cat, "manifest_present")
    assert check.status == "PASS"
    assert check.evidence == "pyproject.toml"


def test_tests_category_all_pass_python(tmp_path: Path) -> None:
    _write_python_repo_complete(tmp_path)
    profile = analyze_project(tmp_path)

    cat = _check_tests(profile)
    assert cat.id == "tests"
    assert cat.title == "Ferramentas de Verificação/TDD"
    assert cat.status == "PASS"
    runner = _by_code(cat, "test_runner_detected")
    assert runner.status == "PASS"
    assert runner.evidence == "pyproject.toml"
    files = _by_code(cat, "test_files_present")
    assert files.status == "PASS"
    assert files.evidence == "tests/test_x.py"


def test_lint_category_pass_python(tmp_path: Path) -> None:
    _write_python_repo_complete(tmp_path)
    profile = analyze_project(tmp_path)

    cat = _check_lint(profile)
    assert cat.id == "lint"
    assert cat.title == "Qualidade Estática/Linting"
    check = _by_code(cat, "linter_configured")
    assert check.status == "PASS"
    assert check.evidence == "pyproject.toml"


def test_python_complete_all_three_categories_pass(tmp_path: Path) -> None:
    # Cenário 1 do prompt: repo Python completo → as 3 categorias 100% PASS.
    _write_python_repo_complete(tmp_path)
    profile = analyze_project(tmp_path)

    assert _check_manifest(profile).status == "PASS"
    assert _check_tests(profile).status == "PASS"
    assert _check_lint(profile).status == "PASS"


def test_empty_dir_severities(tmp_path: Path) -> None:
    # Cenário 2 do prompt (cobre AC-2 parcial): diretório vazio (sem manifest).
    profile = analyze_project(tmp_path)

    manifest = _by_code(_check_manifest(profile), "manifest_present")
    assert manifest.status == "FAIL"
    assert manifest.fix

    tests_cat = _check_tests(profile)
    runner = _by_code(tests_cat, "test_runner_detected")
    assert runner.status == "FAIL"
    assert runner.fix
    files = _by_code(tests_cat, "test_files_present")
    assert files.status == "WARNING"
    assert files.fix

    lint = _by_code(_check_lint(profile), "linter_configured")
    assert lint.status == "WARNING"
    assert lint.fix


def test_python_runner_without_tests_dir(tmp_path: Path) -> None:
    # Cenário 3 do prompt (cobre AC-3): pytest declarado, SEM tests/ →
    # test_runner_detected PASS, test_files_present WARNING.
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_PYTEST_NO_RUFF, encoding="utf-8")
    profile = analyze_project(tmp_path)

    cat = _check_tests(profile)
    assert _by_code(cat, "test_runner_detected").status == "PASS"
    files = _by_code(cat, "test_files_present")
    assert files.status == "WARNING"
    assert cat.status == "WARNING"


def test_test_files_present_message_does_not_claim_absolute_absence(tmp_path: Path) -> None:
    # Cenário 4 do prompt: a message do WARNING NÃO pode afirmar ausência
    # absoluta de testes; deve refletir "convenção não observada em disco".
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_PYTEST_NO_RUFF, encoding="utf-8")
    profile = analyze_project(tmp_path)

    files = _by_code(_check_tests(profile), "test_files_present")
    assert files.status == "WARNING"
    msg = files.message.lower()
    # reflete a convenção não observada em disco...
    assert "convenção" in msg
    assert "não observada" in msg
    # ...e NÃO afirma que não existe teste algum.
    assert "nenhum teste" not in msg
    assert "ausência" not in msg
    assert "sem testes" not in msg


def test_runner_fix_is_contextual_to_javascript(tmp_path: Path) -> None:
    # Fix contextual: repo Node sem script test → fix menciona package.json.
    (tmp_path / "package.json").write_text('{"name": "mock"}', encoding="utf-8")
    profile = analyze_project(tmp_path)

    runner = _by_code(_check_tests(profile), "test_runner_detected")
    assert runner.status == "FAIL"
    assert "package.json" in runner.fix


def test_runner_fix_is_contextual_to_python(tmp_path: Path) -> None:
    # Fix contextual: repo Python sem pytest → fix menciona pytest.
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "mock"\nversion = "0.1.0"\n', encoding="utf-8"
    )
    profile = analyze_project(tmp_path)

    runner = _by_code(_check_tests(profile), "test_runner_detected")
    assert runner.status == "FAIL"
    assert "pytest" in runner.fix.lower()


# ---------------------------------------------------------------------------
# T-04 — run_preflight(): orquestração das 4 categorias + garantia read-only.
# ---------------------------------------------------------------------------

def _tree_snapshot(target_dir: Path) -> list[tuple[str, int]]:
    """Snapshot (path relativo POSIX + mtime_ns) da árvore, EXCLUINDO `.git/`.

    `.git/` é excluído de propósito: `git status` faz refresh de stat-cache no
    index (comportamento interno do git, não escrita do preflight — mitigado
    por `--no-optional-locks` mas não contratualmente garantido). Tudo FORA de
    `.git/` deve permanecer byte-a-byte idêntico após o preflight.
    """
    snapshot: list[tuple[str, int]] = []
    for p in target_dir.rglob("*"):
        rel = p.relative_to(target_dir)
        if rel.parts and rel.parts[0] == ".git":
            continue
        snapshot.append((rel.as_posix(), p.stat().st_mtime_ns))
    return sorted(snapshot)


def test_run_preflight_ready_full_repo(tmp_path: Path) -> None:
    # AC-1: git init + 1 commit + .gitignore + pyproject (pytest + ruff) +
    # tests/test_x.py → READY com as 4 categorias PASS.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    _write_python_repo_complete(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "baseline pré-harness")

    report = run_preflight(tmp_path)

    assert report.verdict == "READY"
    assert report.target == str(tmp_path.resolve())
    # ordem contratada das categorias.
    assert [cat.id for cat in report.categories] == ["git", "manifest", "tests", "lint"]
    for cat in report.categories:
        assert cat.status == "PASS", f"categoria {cat.id} não-PASS: {cat.status}"


def test_run_preflight_not_ready_empty_dir(tmp_path: Path) -> None:
    # AC-2: diretório vazio (sem git, sem manifest) → NOT_READY; todo check
    # não-PASS do laudo inteiro tem `fix` não-vazio (invariante de integração).
    report = run_preflight(tmp_path)

    assert report.verdict == "NOT_READY"
    for cat in report.categories:
        for check in cat.checks:
            if check.status != "PASS":
                assert check.fix, (
                    f"check '{check.code}' ({check.status}) sem fix acionável"
                )
    # confirma os FAILs esperados do repo cru.
    assert _by_code(report.categories[0], "git_repo").status == "FAIL"
    assert _by_code(report.categories[1], "manifest_present").status == "FAIL"
    assert _by_code(report.categories[2], "test_runner_detected").status == "FAIL"


def test_run_preflight_is_read_only(tmp_path: Path) -> None:
    # AC-5 (o mais importante): repo git REAL com >=1 commit — único jeito de
    # exercitar o caminho de subprocess do detector Git, onde mora o risco de
    # escrita. Snapshot antes/depois idêntico EXCLUINDO `.git/`; e `.harness/`
    # NÃO pode nascer (confirma uso de analyze_project puro, sem write_profile).
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("*.pyc\n", encoding="utf-8")
    _write_python_repo_complete(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "baseline")

    before = _tree_snapshot(tmp_path)
    report = run_preflight(tmp_path)
    after = _tree_snapshot(tmp_path)

    # o caminho de subprocess foi de fato exercitado (repo com commit).
    assert _by_code(report.categories[0], "git_baseline_commit").status == "PASS"
    assert _by_code(report.categories[0], "git_worktree_clean").status == "PASS"

    # nada escrito/alterado/removido fora de `.git/`.
    assert before == after
    # nenhum `.harness/` nasceu no alvo (sem write_profile).
    assert not (tmp_path / ".harness").exists()


def test_run_preflight_raises_on_nonexistent_path(tmp_path: Path) -> None:
    missing = tmp_path / "nao_existe"
    with pytest.raises(PreflightError):
        run_preflight(missing)


def test_run_preflight_raises_on_file_target(tmp_path: Path) -> None:
    file_target = tmp_path / "arquivo.txt"
    file_target.write_text("sou um arquivo, não um diretório", encoding="utf-8")
    with pytest.raises(PreflightError):
        run_preflight(file_target)


# ---------------------------------------------------------------------------
# T-05 — CLI: subcomando `harness preflight --dir` e exit codes 0/1/2 (AC-6).
# Invoca harness.cli.main() com argv monkeypatched, capturando stdout/stderr
# e o SystemExit (o CLI sempre chama sys.exit).
# ---------------------------------------------------------------------------

def test_cli_preflight_ready_exit_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    # AC-6: alvo READY (repo completo do AC-1) → exit 0; stdout é JSON válido
    # com verdict == "READY".
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    _write_python_repo_complete(tmp_path)
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "baseline pré-harness")

    monkeypatch.setattr(sys, "argv", ["harness", "preflight", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main()

    assert excinfo.value.code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["verdict"] == "READY"
    assert parsed["target"] == str(tmp_path.resolve())


def test_cli_preflight_warnings_only_exit_zero(tmp_path: Path, monkeypatch, capsys) -> None:
    # AC-6: alvo só com WARNINGs (repo git limpo+commit+.gitignore, pyproject
    # com pytest e tests/, mas SEM linter configurado) → exit 0, verdict
    # READY_WITH_WARNINGS.
    _init_repo(tmp_path)
    (tmp_path / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT_PYTEST_NO_RUFF, encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-m", "baseline")

    monkeypatch.setattr(sys, "argv", ["harness", "preflight", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main()

    assert excinfo.value.code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == "READY_WITH_WARNINGS"


def test_cli_preflight_not_ready_exit_one(tmp_path: Path, monkeypatch, capsys) -> None:
    # AC-6: alvo NOT_READY (dir vazio) → exit 1; verdict NOT_READY no stdout.
    monkeypatch.setattr(sys, "argv", ["harness", "preflight", "--dir", str(tmp_path)])
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main()

    assert excinfo.value.code == 1
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["verdict"] == "NOT_READY"


def test_cli_preflight_missing_path_exit_two(tmp_path: Path, monkeypatch, capsys) -> None:
    # AC-6: --dir apontando p/ path inexistente → exit 2; mensagem em stderr,
    # stdout sem JSON.
    missing = tmp_path / "nao_existe"
    monkeypatch.setattr(sys, "argv", ["harness", "preflight", "--dir", str(missing)])
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "erro:" in captured.err


# ---------------------------------------------------------------------------
# T-06 — Skill /harness-creator:preflight (AC-9). Lê o SKILL.md real do disco,
# parseia o frontmatter YAML (mesmo padrão de delimitadores `---`/`---` que
# contract.parse_spec usa para spec.md) e valida campos + comando do CLI no corpo.
# ---------------------------------------------------------------------------

_SKILL_PATH = Path(__file__).resolve().parents[1] / "skills" / "preflight" / "SKILL.md"


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Parseia o frontmatter YAML entre a 1ª e a 2ª ocorrência de `---`.

    Retorna (frontmatter_dict, corpo). Reimplementação simples do padrão de
    delimitação de contract.parse_spec — não importa parse_spec porque aquele é
    específico do formato de spec.md; aqui basta o YAML entre os delimitadores.
    """
    import yaml

    lines = text.splitlines()
    assert lines and lines[0].strip() == "---", "SKILL.md deve começar com '---'"
    closing = None
    for offset, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            closing = offset
            break
    assert closing is not None, "frontmatter YAML sem delimitador de fechamento"
    frontmatter = yaml.safe_load("\n".join(lines[1:closing])) or {}
    body = "\n".join(lines[closing + 1:])
    return frontmatter, body


def test_preflight_skill_frontmatter_and_body() -> None:
    assert _SKILL_PATH.is_file(), f"SKILL.md ausente em {_SKILL_PATH}"
    text = _SKILL_PATH.read_text(encoding="utf-8")

    frontmatter, body = _split_frontmatter(text)

    for field in ("name", "description", "when_to_use"):
        assert field in frontmatter, f"campo obrigatório '{field}' ausente do frontmatter"
        value = frontmatter[field]
        assert isinstance(value, str), f"'{field}' deve ser string, veio {type(value)}"
        assert value.strip(), f"'{field}' não pode ser vazio"

    assert frontmatter["name"] == "preflight"
    # o corpo referencia o comando real do CLI.
    assert "python -m harness.cli preflight --dir" in body


def test_cli_preflight_unicode_target_emits_valid_utf8_json(tmp_path: Path) -> None:
    # F-01: alvo com nome fora do cp1252 (cirílico + CJK). O CLI REAL via
    # subprocess deve emitir JSON UTF-8 válido — sem o fix de reconfigure() no
    # main(), o stdout piped em cp1252 crasharia com UnicodeEncodeError ao serializar
    # o `target` com ensure_ascii=False. Invocado como os testes de CLI por subprocess
    # (PYTHONPATH=src), não in-process.
    alvo = tmp_path / "репо_测试"
    alvo.mkdir()

    src_dir = Path(__file__).resolve().parents[1] / "src"
    proc = subprocess.run(
        [sys.executable, "-m", "harness.cli", "preflight", "--dir", str(alvo)],
        capture_output=True,
        encoding="utf-8",
        env=os.environ | {"PYTHONPATH": str(src_dir)},
        timeout=60,
    )

    # dir vazio = NOT_READY → exit 1.
    assert proc.returncode == 1, f"esperado exit 1, veio {proc.returncode}\n{proc.stderr}"
    # JSON parseável prova que o stdout veio em UTF-8 válido (sem crash de encoding).
    parsed = json.loads(proc.stdout)
    assert parsed["verdict"] == "NOT_READY"
    # o nome unicode aparece no campo target.
    assert "репо_测试" in parsed["target"]


def test_cli_preflight_file_target_exit_two(tmp_path: Path, monkeypatch, capsys) -> None:
    # AC-6: --dir apontando p/ um arquivo (não diretório) → exit 2.
    file_target = tmp_path / "arquivo.txt"
    file_target.write_text("sou arquivo", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["harness", "preflight", "--dir", str(file_target)])
    with pytest.raises(SystemExit) as excinfo:
        cli_mod.main()

    assert excinfo.value.code == 2
    captured = capsys.readouterr()
    assert captured.out.strip() == ""
    assert "erro:" in captured.err
