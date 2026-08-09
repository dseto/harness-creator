"""E2E da atualização transparente: um repositório de verdade, os comandos
de verdade, nenhum stub.

T-01..T-05 provam cada peça isoladamente — a decisão, a flag `--no-branch`,
o executor, os dois gatilhos. Nenhum deles prova o que o usuário
efetivamente pede: instalar a versão nova e não precisar fazer mais nada. É
o que este arquivo faz, rodando a CLI e o hook como subprocessos reais,
sobre um repositório git com contrato compilado e `branch_per_contract`
ativo.

O eixo mais importante aqui não é "atualizou": é "atualizou SEM efeito
colateral". Um auto-update que recompila mas move o desenvolvedor de branch
troca um incômodo pequeno e visível por um grande e invisível."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import harness
from harness.compiler import STATE_FILE

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PLUGIN_ROOT / "src"

#: Versão deliberadamente antiga gravada no estado compilado. Menor que
#: qualquer release real do pacote, para o veredito ser `outdated` sem
#: depender de qual versão está instalada no momento em que a suíte roda.
STALE_VERSION = "0.0.1"

APPROVED_SPEC = """---
slug: exemplo-feature
approved_by: alice
approved_at: 2026-07-15T10:00:00Z
---

# Spec: Exemplo de Feature
"""

BASIC_PLANS = """## [T-01] Criar modulo de configuracao
- files: `src/app.py`
- verify: `pytest tests/test_app.py -q`
"""

HARNESS_YAML_SRC = """version: 1
project:
  name: alvo-e2e
governance:
  branch_per_contract: true
