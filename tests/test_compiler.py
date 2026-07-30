"""Testes do compilador (pivot plugin): harness.yaml -> governança nativa."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import __version__ as _HARNESS_VERSION
from harness.compiler import AGENTS_BEGIN, AGENTS_END, STATE_FILE, compile_project, render
from harness.config import HarnessConfig


def _write_yaml(target: Path, content: str) -> None:
    path = target / ".harness" / "harness.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


BASIC_YAML = """
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "pytest -x --tb=short"
  test_glob: "tests/**/*.py"
"""


# ---------------- render: mapeamento de permissions por política ----------------

def _rules_for(policy: str, tmp_path: Path) -> dict[str, list[str]]:
    config = HarnessConfig.model_validate({"governance": {"approval_policy": policy}})
    return render(config, tmp_path).permission_rules


def test_balanced_asks_for_all_state_changes(tmp_path: Path) -> None:
    rules = _rules_for("balanced", tmp_path)
    assert "Bash" in rules["ask"]
    assert "Edit" in rules["ask"] and "Write" in rules["ask"]
    assert "WebFetch" in rules["ask"]
    assert "Read" in rules["allow"]


def test_paranoid_asks_even_for_reads(tmp_path: Path) -> None:
    rules = _rules_for("paranoid", tmp_path)
    assert "Read" in rules["ask"]
    assert rules["allow"] == []


def test_auto_still_gates_network(tmp_path: Path) -> None:
    rules = _rules_for("auto", tmp_path)
    assert "WebFetch" in rules["ask"] and "WebSearch" in rules["ask"]
    assert "Bash(curl *)" in rules["ask"]
    assert "Bash" in rules["allow"]          # auto libera execute...
    assert "Bash" not in rules["ask"]
    # ...mas rede nunca vai para allow
    assert all("curl" not in r and "WebFetch" not in r for r in rules["allow"])


@pytest.mark.parametrize("enforce_tdd", [True, False], ids=["tdd-on", "tdd-off"])
def test_render_never_generates_a_bash_hook_file(tmp_path: Path, enforce_tdd: bool) -> None:
    """`render()` não gera nem registra hook próprio nenhum, com `enforce_tdd`
    ligado ou desligado. `guard_tests.py` não é gerado desde T-04/onda-1
    (proteção de edição de teste é do boundary_guard, por-tarefa); e
    `guard_test_runner.py` (matcher Bash, sempre-`allow`, nunca lia o
    payload) deixou de ser gerado/registrado em T-01/onda-3 — media ~125ms
    por chamada de Bash sem mudar nenhuma decisão, já que o boundary_guard.py
    (instalado à parte, matcher `*`) já cobre todo Bash."""
    config = HarnessConfig.model_validate({"verification": {"enforce_tdd": enforce_tdd}})
    artifacts = render(config, tmp_path)
    assert artifacts.hook_files == {}
    assert artifacts.hook_entries == []


def test_ignored_sections_generate_warning(tmp_path: Path) -> None:
    config = HarnessConfig.model_validate({})
    artifacts = render(config, tmp_path, raw_keys={"governance", "sandbox", "routing"})
    assert any("sandbox" in w for w in artifacts.warnings)


# ---------------- compile_project: escrita e merge ----------------

def test_compile_writes_all_artifacts(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    result = compile_project(tmp_path)

    settings = json.loads(result.settings_path.read_text(encoding="utf-8"))
    assert "Bash" in settings["permissions"]["ask"]
    hook_cmds = json.dumps(settings["hooks"]["PreToolUse"])
    # Nem `guard_tests.py` (T-04/onda-1) nem `guard_test_runner.py`
    # (T-01/onda-3) são gerados/registrados por `compile_project` — a
    # proteção de teste e o roteamento de `Bash` são do `boundary_guard.py`,
    # instalado à parte por `install_boundary_guard` no mesmo comando
    # `harness compile`. Ver docs/project/HISTORICO-boundary_guard-2026-07-30.md.
    assert "guard_tests.py" not in hook_cmds
    assert "guard_test_runner.py" not in hook_cmds
    assert not (tmp_path / ".harness" / "hooks" / "guard_tests.py").exists()
    assert not (tmp_path / ".harness" / "hooks" / "guard_test_runner.py").exists()

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert AGENTS_BEGIN in agents and AGENTS_END in agents


def test_compile_never_writes_machine_paths_into_the_versioned_settings(tmp_path: Path) -> None:
    """P0 do laudo de footprint: o comando de hook leva path absoluto desta
    máquina. Se cair no `settings.json` que o time versiona, um clone em outro
    path carrega um PreToolUse que não resolve — repo parece governado e
    nenhum guard roda. Destino tem que ser o arquivo machine-local, já
    ignorado por um `.gitignore` que o próprio produto escreve."""
    _write_yaml(tmp_path, BASIC_YAML)
    result = compile_project(tmp_path)

    assert result.settings_path == tmp_path / ".claude" / "settings.local.json"
    assert not (tmp_path / ".claude" / "settings.json").exists()

    claude_ignore = (tmp_path / ".claude" / ".gitignore").read_text(encoding="utf-8")
    assert "settings.local.json" in claude_ignore.split()
    harness_ignore = (tmp_path / ".harness" / ".gitignore").read_text(encoding="utf-8")
    assert "hooks/" in harness_ignore.split()
    assert "compiled-state.json" in harness_ignore.split()


def test_compile_creates_the_scratch_surface_it_tells_the_agent_to_use(
    tmp_path: Path,
) -> None:
    """D3 do teste isento: o bloco gerenciado que `compile` escreve no
    `AGENTS.md` manda salvar artefato temporário em `.harness/scratch/` — mas a
    pasta só nascia no `compile-session`. Entre um comando e outro a instrução
    apontava para um diretório inexistente."""
    _write_yaml(tmp_path, BASIC_YAML)
    result = compile_project(tmp_path)

    scratch = tmp_path / ".harness" / "scratch"
    assert scratch.is_dir()
    # Auto-ignorada: o git status fica limpo mesmo com screenshot esquecido lá,
    # sem encostar no .gitignore da raiz do usuário.
    assert (scratch / ".gitignore").read_text(encoding="utf-8") == "*\n!.gitignore\n"

    agents = result.agents_path.read_text(encoding="utf-8")
    assert ".harness/scratch/" in agents


def test_compile_preserves_a_customized_scratch_gitignore(tmp_path: Path) -> None:
    """O `.gitignore` do scratch pode ter sido customizado — recompilar não
    pode sobrescrever."""
    _write_yaml(tmp_path, BASIC_YAML)
    scratch = tmp_path / ".harness" / "scratch"
    scratch.mkdir(parents=True)
    (scratch / ".gitignore").write_text("*\n!.gitignore\n!manter.png\n", encoding="utf-8")

    compile_project(tmp_path)

    assert "!manter.png" in (scratch / ".gitignore").read_text(encoding="utf-8")


def test_compile_stamps_plugin_version_in_state_file(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)

    state = json.loads((tmp_path / STATE_FILE).read_text(encoding="utf-8"))
    assert state["plugin_version"] == _HARNESS_VERSION


def test_merge_preserves_user_settings_and_is_idempotent(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    (claude_dir / "settings.local.json").write_text(json.dumps({
        "model": "opus",
        "permissions": {"allow": ["Bash(npm run *)"], "deny": ["Read(.env)"]},
        "hooks": {"PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-hook.sh"}]}
        ]},
    }), encoding="utf-8")

    compile_project(tmp_path)
    compile_project(tmp_path)  # segunda rodada: idempotente, sem duplicar

    settings = json.loads((claude_dir / "settings.local.json").read_text(encoding="utf-8"))
    assert settings["model"] == "opus"                                  # chave alheia intacta
    assert "Bash(npm run *)" in settings["permissions"]["allow"]        # regra do usuário intacta
    assert "Read(.env)" in settings["permissions"]["deny"]
    assert settings["permissions"]["ask"].count("Bash") == 1            # sem duplicata
    user_hooks = [e for e in settings["hooks"]["PreToolUse"]
                  if "meu-hook.sh" in json.dumps(e)]
    assert len(user_hooks) == 1                                         # hook do usuário intacto
    # `compiler.py` não registra hook próprio nenhum hoje (guard_tests.py
    # nem gera mais desde T-04/onda-1; guard_test_runner.py idem desde
    # T-01/onda-3) — a idempotência sob teste aqui é a de permissions/hooks
    # de usuário, cobertas pelas asserções acima.
    assert settings["hooks"]["PreToolUse"] == [
        {"matcher": "Bash", "hooks": [{"type": "command", "command": "meu-hook.sh"}]}
    ]


def test_recompile_after_policy_change_swaps_rules(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    _write_yaml(tmp_path, BASIC_YAML.replace("balanced", "auto"))
    compile_project(tmp_path)

    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    assert "Bash" in settings["permissions"]["allow"]   # auto libera execute
    assert "Bash" not in settings["permissions"]["ask"] # regra antiga removida


def test_agents_block_regenerates_without_destroying_manual_text(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    (tmp_path / "AGENTS.md").write_text(
        f"# Meu projeto\n\nRegra manual minha.\n\n{AGENTS_BEGIN}\nvelho\n{AGENTS_END}\n",
        encoding="utf-8",
    )
    compile_project(tmp_path)
    text = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    assert "Regra manual minha." in text
    assert "velho" not in text
    assert text.count(AGENTS_BEGIN) == 1


def test_agents_block_does_not_repeat_fixed_text_already_in_the_manual_section(
    tmp_path: Path,
) -> None:
    """Onda 2/T-02: 'Escopo mínimo' e 'Sem segredos' eram texto FIXO no bloco
    gerado (sem interpolar `harness.yaml`) que já vive, com as mesmas
    palavras, na parte manual do AGENTS.md (ver AGENTS.md, Regras
    Inegociáveis 3-4) — a mesma regra declarada duas vezes no mesmo arquivo
    por dois mecanismos diferentes. O bloco gerado passa a carregar só o que
    de fato deriva do YAML: TDD/política de aprovação, orçamento, scratch."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)

    agents = (tmp_path / "AGENTS.md").read_text(encoding="utf-8")
    block = agents[agents.index(AGENTS_BEGIN):agents.index(AGENTS_END) + len(AGENTS_END)]
    assert "Escopo mínimo" not in block
    assert "Sem segredos" not in block
    # o que É derivado do YAML continua no bloco gerado
    assert "Política de aprovação" in block
    assert "Orçamento" in block


