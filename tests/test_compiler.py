"""Testes do compilador (pivot plugin): harness.yaml -> governança nativa."""

from __future__ import annotations

import json
import subprocess
import sys
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


def test_enforce_tdd_false_drops_runner_hook(tmp_path: Path) -> None:
    config = HarnessConfig.model_validate({"verification": {"enforce_tdd": False}})
    artifacts = render(config, tmp_path)
    assert "guard_test_runner.py" not in artifacts.hook_files
    assert "guard_tests.py" in artifacts.hook_files  # edit_test sempre protegido


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
    assert "guard_test_runner.py" in hook_cmds
    # O `guard_tests.py` é gerado em disco mas NÃO registrado — issue #61. Este
    # assert afirmava o contrário e era a única fonte de verdade a favor do
    # registro, contra dois e2e que travam a ausência depois de
    # `install_boundary_guard`. Quem entrega o gate de edição de teste hoje é o
    # boundary_guard, por decisão por-tarefa.
    assert "guard_tests.py" not in hook_cmds

    assert (tmp_path / ".harness" / "hooks" / "guard_tests.py").is_file()
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
    # A idempotência é a regra sob teste; o sujeito mudou porque o
    # `guard_tests.py` deixou de ser registrado (issue #61). O guard que o
    # compilador registra hoje é o de execução de teste.
    guard_entries = [e for e in settings["hooks"]["PreToolUse"]
                     if "guard_test_runner.py" in json.dumps(e)]
    assert len(guard_entries) == 1                                      # sem duplicar o nosso


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


def test_compile_without_yaml_raises_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="harness-creator:init"):
        compile_project(tmp_path)


# ---------------- hooks gerados: standalone, executados de verdade ----------------

def _run_hook(script: Path, payload: dict) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input=json.dumps(payload), capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)["hookSpecificOutput"]


def test_guard_tests_hook_asks_for_test_and_allows_source(tmp_path: Path) -> None:
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    asks = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "tests/test_x.py"}})
    assert asks["permissionDecision"] == "ask"

    allows = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                                "tool_input": {"file_path": "src/main.py"}})
    assert allows["permissionDecision"] == "allow"

    # Path absoluto (forma que o Claude Code envia) também é reconhecido.
    abs_asks = _run_hook(script, {"tool_name": "Write", "cwd": str(tmp_path),
                                  "tool_input": {"file_path": str(tmp_path / "tests" / "test_y.py")}})
    assert abs_asks["permissionDecision"] == "ask"


def test_guard_tests_recursive_glob_does_not_overblock(tmp_path: Path) -> None:
    """Regressão do bug is_test_path: '**/test_*.py' não pode marcar todo .py."""
    _write_yaml(tmp_path, BASIC_YAML.replace("tests/**/*.py", "**/test_*.py"))
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    allows = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                                "tool_input": {"file_path": "src/orchestrator.py"}})
    assert allows["permissionDecision"] == "allow"

    asks = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                              "tool_input": {"file_path": "pkg/test_core.py"}})
    assert asks["permissionDecision"] == "ask"


def test_guard_test_runner_always_allows(tmp_path: Path) -> None:
    """Execução da suíte não gateia mais — só a ESCRITA do teste
    (guard_tests.py) exige aprovação. Rodar `pytest` repetidas vezes na
    mesma tarefa não deve pedir aprovação de novo."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_test_runner.py"

    for cmd in ("pytest -x", "pytest&&true", "(pytest)", "true|pytest",
                "dotnet test", "git status"):
        out = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": cmd}})
        assert out["permissionDecision"] == "allow", cmd


def test_guard_tests_reason_names_the_file_path(tmp_path: Path) -> None:
    """US-1: a razão do prompt cita o path do arquivo de teste editado."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                             "tool_input": {"file_path": "tests/test_widget.py"}})
    assert out["permissionDecision"] == "ask"
    assert "tests/test_widget.py" in out["permissionDecisionReason"], (
        out["permissionDecisionReason"]
    )


# ---------------- razão do gate cita o contrato, não só o payload (#41) ----------------

def _write_feature_list(target: Path, features: list[dict]) -> None:
    path = target / ".harness" / "feature_list.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"contract": "demo", "features": features}, ensure_ascii=False),
        encoding="utf-8",
    )


