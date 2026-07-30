"""Testes do templates (Fase 2): `.harness/progress.md` inicial e
`.harness/init.sh`/`.harness/init.ps1` gerados a partir do `repo-profile.json`
compilado."""

from __future__ import annotations

from pathlib import Path

from harness.templates import (
    INIT_PS1_FILE,
    INIT_SH_FILE,
    MANAGED_MARKER,
    PROGRESS_FILE,
    append_progress_note,
    install_templates,
    is_managed_init_script,
    manual_init_scripts,
    render_init_scripts,
    render_last_update_note,
    render_progress_template,
    update_progress_status,
)


def _write(path: Path, text: str) -> Path:
    """Grava criando o diretório pai — os três artefatos moram em `.harness/`,
    que nem sempre existe no `tmp_path` do teste."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


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
    _write(tmp_path / PROGRESS_FILE, render_progress_template(_FEATURE_LIST))

    update_progress_status(tmp_path, "T-02", "done")

    content = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    lines = [ln for ln in content.splitlines() if ln.startswith("| T-")]
    row_by_id = {ln.split("|")[1].strip(): ln for ln in lines}
    assert row_by_id["T-02"].split("|")[3].strip() == "done"
    # a outra feature permanece intacta
    assert row_by_id["T-01"].split("|")[3].strip() == "pending"


def test_update_progress_status_is_idempotent(tmp_path: Path) -> None:
    _write(tmp_path / PROGRESS_FILE, render_progress_template(_FEATURE_LIST))

    update_progress_status(tmp_path, "T-01", "done")
    once = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    update_progress_status(tmp_path, "T-01", "done")
    twice = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")

    assert once == twice
    assert once.count("done") == 1


def test_update_progress_status_noop_when_file_absent(tmp_path: Path) -> None:
    # não levanta e não cria o arquivo
    update_progress_status(tmp_path, "T-01", "done")
    assert not (tmp_path / PROGRESS_FILE).exists()


def test_update_progress_status_noop_when_id_absent(tmp_path: Path) -> None:
    original = render_progress_template(_FEATURE_LIST)
    _write(tmp_path / PROGRESS_FILE, original)

    update_progress_status(tmp_path, "T-99", "done")

    assert (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8") == original


def test_update_progress_status_preserves_ultima_atualizacao_section(tmp_path: Path) -> None:
    content = render_progress_template(_FEATURE_LIST)
    content += "\nNota livre do agente: quebrou X, ver Y.\n"
    _write(tmp_path / PROGRESS_FILE, content)

    update_progress_status(tmp_path, "T-01", "done")

    after = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "## Última atualização" in after
    assert "Nota livre do agente: quebrou X, ver Y." in after


# ---------------------------------------------------------------------------
# append_progress_note (item 4 do backlog do dogfood miojo)
# ---------------------------------------------------------------------------

def test_append_progress_note_creates_auto_block_below_heading(tmp_path: Path) -> None:
    _write(tmp_path / PROGRESS_FILE, render_progress_template(_FEATURE_LIST))

    assert append_progress_note(tmp_path, "2026-07-27T10:00:00+00:00 — T-01 verificado") is True

    after = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "<!-- harness:auto -->" in after
    assert "- 2026-07-27T10:00:00+00:00 — T-01 verificado" in after
    # o bloco entra ABAIXO do heading e o placeholder original segue intacto
    assert after.index("## Última atualização") < after.index("<!-- harness:auto -->")
    assert "_(vazio" in after


def test_append_progress_note_accumulates_and_preserves_human_prose(tmp_path: Path) -> None:
    content = render_progress_template(_FEATURE_LIST) + "\nNota livre: falta migrar Z.\n"
    _write(tmp_path / PROGRESS_FILE, content)

    append_progress_note(tmp_path, "t1 — T-01 verificado")
    append_progress_note(tmp_path, "t2 — T-02 verificado")

    after = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "- t1 — T-01 verificado" in after
    assert "- t2 — T-02 verificado" in after
    # a prosa do agente nunca é tocada pelo bloco automático
    assert "Nota livre: falta migrar Z." in after
    # e não vira um segundo bloco a cada nota
    assert after.count("<!-- harness:auto -->") == 1


def test_append_progress_note_keeps_only_the_most_recent_entries(tmp_path: Path) -> None:
    _write(tmp_path / PROGRESS_FILE, render_progress_template(_FEATURE_LIST))

    for i in range(13):
        append_progress_note(tmp_path, f"t{i:02d} — T-01 verificado")

    after = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "t00 —" not in after
    assert "t02 —" not in after
    assert "t03 —" in after
    assert "t12 —" in after


def test_append_progress_note_dedupes_same_feature_id(tmp_path: Path) -> None:
    """Onda 2/T-05: reverificar a MESMA feature (ex.: corrigir evidência
    stale) somava outra linha em vez de substituir — 44% do teto de 10
    entradas era repetição da mesma feature (achado #6 do laudo de
    simplificação). Passando `feature_id`, a entrada antiga dela é
    substituída; outras features não são tocadas."""
    _write(tmp_path / PROGRESS_FILE, render_progress_template(_FEATURE_LIST))

    append_progress_note(tmp_path, "t1 — T-01 verificado", feature_id="T-01")
    append_progress_note(tmp_path, "t2 — T-02 verificado", feature_id="T-02")
    append_progress_note(tmp_path, "t3 — T-01 verificado de novo", feature_id="T-01")

    after = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "t1 —" not in after
    assert "- t3 — T-01 verificado de novo" in after
    assert "- t2 — T-02 verificado" in after
    auto_block = after[after.index("<!-- harness:auto -->"):after.index("<!-- /harness:auto -->")]
    assert auto_block.count("T-01") == 1


def test_append_progress_note_without_feature_id_keeps_old_behavior(tmp_path: Path) -> None:
    """Sem `feature_id` (chamador antigo, se algum sobrar), acumula como
    antes — o parâmetro é aditivo, não muda comportamento por padrão."""
    _write(tmp_path / PROGRESS_FILE, render_progress_template(_FEATURE_LIST))

    append_progress_note(tmp_path, "t1 — T-01 verificado")
    append_progress_note(tmp_path, "t2 — T-01 verificado de novo")

    after = (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8")
    assert "- t1 — T-01 verificado" in after
    assert "- t2 — T-01 verificado de novo" in after


def test_append_progress_note_noop_when_file_or_heading_absent(tmp_path: Path) -> None:
    # arquivo ausente: no-op silencioso, nunca cria o esqueleto
    assert append_progress_note(tmp_path, "t — x") is False
    assert not (tmp_path / PROGRESS_FILE).exists()

    # arquivo sem o heading (agente reescreveu à mão): fica como está
    custom = "# Meu progresso\n\nsó texto meu\n"
    _write(tmp_path / PROGRESS_FILE, custom)
    assert append_progress_note(tmp_path, "t — x") is False
    assert (tmp_path / PROGRESS_FILE).read_text(encoding="utf-8") == custom


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
    assert init_sh.startswith("#!/usr/bin/env bash\n" + MANAGED_MARKER + "\n")
    assert "set -e" in init_sh
    assert init_ps1.startswith(MANAGED_MARKER + "\n$ErrorActionPreference = 'Stop'")


def test_generated_init_scripts_are_pure_ascii() -> None:
    """O `.ps1` gerado é lido pelo PowerShell 5.1, que corrompe UTF-8
    multi-byte: acento e travessão chegam ilegíveis no terminal do usuário.
    Vale para TODO o conteúdo gerado, não só o marcador — o comentário de
    "nenhum package manager detectado" trazia um travessão."""
    assert MANAGED_MARKER.isascii()
    for profile in (
        {"package_manager": None, "test_command": None},
        _NPM_PROFILE,
        {"package_manager": {"value": "uv"}, "test_command": {"value": "pytest -q"}},
    ):
        init_sh, init_ps1 = render_init_scripts(profile)
        assert init_sh.isascii(), init_sh
        assert init_ps1.isascii(), init_ps1


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

    progress_path = tmp_path / PROGRESS_FILE
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
    progress_path = tmp_path / PROGRESS_FILE
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    custom_content = "# Progresso customizado pelo agente\n\nJá fiz T-01.\n"
    progress_path.write_text(custom_content, encoding="utf-8")

    npm_profile = {
        "package_manager": {"value": "npm", "evidence": "package-lock.json", "confidence": 1.0},
        "test_command": None,
    }
    written_first = install_templates(tmp_path, _FEATURE_LIST, npm_profile)

    # .harness/progress.md já existia -> não entra na lista de escritos, e o
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
    """Achado A (dogfood 2026-07-22): `.harness/progress.md` gerado por um
    contrato ANTIGO (`compilar-x`) não pode sobreviver a uma recompilação
    para um contrato NOVO (`exemplo-feature`) — senão o agente lê o header
    e a tabela de features de um contrato que não é mais o ativo."""
    old_feature_list = {
        "contract": "compilar-x",
        "features": [
            {"id": "OLD-01", "desc": "Feature do contrato antigo", "passes": False},
        ],
    }
    progress_path = tmp_path / PROGRESS_FILE
    _write(progress_path, render_progress_template(old_feature_list))

    profile = {"package_manager": None, "test_command": None}
    written = install_templates(tmp_path, _FEATURE_LIST, profile)

    assert progress_path in written
    new_content = progress_path.read_text(encoding="utf-8")
    assert "exemplo-feature" in new_content
    assert "T-01" in new_content
    assert "compilar-x" not in new_content
    assert "OLD-01" not in new_content


def test_install_templates_regenerate_drops_auto_notes_whose_evidence_is_gone(
    tmp_path: Path,
) -> None:
    """Onda 2/T-05: na troca de contrato, `install_templates` copiava a seção
    'Última atualização' inteira para o `progress.md` novo — incluindo notas
    automáticas que citam evidência de um contrato que NÃO É MAIS o ativo
    (achado #6: '3 paths de evidência inexistentes e 2 features fantasma
    injetados'). Uma nota só sobrevive à troca se o arquivo de evidência que
    ela cita ainda existir em disco; o resto da seção (prosa humana) nunca é
    tocado."""
    old_feature_list = {"contract": "compilar-x", "features": []}
    progress_path = tmp_path / PROGRESS_FILE
    old_content = render_progress_template(old_feature_list)
    old_content = render_last_update_note(
        old_content,
        "t1 — OLD-01 verificado (exit_code 0) — .harness/evidence/compilar-x/OLD-01.json",
        feature_id="OLD-01",
    )
    old_content = render_last_update_note(
        old_content,
        "t2 — OLD-02 verificado (exit_code 0) — .harness/evidence/compilar-x/OLD-02.json",
        feature_id="OLD-02",
    )
    _write(progress_path, old_content)

    # só a evidência de OLD-02 sobrevive no disco — OLD-01 é a fantasma.
    evidence_dir = tmp_path / ".harness" / "evidence" / "compilar-x"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    (evidence_dir / "OLD-02.json").write_text("{}", encoding="utf-8")

    profile = {"package_manager": None, "test_command": None}
    install_templates(tmp_path, _FEATURE_LIST, profile)

    new_content = progress_path.read_text(encoding="utf-8")
    assert "OLD-01" not in new_content
    assert "OLD-02" in new_content


def test_install_templates_regenerate_preserves_ultima_atualizacao_notes(
    tmp_path: Path,
) -> None:
    old_feature_list = {"contract": "compilar-x", "features": []}
    progress_path = tmp_path / PROGRESS_FILE
    old_content = render_progress_template(old_feature_list)
    old_content += "Nota livre do agente: quebrou X, ver Y.\n"
    _write(progress_path, old_content)

    profile = {"package_manager": None, "test_command": None}
    install_templates(tmp_path, _FEATURE_LIST, profile)

    new_content = progress_path.read_text(encoding="utf-8")
    assert "Nota livre do agente: quebrou X, ver Y." in new_content
    assert "exemplo-feature" in new_content


def test_install_templates_same_contract_does_not_regenerate_progress(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / PROGRESS_FILE
    original = render_progress_template(_FEATURE_LIST)
    _write(progress_path, original)

    profile = {"package_manager": None, "test_command": None}
    written = install_templates(tmp_path, _FEATURE_LIST, profile)

    assert progress_path not in written
    assert progress_path.read_text(encoding="utf-8") == original


# ---------------------------------------------------------------------------
# guarda de colisão em init.* (item 5 do laudo de footprint)
# ---------------------------------------------------------------------------

_NPM_PROFILE = {
    "package_manager": {"value": "npm", "evidence": "package-lock.json", "confidence": 1.0},
    "test_command": None,
}


def test_install_templates_never_touches_the_project_root(tmp_path: Path) -> None:
    """Item 6: o alvo não recebe mais `claude-progress.md`/`init.*` na raiz —
    nenhum dos três é lido por ferramenta externa, e `init.sh` na raiz colide
    com o bootstrap do próprio projeto."""
    install_templates(tmp_path, _FEATURE_LIST, _NPM_PROFILE)

    assert sorted(p.name for p in tmp_path.iterdir()) == [".harness"]
    assert (tmp_path / ".harness" / "progress.md").is_file()
    assert (tmp_path / ".harness" / "init.sh").is_file()
    assert (tmp_path / ".harness" / "init.ps1").is_file()


def test_install_templates_preserves_hand_edited_init_scripts(tmp_path: Path) -> None:
    """Item 5: um `init.*` SEM o marcador foi escrito por gente — regenerar
    por cima apaga trabalho sem aviso. O arquivo fica intacto e sai da lista de
    escritos; `manual_init_scripts` é quem denuncia os dois."""
    meu_script = "#!/usr/bin/env bash\n./bootstrap-do-projeto.sh\n"
    init_sh = _write(tmp_path / INIT_SH_FILE, meu_script)
    init_ps1 = _write(tmp_path / INIT_PS1_FILE, "./bootstrap-do-projeto.ps1\n")

    written = install_templates(tmp_path, _FEATURE_LIST, _NPM_PROFILE)

    assert init_sh.read_text(encoding="utf-8") == meu_script
    assert "npm ci" not in init_ps1.read_text(encoding="utf-8")
    assert init_sh not in written and init_ps1 not in written
    assert set(manual_init_scripts(tmp_path)) == {init_sh, init_ps1}


def test_install_templates_regenerates_its_own_init_scripts(tmp_path: Path) -> None:
    """O outro lado da guarda: script COM marcador continua determinístico —
    trocar o profile regenera o conteúdo, e nada aparece como preservado."""
    install_templates(tmp_path, _FEATURE_LIST, _NPM_PROFILE)

    pnpm_profile = {
        "package_manager": {"value": "pnpm", "evidence": "pnpm-lock.yaml", "confidence": 1.0},
        "test_command": None,
    }
    written = install_templates(tmp_path, _FEATURE_LIST, pnpm_profile)

    init_sh = tmp_path / INIT_SH_FILE
    assert "pnpm install --frozen-lockfile" in init_sh.read_text(encoding="utf-8")
    assert init_sh in written
    assert manual_init_scripts(tmp_path) == []


def test_is_managed_init_script_treats_absent_as_managed(tmp_path: Path) -> None:
    """Ausente = nada do usuário a proteger, e o caminho normal é criar. Só a
    presença de conteúdo SEM o marcador bloqueia a regeneração."""
    assert is_managed_init_script(tmp_path / INIT_SH_FILE) is True

    hand_written = _write(tmp_path / INIT_SH_FILE, "echo oi\n")
    assert is_managed_init_script(hand_written) is False

    generated = _write(tmp_path / INIT_SH_FILE, render_init_scripts(_NPM_PROFILE)[0])
    assert is_managed_init_script(generated) is True