def test_compile_without_yaml_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="harness-creator:init"):
        compile_project(tmp_path)


# ---------------------------------------------------------------------------
# harness.yaml vazio / malformado (achados de teste isento)
# ---------------------------------------------------------------------------

def test_empty_harness_yaml_refuses_instead_of_compiling_python_defaults(
    tmp_path: Path,
) -> None:
    """Vazio caía em `{}` e compilava os defaults do schema — que são Python
    (`pytest`, `tests/**/*.py`). Num repo Angular/.NET isso protege um
    diretório inexistente e DEIXA DE proteger os testes reais: governança
    degradada em silêncio, com exit 0."""
    _write_yaml(tmp_path, "")

    with pytest.raises(ValueError, match="vazio"):
        compile_project(tmp_path)

    assert not (tmp_path / ".claude" / "settings.local.json").exists()
    assert not (tmp_path / "AGENTS.md").exists()


def test_malformed_harness_yaml_is_a_clean_error_not_a_traceback(tmp_path: Path) -> None:
    """Era o único caminho de erro do CLI inteiro que vazava stack do PyYAML."""
    _write_yaml(tmp_path, "isto: nao\n  e: [yaml valido\n")

    with pytest.raises(ValueError, match="YAML inválido"):
        compile_project(tmp_path)

    assert not (tmp_path / ".claude" / "settings.local.json").exists()


def test_non_mapping_harness_yaml_is_refused(tmp_path: Path) -> None:
    _write_yaml(tmp_path, "- isto\n- e uma lista\n")

    with pytest.raises(ValueError, match="mapeamento"):
        compile_project(tmp_path)
