"""Testes do templates (Fase 2): `claude-progress.md` inicial e `init.sh`/
`init.ps1` gerados a partir do `repo-profile.json` compilado."""

from __future__ import annotations

from pathlib import Path

from harness.templates import (
    CLAUDE_PROGRESS_FILE,
    INIT_PS1_FILE,
    INIT_SH_FILE,
    install_templates,
    render_init_scripts,
    render_progress_template,
    update_progress_status,
)


_FEATURE_LIST = {
    "contract": "exemplo-feature",
    "compiled_at": "2026-07-15T12:00:00+00:00",
    "features": [
        {
            "id": "T-01",
            "desc": "Criar módulo de configuração",
            "files": ["src/harness/config.py"],
            "verify_cmd": "pytest tests/test_config.py -q",
            "depends": [],
            "passes": False,
        },
        {
            "id": "T-02",
            "desc": "Integrar configuração no compilador",
            "files": ["src/harness/compiler.py"],
            "verify_cmd": "pytest tests/test_compiler.py -q",
            "depends": ["T-01"],
            "passes": False,
        },
    ],
}


# ---------------------------------------------------------------------------
# render_progress_template
# ---------------------------------------------------------------------------

def test_render_progress_template_lists_all_features_as_pending() -> None:
    content = render_progress_template(_FEATURE_LIST)

    assert "T-01" in content
    assert "T-02" in content
    assert "Criar módulo de configuração" in content
    assert "Integrar configuração no compilador" in content
    # cada feature aparece com status inicial 'pending' (passes: false)
    assert content.count("pending") == 2
    assert "## Última atualização" in content


def test_render_progress_template_empty_features() -> None:
    content = render_progress_template({"contract": "vazio", "features": []})

    assert "Nenhuma feature" in content


# ---------------------------------------------------------------------------
# update_progress_status (US-2)
# ---------------------------------------------------------------------------

def test_update_progress_status_flips_matching_row_to_done(tmp_path: Path) -> None:
    (tmp_path / CLAUDE_PROGRESS_FILE).write_text(
        render_progress_template(_FEATURE_LIST), encoding="utf-8"
    )

    update_progress_status(tmp_path, "T-02", "done")

    content = (tmp_path / CLAUDE_PROGRESS_FILE).read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.startswith("| T-")]
    row_by_id = {ln.split("|")[1].strip(): ln for ln in lines}
    assert row_by_id["T-02"].split("|")[3].strip() == "done"
    # a outra feature permanece intacta
    assert row_by_id["T-01"].split("|")[3].strip() == "pending"


def test_update_progress_status_is_idempotent(tmp_path: Path) -> None:
    (tmp_path / CLAUDE_PROGRESS_FILE).write_text(
        render_progress_template(_FEATURE_LIST), encoding="utf-8"
    )

    update_progress_status(tmp_path, "T-01", "done")
    once = (tmp_path / CLAUDE_PROGRESS_FILE).read_text(encoding="utf-8")
    update_progress_status(tmp_path, "T-01", "done")
    twice = (tmp_path / CLAUDE_PROGRESS_FILE).read_text(encoding="utf-8")

    assert once == twice
    assert once.count("done") == 1


def test_update_progress_status_noop_when_file_absent(tmp_path: Path) -> None:
    # não levanta e não cria o arquivo
    update_progress_status(tmp_path, "T-01", "done")
    assert not (tmp_path / CLAUDE_PROGRESS_FILE).exists()


def test_update_progress_status_noop_when_id_absent(tmp_path: Path) -> None:
    original = render_progress_template(_FEATURE_LIST)
    (tmp_path / CLAUDE_PROGRESS_FILE).write_text(original, encoding="utf-8")

    update_progress_status(tmp_path, "T-99", "done")

    assert (tmp_path / CLAUDE_PROGRESS_FILE).read_text(encoding="utf-8") == original


