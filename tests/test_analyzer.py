"""Testes do analyzer (Fase 1): schema evidence/confidence/unknowns e
detectores core de linguagem, manifest e teste, com repos sintéticos."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from harness.analyzer import (
    Finding,
    RepoProfile,
    analyze_project,
    write_profile,
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _finding_values(findings: list[Finding]) -> set[str]:
    return {f.value for f in findings}


# ---------------------------------------------------------------------------
# Repo Python
# ---------------------------------------------------------------------------

def _bootstrap_python(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
[project]
name = "sample"
dependencies = ["pytest>=8.0"]
""",
    )
    _write(tmp_path / "uv.lock", "# lockfile fake\n")
    _write(tmp_path / "tests" / "test_sample.py", "def test_ok():\n    assert True\n")


def test_python_project_detects_language_manifest_and_pytest(tmp_path: Path) -> None:
    _bootstrap_python(tmp_path)

    profile = analyze_project(tmp_path)

    assert _finding_values(profile.languages) == {"python"}
    assert profile.languages[0].evidence == "pyproject.toml"

    assert profile.package_manager is not None
    assert profile.package_manager.value == "uv"
    assert profile.package_manager.evidence == "uv.lock"

    assert profile.test_command is not None
    assert profile.test_command.value == "pytest"
    assert profile.test_command.evidence == "pyproject.toml"

    assert profile.test_glob is not None
    assert profile.test_glob.value == "tests/**/*.py"
    assert profile.test_glob.evidence == "tests/test_sample.py"

    assert profile.unknowns == []
    assert "pyproject.toml" in profile.manifest_snapshot
    assert "uv.lock" in profile.manifest_snapshot
    expected_hash = hashlib.sha256((tmp_path / "pyproject.toml").read_bytes()).hexdigest()
    assert profile.manifest_snapshot["pyproject.toml"] == expected_hash


def test_python_pytest_ini_detected_when_pyproject_silent(tmp_path: Path) -> None:
    _write(tmp_path / "pyproject.toml", "[project]\nname = \"sample\"\n")
    _write(tmp_path / "pytest.ini", "[pytest]\n")
    _write(tmp_path / "tests" / "test_sample.py", "def test_ok():\n    assert True\n")

    profile = analyze_project(tmp_path)

    assert profile.test_command is not None
    assert profile.test_command.value == "pytest"
    assert profile.test_command.evidence == "pytest.ini"


# ---------------------------------------------------------------------------
# Repo Node
# ---------------------------------------------------------------------------

def _bootstrap_node(tmp_path: Path) -> None:
    _write(
        tmp_path / "package.json",
        json.dumps({"name": "sample", "scripts": {"test": "jest --coverage"}}),
    )
    _write(tmp_path / "package-lock.json", "{}")
    _write(tmp_path / "src" / "sample.test.ts", "test('ok', () => {});\n")


def test_node_project_detects_manager_and_test_script(tmp_path: Path) -> None:
    _bootstrap_node(tmp_path)

    profile = analyze_project(tmp_path)

    assert _finding_values(profile.languages) == {"javascript"}
    assert profile.package_manager is not None
    assert profile.package_manager.value == "npm"
    assert profile.package_manager.evidence == "package-lock.json"

    assert profile.test_command is not None
    assert profile.test_command.value == "jest --coverage"
    assert profile.test_command.evidence == "package.json"

    assert profile.test_glob is not None
    assert profile.test_glob.value == "**/*.test.ts"
    assert profile.test_glob.evidence == "src/sample.test.ts"
    assert profile.unknowns == []


def test_node_project_with_tsconfig_adds_typescript_language(tmp_path: Path) -> None:
    _bootstrap_node(tmp_path)
    _write(tmp_path / "tsconfig.json", "{}")

    profile = analyze_project(tmp_path)

    assert _finding_values(profile.languages) == {"javascript", "typescript"}


def test_node_placeholder_test_script_is_not_a_runner(tmp_path: Path) -> None:
    _write(
        tmp_path / "package.json",
        json.dumps(
            {"name": "sample", "scripts": {"test": 'echo "Error: no test specified" && exit 1'}}
        ),
    )

    profile = analyze_project(tmp_path)

    assert profile.test_command is None
    assert "test_command: nenhum runner detectado" in profile.unknowns


# ---------------------------------------------------------------------------
# Repo vazio / unknowns
# ---------------------------------------------------------------------------