"""


def _env() -> dict[str, str]:
    return os.environ | {"PYTHONPATH": str(SRC_DIR)}


def _run_cli(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "harness.cli", *args],
        capture_output=True, text=True, timeout=120, env=_env(), cwd=str(cwd),
    )


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=str(cwd), capture_output=True, text=True, check=True
    )
    return proc.stdout.strip()


def _current_branch(cwd: Path) -> str:
    return _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _compiled_version(root: Path) -> str | None:
    path = root / STATE_FILE
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8-sig")).get("plugin_version")


def _bootstrap_governed_repo(root: Path) -> None:
    """Repositório governado e COMMITADO, na branch `main`, cujo `.harness/`
    foi compilado por uma versão antiga — o estado exato de quem acabou de
    rodar `pip install --upgrade` e abriu um projeto antigo."""
    _write(root / "pyproject.toml", '[project]\nname = "alvo"\ndependencies = ["pytest>=8.0"]\n')
    _write(root / "src" / "app.py", "def run():\n    return 1\n")
    _write(root / "tests" / "test_app.py", "def test_ok():\n    assert True\n")
    _write(root / ".harness" / "harness.yaml", HARNESS_YAML_SRC)
    _write(root / ".harness" / "work" / "exemplo-feature" / "spec.md", APPROVED_SPEC)
    _write(root / ".harness" / "work" / "exemplo-feature" / "Plans.md", BASIC_PLANS)

    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "e2e@example.com")
    _git(root, "config", "user.name", "E2E")

    assert _run_cli(["analyze", "--dir", "."], root).returncode == 0
    assert _run_cli(["compile-contract", "--slug", "exemplo-feature", "--dir", "."], root).returncode == 0
    assert _run_cli(["compile", "--dir", "."], root).returncode == 0

    _git(root, "add", "-A")
    _git(root, "commit", "-m", "estado inicial governado")

    # Só agora o estado é envelhecido: `compile` acabou de gravar a versão
    # corrente, e é essa gravação que precisa ser desfeita para simular o
    # projeto que ficou para trás.
    _write(root / STATE_FILE, json.dumps({"plugin_version": STALE_VERSION}))
    assert _compiled_version(root) == STALE_VERSION


def test_running_any_command_brings_the_project_up_to_date_without_changing_branch(
    tmp_path: Path,
) -> None:
    """O caminho que o usuário percorre: atualizou o pacote, abriu um projeto
    antigo, rodou um comando qualquer."""
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)
    assert _current_branch(root) == "main"

    proc = _run_cli(["audit", "--dir", "."], root)

    assert _compiled_version(root) == harness.__version__
    assert _current_branch(root) == "main"
    # O comando pedido continua entregando o que sempre entregou: o auto-update
    # não pode roubar o stdout nem o exit code de quem o disparou.
    assert proc.returncode == 0, proc.stderr
    assert "score" in json.loads(proc.stdout)
    assert STALE_VERSION in proc.stderr and harness.__version__ in proc.stderr


def test_the_update_happens_once_and_then_stops_costing_anything(tmp_path: Path) -> None:
    """Segunda execução: já em dia, nada a fazer e nada a dizer. Sem isto, o
    aviso viraria ruído em toda invocação."""
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)

    _run_cli(["audit", "--dir", "."], root)
    second = _run_cli(["audit", "--dir", "."], root)

    assert _compiled_version(root) == harness.__version__
    assert "recompilados" not in second.stderr


def test_doctor_still_reports_the_real_state_instead_of_fixing_it(tmp_path: Path) -> None:
    """`doctor` é o comando que existe para mostrar a verdade das 3 camadas de
    versão. Se o auto-update rodasse antes dele, o laudo descreveria um
    estado que o próprio laudo acabou de criar."""
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)

    proc = _run_cli(["doctor", "--dir", "."], root)
    report = json.loads(proc.stdout)

    assert report["compiled_version"] == STALE_VERSION
    assert _compiled_version(root) == STALE_VERSION
    assert any(STALE_VERSION in issue for issue in report["issues"])


def test_the_kill_switch_holds_even_against_the_automatic_update(tmp_path: Path) -> None:
    """Kill-switch é a saída de emergência de um harness quebrado. Um
    auto-update que ignorasse o sentinel poderia reinstalar exatamente os
    hooks que o usuário desligou para conseguir trabalhar."""
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)
    assert _run_cli(["disable", "--dir", "."], root).returncode == 0

    _run_cli(["audit", "--dir", "."], root)

    assert _compiled_version(root) == STALE_VERSION


def test_opting_out_keeps_the_project_exactly_where_the_user_left_it(tmp_path: Path) -> None:
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)

    subprocess.run(
        [sys.executable, "-m", "harness.cli", "audit", "--dir", "."],
        capture_output=True, text=True, timeout=120, cwd=str(root),
        env=_env() | {"HARNESS_AUTO_UPDATE": "0"},
    )

    assert _compiled_version(root) == STALE_VERSION


def test_a_stale_plugin_cache_reaches_the_session_with_the_command_and_no_block(
    tmp_path: Path,
) -> None:
    """Camada 3 ponta a ponta, com `installed_plugins.json` de verdade em
    disco: hook real -> subprocesso real -> doctor real. Prova a costura, que
    e onde o risco mora — cada peca ja tem teste proprio."""
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)
    assert _run_cli(["compile-session", "--dir", ".", "--no-branch"], root).returncode == 0
    # Artefatos em dia: isola a camada 3 do aviso de recompilacao da camada 2.
    assert _run_cli(["compile", "--dir", "."], root).returncode == 0

    plugins_file = tmp_path / "installed_plugins.json"
    plugins_file.write_text(json.dumps({
        "plugins": {
            "harness-creator@harness-creator-local": [
                {"version": "0.0.1", "installPath": str(tmp_path / "cache")}
            ]
        }
    }), encoding="utf-8")

    hook = root / ".harness" / "hooks" / "session_start.py"
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"cwd": str(root)}),
        capture_output=True, text=True, timeout=180,
        env=_env() | {"HARNESS_INSTALLED_PLUGINS_FILE": str(plugins_file)},
    )

    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "ACAO NECESSARIA" in context
    assert "claude plugin update harness-creator@harness-creator-local" in context
    assert "REINICIE" in context
    assert "0.0.1" in context and harness.__version__ in context
    # O resto do contexto continua intacto: o aviso soma, nao substitui.
    assert "Estado da sessao anterior" in context


def test_a_plugin_in_step_with_the_package_adds_no_noise_to_the_session(
    tmp_path: Path,
) -> None:
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)
    assert _run_cli(["compile-session", "--dir", ".", "--no-branch"], root).returncode == 0
    assert _run_cli(["compile", "--dir", "."], root).returncode == 0

    plugins_file = tmp_path / "installed_plugins.json"
    plugins_file.write_text(json.dumps({
        "plugins": {
            "harness-creator@harness-creator-local": [
                {"version": harness.__version__, "installPath": str(tmp_path / "cache")}
            ]
        }
    }), encoding="utf-8")

    hook = root / ".harness" / "hooks" / "session_start.py"
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"cwd": str(root)}),
        capture_output=True, text=True, timeout=180,
        env=_env() | {"HARNESS_INSTALLED_PLUGINS_FILE": str(plugins_file)},
    )

    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "ACAO NECESSARIA" not in context


def test_the_session_start_hook_updates_the_project_and_says_so(tmp_path: Path) -> None:
    """O gatilho que não exige comando nenhum: abrir a sessão. É o caso que
    torna a atualização de fato transparente para quem só usa o Claude Code."""
    root = tmp_path / "alvo"
    root.mkdir()
    _bootstrap_governed_repo(root)
    assert _run_cli(["compile-session", "--dir", ".", "--no-branch"], root).returncode == 0
    _write(root / STATE_FILE, json.dumps({"plugin_version": STALE_VERSION}))

    hook = root / ".harness" / "hooks" / "session_start.py"
    proc = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"cwd": str(root)}),
        capture_output=True, text=True, timeout=180, env=_env(),
    )

    assert proc.returncode == 0, proc.stderr
    context = json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]
    assert STALE_VERSION in context
    assert harness.__version__ in context
    assert _compiled_version(root) == harness.__version__
    assert _current_branch(root) == "main"