def test_guard_tests_reason_carries_the_functional_description(tmp_path: Path) -> None:
    """#41: o humano aprova a edição do teste vendo o COMPORTAMENTO coberto
    (desc da tarefa que declara o arquivo), não só o path."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "Alternar tema persiste entre recarregamentos",
         "files": ["tests/test_theme.py"], "verify_cmd": "pytest tests/test_theme.py",
         "passes": False},
        {"id": "T-02", "desc": "Rodapé some no modo compacto",
         "files": ["tests/test_footer.py"], "verify_cmd": "pytest tests/test_footer.py",
         "passes": False},
    ])
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                             "tool_input": {"file_path": "tests/test_theme.py"}})
    reason = out["permissionDecisionReason"]
    assert out["permissionDecision"] == "ask"
    assert "Alternar tema persiste entre recarregamentos" in reason, reason
    assert "T-01" in reason and "Rodapé" not in reason, reason


def test_guard_tests_flags_a_test_file_no_task_declares(tmp_path: Path) -> None:
    """Contrato ativo mas arquivo não declarado: a razão avisa que é trabalho
    fora do contrato — em vez de mostrar descrição de outra tarefa."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    _write_feature_list(tmp_path, [
        {"id": "T-01", "desc": "Alternar tema persiste", "files": ["tests/test_theme.py"],
         "verify_cmd": "pytest", "passes": False},
    ])
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                             "tool_input": {"file_path": "tests/test_outro.py"}})
    reason = out["permissionDecisionReason"]
    assert out["permissionDecision"] == "ask"
    assert "nenhuma tarefa do contrato" in reason, reason
    assert "Alternar tema persiste" not in reason, reason


def test_guards_fall_back_to_payload_reason_without_contract(tmp_path: Path) -> None:
    """Sem `feature_list.json` (init sem compile-contract) nada quebra: o
    guard de escrita continua pedindo aprovação com a razão antiga; o de
    execução continua sempre allow."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    assert not (tmp_path / ".harness" / "feature_list.json").exists()

    tests_hook = tmp_path / ".harness" / "hooks" / "guard_tests.py"
    out = _run_hook(tests_hook, {"tool_name": "Edit", "cwd": str(tmp_path),
                                 "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "ask"
    assert out["permissionDecisionReason"].startswith("Arquivo de teste protegido")

    runner_hook = tmp_path / ".harness" / "hooks" / "guard_test_runner.py"
    out = _run_hook(runner_hook, {"tool_name": "Bash", "tool_input": {"command": "pytest -x"}})
    assert out["permissionDecision"] == "allow"


def test_guards_survive_a_corrupt_feature_list(tmp_path: Path) -> None:
    """JSON ilegível é fail-safe: razão sem contrato, decisão intacta — o gate
    nunca vira allow nem estoura o hook por causa do enriquecimento."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    (tmp_path / ".harness" / "feature_list.json").write_text("{lixo", encoding="utf-8")

    out = _run_hook(tmp_path / ".harness" / "hooks" / "guard_tests.py",
                    {"tool_name": "Edit", "cwd": str(tmp_path),
                     "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "ask"
    assert out["permissionDecisionReason"].startswith("Arquivo de teste protegido")


# ---------------- kill-switch: guard_tests / guard_test_runner no-op ----------------

def test_guard_tests_hook_noop_when_sentinel_present(tmp_path: Path) -> None:
    """Com o sentinel presente, guard_tests faz no-op -> allow, mesmo para um
    arquivo de teste que normalmente exigiria aprovação (ask)."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_tests.py"

    ask = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                             "tool_input": {"file_path": "tests/test_x.py"}})
    assert ask["permissionDecision"] == "ask"

    (tmp_path / ".harness" / "harness.disabled").write_text("{}", encoding="utf-8")
    out = _run_hook(script, {"tool_name": "Edit", "cwd": str(tmp_path),
                             "tool_input": {"file_path": "tests/test_x.py"}})
    assert out["permissionDecision"] == "allow"


def test_guard_test_runner_hook_noop_when_sentinel_present(tmp_path: Path) -> None:
    """guard_test_runner é allow com ou sem o sentinel — só a razão muda."""
    _write_yaml(tmp_path, BASIC_YAML)
    compile_project(tmp_path)
    script = tmp_path / ".harness" / "hooks" / "guard_test_runner.py"

    before = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": "pytest -x"}})
    assert before["permissionDecision"] == "allow"

    (tmp_path / ".harness" / "harness.disabled").write_text("{}", encoding="utf-8")
    after = _run_hook(script, {"tool_name": "Bash", "tool_input": {"command": "pytest -x"}})
    assert after["permissionDecision"] == "allow"
    assert after["permissionDecisionReason"] != before["permissionDecisionReason"]


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