def test_update_progress_status_preserves_ultima_atualizacao_section(tmp_path: Path) -> None:
    content = render_progress_template(_FEATURE_LIST)
    content += "\nNota livre do agente: quebrou X, ver Y.\n"
    (tmp_path / CLAUDE_PROGRESS_FILE).write_text(content, encoding="utf-8")

    update_progress_status(tmp_path, "T-01", "done")

    after = (tmp_path / CLAUDE_PROGRESS_FILE).read_text(encoding="utf-8")
    assert "## Última atualização" in after
    assert "Nota livre do agente: quebrou X, ver Y." in after


# ---------------------------------------------------------------------------
# render_init_scripts
# ---------------------------------------------------------------------------

def test_render_init_scripts_npm_generates_npm_ci_in_both_scripts() -> None:
    profile = {
        "package_manager": {"value": "npm", "evidence": "package-lock.json", "confidence": 1.0},
        "test_command": {"value": "npm test", "evidence": "package.json", "confidence": 1.0},
    }

    init_sh, init_ps1 = render_init_scripts(profile)

    assert "npm ci" in init_sh
    assert "npm ci" in init_ps1
    assert "npm test" in init_sh
    assert "npm test" in init_ps1
    assert init_sh.startswith("#!/usr/bin/env bash")
    assert "set -e" in init_sh
    assert init_ps1.startswith("$ErrorActionPreference = 'Stop'")


def test_render_init_scripts_missing_package_manager_key_generates_comment() -> None:
    profile = {"test_command": {"value": "pytest", "evidence": "pyproject.toml", "confidence": 1.0}}

    init_sh, init_ps1 = render_init_scripts(profile)

    assert "nenhum package manager detectado" in init_sh
    assert "nenhum package manager detectado" in init_ps1
    assert "pytest" in init_sh
    assert "pytest" in init_ps1


def test_render_init_scripts_explicit_none_package_manager_generates_comment() -> None:
    """`package_manager: None` explícito (chave presente, valor None) é o
    formato real do repo-profile.json quando nenhum lockfile é detectado —
    NÃO pode lançar AttributeError."""
    profile = {"package_manager": None, "test_command": None}

    init_sh, init_ps1 = render_init_scripts(profile)

    assert "nenhum package manager detectado" in init_sh
    assert "nenhum package manager detectado" in init_ps1
    assert "nenhum test_command detectado" in init_sh
    assert "nenhum test_command detectado" in init_ps1


def test_render_init_scripts_missing_test_command_generates_comment() -> None:
    profile = {"package_manager": {"value": "uv", "evidence": "uv.lock", "confidence": 1.0}}

    init_sh, init_ps1 = render_init_scripts(profile)

    assert "uv sync" in init_sh
    assert "uv sync" in init_ps1
    assert "nenhum test_command detectado" in init_sh
    assert "nenhum test_command detectado" in init_ps1


# ---------------------------------------------------------------------------
# install_templates
# ---------------------------------------------------------------------------

def test_render_init_scripts_pip_generates_pip_install_editable(tmp_path: Path) -> None:
    profile = {"package_manager": {"value": "pip", "evidence": "pyproject.toml", "confidence": 0.6}}

    init_sh, init_ps1 = render_init_scripts(profile)

    assert "pip install -e ." in init_sh
    assert "pip install -e ." in init_ps1


def test_install_templates_creates_three_files_in_empty_dir(tmp_path: Path) -> None:
    profile = {
        "package_manager": {"value": "poetry", "evidence": "poetry.lock", "confidence": 1.0},
        "test_command": {"value": "pytest", "evidence": "pyproject.toml", "confidence": 1.0},
    }

    written = install_templates(tmp_path, _FEATURE_LIST, profile)

    progress_path = tmp_path / CLAUDE_PROGRESS_FILE
    init_sh_path = tmp_path / INIT_SH_FILE
    init_ps1_path = tmp_path / INIT_PS1_FILE

    assert set(written) == {progress_path, init_sh_path, init_ps1_path}
    assert progress_path.is_file()
    assert init_sh_path.is_file()
    assert init_ps1_path.is_file()
    assert "poetry install" in init_sh_path.read_text(encoding="utf-8")