def test_empty_repo_populates_unknowns(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("nada aqui\n", encoding="utf-8")

    profile = analyze_project(tmp_path)

    assert profile.languages == []
    assert profile.package_manager is None
    assert profile.test_command is None
    assert profile.test_glob is None
    assert set(profile.unknowns) == {
        "languages: nenhum manifest reconhecido",
        "package_manager: nenhum lockfile detectado",
        "test_command: nenhum runner detectado",
        "test_glob: linguagem não detectada",
    }
    assert profile.manifest_snapshot == {}


def test_glob_without_matching_files_becomes_unknown(tmp_path: Path) -> None:
    # python detectável (pytest em deps) mas sem NENHUM arquivo tests/**/*.py
    _write(
        tmp_path / "pyproject.toml",
        "[project]\nname = \"sample\"\ndependencies = [\"pytest>=8.0\"]\n",
    )

    profile = analyze_project(tmp_path)

    assert profile.test_command is not None  # pytest detectado via dependency
    assert profile.test_glob is None
    assert "test_glob: nenhum arquivo casa a convenção de 'python'" in profile.unknowns


def test_skip_dirs_are_ignored(tmp_path: Path) -> None:
    _bootstrap_node(tmp_path)
    # manifest "fantasma" dentro de node_modules não deve virar evidência
    _write(tmp_path / "node_modules" / "dep" / "package.json", json.dumps({"name": "dep"}))

    profile = analyze_project(tmp_path)

    assert profile.package_manager.evidence == "package-lock.json"
    assert all("node_modules" not in f.evidence for f in profile.languages)


# ---------------------------------------------------------------------------
# to_dict/from_dict + write_profile
# ---------------------------------------------------------------------------

def test_finding_and_profile_round_trip_through_dict() -> None:
    profile = RepoProfile(
        languages=[Finding("python", "pyproject.toml", 1.0)],
        package_manager=Finding("uv", "uv.lock", 1.0),
        test_command=Finding("pytest", "pyproject.toml", 1.0),
        test_glob=Finding("tests/**/*.py", "tests/test_x.py", 1.0),
        extras={"lint": Finding("ruff", "pyproject.toml", 1.0)},
        unknowns=["algo: desconhecido"],
        analyzed_at="2026-07-15T00:00:00+00:00",
        manifest_snapshot={"pyproject.toml": "deadbeef"},
    )

    restored = RepoProfile.from_dict(json.loads(json.dumps(profile.to_dict())))

    assert restored == profile


# ---------------------------------------------------------------------------
# Detectores estendidos (extras): CI, docker-compose, monorepo, ruff
# ---------------------------------------------------------------------------

def test_ci_workflow_detected_in_extras(tmp_path: Path) -> None:
    _bootstrap_python(tmp_path)
    _write(
        tmp_path / ".github" / "workflows" / "ci.yml",
        "name: CI\non: [push]\njobs:\n  test:\n    runs-on: ubuntu-latest\n",
    )

    profile = analyze_project(tmp_path)

    assert "ci" in profile.extras
    ci = profile.extras["ci"]
    assert ci.value == ["ci.yml"]
    assert ci.evidence == ".github/workflows/ci.yml"


def test_docker_compose_services_detected_in_extras(tmp_path: Path) -> None:
    _bootstrap_python(tmp_path)
    _write(
        tmp_path / "docker-compose.yml",
        "services:\n  web:\n    image: sample\n  db:\n    image: postgres\n",
    )

    profile = analyze_project(tmp_path)

    assert "services" in profile.extras
    services = profile.extras["services"]
    assert services.value == ["db", "web"]
    assert services.evidence == "docker-compose.yml"


def test_monorepo_workspaces_detected_in_extras(tmp_path: Path) -> None:
    _write(
        tmp_path / "package.json",
        json.dumps({"name": "sample", "workspaces": ["packages/*"]}),
    )

    profile = analyze_project(tmp_path)

    assert "monorepo" in profile.extras
    monorepo = profile.extras["monorepo"]
    assert monorepo.value is True
    assert monorepo.evidence == "package.json"


def test_python_ruff_configured_detected_as_lint_command(tmp_path: Path) -> None:
    _write(
        tmp_path / "pyproject.toml",
        """
[project]
name = "sample"
dependencies = ["pytest>=8.0"]

[tool.ruff]
line-length = 100
""",
    )

    profile = analyze_project(tmp_path)

    assert "lint_command" in profile.extras
    lint = profile.extras["lint_command"]
    assert lint.value == "ruff check ."
    assert lint.evidence == "pyproject.toml"


def test_write_profile_writes_json_under_harness_dir(tmp_path: Path) -> None:
    _bootstrap_python(tmp_path)
    profile = analyze_project(tmp_path)

    written_path = write_profile(profile, tmp_path)

    assert written_path == tmp_path / ".harness" / "repo-profile.json"
    data = json.loads(written_path.read_text(encoding="utf-8"))
    assert data["languages"][0]["value"] == "python"
    assert data["test_command"]["value"] == "pytest"

    # regenerar do zero: chamar de novo não deve acumular lixo/duplicar chaves
    write_profile(profile, tmp_path)
    data_again = json.loads(written_path.read_text(encoding="utf-8"))
    assert data_again == data