def test_install_templates_preserves_existing_progress_but_regenerates_init(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / CLAUDE_PROGRESS_FILE
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    custom_content = "# Progresso customizado pelo agente\n\nJá fiz T-01.\n"
    progress_path.write_text(custom_content, encoding="utf-8")

    npm_profile = {
        "package_manager": {"value": "npm", "evidence": "package-lock.json", "confidence": 1.0},
        "test_command": None,
    }
    written_first = install_templates(tmp_path, _FEATURE_LIST, npm_profile)

    # claude-progress.md já existia -> não entra na lista de escritos, e o
    # conteúdo customizado é preservado.
    assert progress_path not in written_first
    assert progress_path.read_text(encoding="utf-8") == custom_content

    # init.sh/init.ps1 são regenerados com o profile novo (pnpm).
    pnpm_profile = {
        "package_manager": {"value": "pnpm", "evidence": "pnpm-lock.yaml", "confidence": 1.0},
        "test_command": {"value": "pytest", "evidence": "pyproject.toml", "confidence": 1.0},
    }
    written_second = install_templates(tmp_path, _FEATURE_LIST, pnpm_profile)

    assert progress_path not in written_second
    assert progress_path.read_text(encoding="utf-8") == custom_content

    init_sh_content = (tmp_path / INIT_SH_FILE).read_text(encoding="utf-8")
    assert "pnpm install --frozen-lockfile" in init_sh_content
    assert "pytest" in init_sh_content


def test_install_templates_regenerates_progress_when_contract_diverges(
    tmp_path: Path,
) -> None:
    """Achado A (dogfood 2026-07-22): `claude-progress.md` gerado por um
    contrato ANTIGO (`compilar-x`) não pode sobreviver a uma recompilação
    para um contrato NOVO (`exemplo-feature`) — senão o agente lê o header
    e a tabela de features de um contrato que não é mais o ativo."""
    old_feature_list = {
        "contract": "compilar-x",
        "features": [
            {"id": "OLD-01", "desc": "Feature do contrato antigo", "passes": False},
        ],
    }
    progress_path = tmp_path / CLAUDE_PROGRESS_FILE
    progress_path.write_text(render_progress_template(old_feature_list), encoding="utf-8")

    profile = {"package_manager": None, "test_command": None}
    written = install_templates(tmp_path, _FEATURE_LIST, profile)

    assert progress_path in written
    new_content = progress_path.read_text(encoding="utf-8")
    assert "exemplo-feature" in new_content
    assert "T-01" in new_content
    assert "compilar-x" not in new_content
    assert "OLD-01" not in new_content


def test_install_templates_regenerate_preserves_ultima_atualizacao_notes(
    tmp_path: Path,
) -> None:
    old_feature_list = {"contract": "compilar-x", "features": []}
    progress_path = tmp_path / CLAUDE_PROGRESS_FILE
    old_content = render_progress_template(old_feature_list)
    old_content += "Nota livre do agente: quebrou X, ver Y.\n"
    progress_path.write_text(old_content, encoding="utf-8")

    profile = {"package_manager": None, "test_command": None}
    install_templates(tmp_path, _FEATURE_LIST, profile)

    new_content = progress_path.read_text(encoding="utf-8")
    assert "Nota livre do agente: quebrou X, ver Y." in new_content
    assert "exemplo-feature" in new_content


def test_install_templates_same_contract_does_not_regenerate_progress(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / CLAUDE_PROGRESS_FILE
    original = render_progress_template(_FEATURE_LIST)
    progress_path.write_text(original, encoding="utf-8")

    profile = {"package_manager": None, "test_command": None}
    written = install_templates(tmp_path, _FEATURE_LIST, profile)

    assert progress_path not in written
    assert progress_path.read_text(encoding="utf-8") == original
