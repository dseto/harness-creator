"""Testes do lançador de hooks (`harness.hook_launcher`) — Item 1 do backlog
do dogfood venv-Windows.

O que está sendo protegido aqui não é ergonomia: um hook registrado com
interpretador irresolúvel NÃO RODA, e pela semântica de exit code de hook do
Claude Code (só `exit 2` bloqueia; qualquer outro não-zero é erro
não-bloqueante) a tool call PASSA sem runtime floor, sem proteção de segredo
e sem bloqueio de push. Estes testes fixam as TRÊS metades da correção:
bakear o caminho absoluto na instalação (Item 1), converter a falha de partida
em `exit 2` — o único código que bloqueia — via sufixo no próprio `command`
(Item 1b), e detectar os dois estados quebrados depois (`doctor`).
"""

from __future__ import annotations

import sys
from pathlib import Path

from harness.hook_launcher import (
    FAIL_CLOSED_SUFFIX,
    fail_closed_problem,
    hook_command,
    interpreter_from_command,
    interpreter_problem,
    resolve_interpreter,
)


# ---------------------------------------------------------------------------
# hook_command — o que é gravado em .claude/settings.json
# ---------------------------------------------------------------------------

def test_hook_command_bakes_absolute_interpreter() -> None:
    command = hook_command(Path("/repo/.harness/hooks/boundary_guard.py"))
    assert sys.executable in command
    # O regressor central: o formato antigo delegava a resolução ao PATH.
    assert not command.startswith("python ")


def test_hook_command_quotes_both_paths() -> None:
    command = hook_command(Path("/repo com espaço/.harness/hooks/stop_hook.py"))
    assert command.startswith(f'"{sys.executable}" -S -E "')
    # O caminho do script fica entre aspas mesmo com o sufixo fail-closed
    # depois dele — um path com espaço não pode vazar para o shell.
    assert '.harness' in command
    assert command.split(FAIL_CLOSED_SUFFIX)[0].rstrip().endswith('"')


def test_hook_command_uses_isolated_interpreter_flags() -> None:
    command = hook_command(Path("/repo/.harness/hooks/boundary_guard.py"))
    # -S: pula site-packages (hooks são stdlib-only por design; medido 90->68ms).
    # -E: ignora PYTHONPATH herdado — o hook nunca deve importar do repo-alvo.
    assert f'"{sys.executable}" -S -E "' in command
    # interpreter_from_command continua extraindo só o interpretador, sem as flags.
    assert interpreter_from_command(command) == sys.executable


def test_resolve_interpreter_is_current_executable() -> None:
    assert resolve_interpreter() == sys.executable


# ---------------------------------------------------------------------------
# interpreter_from_command — precisa ler as DUAS formas (nova e legada)
# ---------------------------------------------------------------------------

def test_interpreter_from_new_format() -> None:
    command = hook_command(Path("/repo/.harness/hooks/session_start.py"))
    assert interpreter_from_command(command) == sys.executable


def test_interpreter_from_legacy_format() -> None:
    # Formato gravado por versões <= 0.17.7; `doctor` roda sobre settings.json
    # que pode ter sido compilado por qualquer versão.
    assert interpreter_from_command('python ".harness/hooks/boundary_guard.py"') == "python"


def test_interpreter_preserves_windows_backslashes() -> None:
    # shlex em modo POSIX comeria as barras invertidas do caminho e
    # transformaria C:\venv\Scripts\python.exe em C:venvScriptspython.exe,
    # fazendo o `doctor` reportar "não existe" para um interpretador válido.
    command = r'"C:\venv\Scripts\python.exe" "C:\repo\.harness\hooks\stop_hook.py"'
    assert interpreter_from_command(command) == r"C:\venv\Scripts\python.exe"


def test_interpreter_from_empty_command_is_none() -> None:
    assert interpreter_from_command("") is None
    assert interpreter_from_command("   ") is None


# ---------------------------------------------------------------------------
# interpreter_problem — os 3 estados quebrados + o caminho feliz
# ---------------------------------------------------------------------------

def test_problem_none_for_current_interpreter() -> None:
    assert interpreter_problem(hook_command(Path("/repo/hook.py"))) is None


def test_problem_flags_bare_interpreter() -> None:
    problem = interpreter_problem('python ".harness/hooks/boundary_guard.py"')
    assert problem is not None
    assert "PATH" in problem
    assert "compile-session" in problem


def test_problem_flags_missing_interpreter(tmp_path: Path) -> None:
    ghost = tmp_path / "venv" / "Scripts" / "python.exe"
    problem = interpreter_problem(f'"{ghost}" "{tmp_path}/hook.py"')
    assert problem is not None
    assert "não existe mais em disco" in problem


def test_problem_flags_empty_command() -> None:
    problem = interpreter_problem("")
    assert problem is not None
    assert "vazio" in problem


def test_problem_mentions_that_the_call_passes_without_gate() -> None:
    # A consequência precisa estar na mensagem: quem lê o `doctor` tem que
    # entender que não é um aviso cosmético — o gate não está rodando.
    for command in ('python "hook.py"', '"/nao/existe/python" "hook.py"'):
        problem = interpreter_problem(command)
        assert problem is not None
        assert "PASSA sem o gate" in problem


# ---------------------------------------------------------------------------
# Item 1b — sufixo fail-closed. O bake sozinho não fecha o fail-open: ele troca
# a CAUSA da falha (PATH divergente -> venv recriado) sem mudar o modo (exit
# != 2 => tool call passa). O que fecha é o `|| exit 2`.
# ---------------------------------------------------------------------------

def test_hook_command_ends_with_fail_closed_suffix() -> None:
    command = hook_command(Path("/repo/.harness/hooks/boundary_guard.py"))
    assert command.endswith(FAIL_CLOSED_SUFFIX)


def test_fail_closed_problem_none_when_suffix_present() -> None:
    assert fail_closed_problem(hook_command(Path("/repo/hook.py"))) is None


def test_fail_closed_problem_flags_legacy_format() -> None:
    # Formato gravado por versões <= 0.17.7 (bake sem sufixo) e o formato
    # ainda mais antigo (interpretador nu). Ambos falham ABERTO.
    for command in ('"/usr/bin/python3" "hook.py"', 'python "hook.py"'):
        problem = fail_closed_problem(command)
        assert problem is not None
        assert "PASSA sem o gate" in problem


def test_generated_guard_always_exits_zero_so_suffix_semantics_hold(tmp_path: Path) -> None:
    """A premissa que torna `|| exit 2` correto: o script gerado NUNCA sai com
    código != 0 por conta própria — ele imprime a decisão (inclusive `deny`) e
    retorna. Logo todo exit não-zero é, por construção, "o hook não rodou".

    Se algum dia o guard passar a sair com código != 0 para sinalizar `deny`,
    este teste quebra — e deve quebrar: o sufixo viraria redundante no melhor
    caso e mascararia a decisão no pior."""
    import json
    import subprocess

    from harness.boundary_guard import render_boundary_guard

    script = tmp_path / "guard.py"
    script.write_text(render_boundary_guard(), encoding="utf-8")

    for payload in (
        {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
        {"tool_name": "Bash", "tool_input": {"command": "ls"}},
        {"tool_name": "Write", "tool_input": {"file_path": ".env"}},
        {"tool_name": "Bash"},  # payload degenerado: sem tool_input
    ):
        payload["cwd"] = str(tmp_path)
        proc = subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps(payload), capture_output=True, text=True, timeout=30,
        )
        assert proc.returncode == 0, (payload, proc.returncode, proc.stderr)
        assert json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]


def test_fail_closed_suffix_really_exits_2_in_the_platform_shell(tmp_path: Path) -> None:
    """Prova de execução do Item 1b, no shell REAL da plataforma.

    `subprocess(shell=True)` usa `/bin/sh -c` no POSIX e `cmd.exe /c` no
    Windows — os dois shells que podem executar o `command` do hook. O `||` e o
    `exit` têm a mesma semântica nos dois, e é isso que este teste fixa: com o
    interpretador morto, o processo sai com 2 (ÚNICO código que o Claude Code
    trata como bloqueio) em vez de 127/9009 (erro não-bloqueante => tool call
    passa). Sem esta garantia, o Item 1b é só uma string bonita no settings.

    Verificado também à mão em `cmd.exe /d /s /c` (a forma que o Node usa com
    `shell: true`): interpretador morto -> exit 2, vivo -> exit do processo.
    """
    import subprocess

    dead = tmp_path / "nao-existe" / "python.exe"
    command = f'"{dead}" "{tmp_path / "hook.py"}" {FAIL_CLOSED_SUFFIX}'
    proc = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=30)
    assert proc.returncode == 2, (proc.returncode, proc.stdout, proc.stderr)


def test_fail_closed_suffix_does_not_mask_a_successful_hook(tmp_path: Path) -> None:
    """O simétrico: com o interpretador vivo, o sufixo é transparente — o exit
    0 do guard (que já carrega `deny` no JSON quando é o caso) passa intacto.
    Se o sufixo transformasse todo run em 2, o guard bloquearia TUDO."""
    import json
    import subprocess

    from harness.boundary_guard import render_boundary_guard

    script = tmp_path / "guard.py"
    script.write_text(render_boundary_guard(), encoding="utf-8")
    command = hook_command(script)

    payload = json.dumps({
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "cwd": str(tmp_path),
    })
    proc = subprocess.run(
        command, shell=True, input=payload, capture_output=True, text=True, timeout=30
    )
    assert proc.returncode == 0, (proc.returncode, proc.stderr)
    decision = json.loads(proc.stdout)["hookSpecificOutput"]["permissionDecision"]
    assert decision == "deny", proc.stdout


# ---------------------------------------------------------------------------
# B2 — o sufixo precisa estar no que os INSTALADORES gravam, não só no que
# `hook_command()` devolve.
#
# Achado do comitê MAR sobre a onda 1: nenhum teste de instalação assertava o
# sufixo. Os três testes de instalação existentes checavam apenas
# `sys.executable in command` e `not startswith("python ")`. Um instalador que
# parasse de chamar `hook_command()` e montasse a string à mão reintroduziria
# o fail-open com a suíte inteira verde — a mesma classe de furo de composição
# do Item 0: a peça correta existe, mas ninguém prova que ela é a usada.
# ---------------------------------------------------------------------------

_INSTALLERS = [
    ("harness.boundary_guard", "install_boundary_guard", "PreToolUse"),
    ("harness.session_start", "install_session_start", "SessionStart"),
    ("harness.stop_hook", "install_stop_hook", "Stop"),
]


def _installed_command(tmp_path: Path, module: str, func: str, event: str) -> str:
    import importlib
    import json

    getattr(importlib.import_module(module), func)(tmp_path)
    settings = json.loads(
        (tmp_path / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    return settings["hooks"][event][0]["hooks"][0]["command"]


def test_every_installer_writes_the_fail_closed_suffix(tmp_path: Path) -> None:
    for i, (module, func, event) in enumerate(_INSTALLERS):
        target = tmp_path / f"repo{i}"
        target.mkdir()
        command = _installed_command(target, module, func, event)
        assert command.endswith(FAIL_CLOSED_SUFFIX), (module, command)


def test_installed_command_blocks_when_the_hook_script_is_broken(tmp_path: Path) -> None:
    """O teste de DESFECHO, não de string: pega o comando que o instalador
    gravou de fato e roda no shell da plataforma com o script corrompido.

    A quebra é erro de SINTAXE, deliberadamente, e não script ausente:
    `python script_que_nao_existe.py` já sai 2 por conta do próprio Python, o
    que faria o teste passar mesmo SEM o sufixo — não discriminaria nada.
    Erro de sintaxe sai 1, que é o código que o Claude Code trata como erro
    NÃO-bloqueante ("execution continues"). Sem o sufixo este teste retorna 1
    e falha; com ele, 2."""
    import subprocess

    for i, (module, func, event) in enumerate(_INSTALLERS):
        target = tmp_path / f"repo{i}"
        target.mkdir()
        command = _installed_command(target, module, func, event)

        script = next((target / ".harness" / "hooks").glob("*.py"))
        script.write_text("def quebrado(\n", encoding="utf-8")

        proc = subprocess.run(
            command, shell=True, input="{}", capture_output=True, text=True, timeout=30
        )
        assert proc.returncode == 2, (module, proc.returncode, proc.stderr[:400])


# ---------------------------------------------------------------------------
# F8 — os hooks de `harness compile` também.
#
# Achado do dogfood venv-Windows (2026-07-27): o Item 1/1b foi
# aplicado aos três instaladores do `compile-session`, mas `compiler.py`
# continuou montando `python "<script>"` à mão para `guard_tests.py` e
# `guard_test_runner.py`. É o caminho por onde TODA instalação passa primeiro —
# `harness compile` roda antes de existir contrato —, e o alvo real estava
# nesse estado, com os dois guards de TDD lançados por interpretador nu.
#
# O B2 acima previu exatamente esta forma de regressão ("um instalador que
# parasse de chamar `hook_command()` e montasse a string à mão"); o que faltava
# era o teste cobrir os DOIS instaladores que existem, não só os três de sessão.
# ---------------------------------------------------------------------------

_HARNESS_YAML = (
    "governance:\n"
    "  approval_policy: auto\n"
    "verification:\n"
    "  enforce_tdd: true\n"
    '  test_command: "pytest -q"\n'
    '  test_glob: "tests/**/*.py"\n'
)


def _compile_commands(target: Path) -> list[str]:
    import json

    from harness.compiler import compile_project

    (target / ".harness").mkdir(parents=True, exist_ok=True)
    (target / ".harness" / "harness.yaml").write_text(_HARNESS_YAML, encoding="utf-8")
    compile_project(target)
    settings = json.loads(
        (target / ".claude" / "settings.local.json").read_text(encoding="utf-8")
    )
    return [
        hook["command"]
        for entry in settings["hooks"]["PreToolUse"]
        for hook in entry["hooks"]
    ]


def test_compile_hooks_carry_the_absolute_interpreter_and_fail_closed_suffix(
    tmp_path: Path,
) -> None:
    commands = _compile_commands(tmp_path)

    # Só o guard_test_runner: o `guard_tests.py` é gerado em disco mas não
    # registrado desde a issue #61 (ver `compiler.render`). O invariante sob
    # teste aqui é o do launcher — interpretador absoluto e sufixo fail-closed
    # —, não a quantidade de hooks; o número acompanha quem de fato é
    # registrado.
    assert len(commands) == 1, commands
    for command in commands:
        assert command.endswith(FAIL_CLOSED_SUFFIX), command
        assert not command.startswith("python "), command
        assert interpreter_problem(command) is None, command


def test_compile_hook_blocks_when_the_script_is_broken(tmp_path: Path) -> None:
    """Desfecho, não string — mesma discriminação do B2: a quebra é erro de
    SINTAXE (sai 1, que o Claude Code trata como não-bloqueante), não script
    ausente (que já sairia 2 pelo próprio Python e não provaria nada)."""
    import subprocess

    commands = _compile_commands(tmp_path)
    for script in (tmp_path / ".harness" / "hooks").glob("*.py"):
        script.write_text("def quebrado(\n", encoding="utf-8")

    for command in commands:
        proc = subprocess.run(
            command, shell=True, input="{}", capture_output=True, text=True, timeout=30
        )
        assert proc.returncode == 2, (command, proc.returncode, proc.stderr[:400])


def test_doctor_now_sees_the_compile_hooks(tmp_path: Path) -> None:
    """O laudo do alvo real devolvia `"hooks": []` com os hooks de `compile`
    instalados e vulneráveis — `MANAGED_HOOK_FILENAMES` listava só os de
    sessão, então o `doctor` dava verde falso sobre exatamente o estado que o
    check existe para pegar.

    Eram dois hooks quando este teste foi escrito; hoje é um, porque o
    `guard_tests.py` deixou de ser registrado (issue #61). O que o teste
    protege é o `doctor` VER o que está registrado, não o número."""
    from harness.doctor import run_doctor

    _compile_commands(tmp_path)
    report = run_doctor(tmp_path)

    assert len(report.hooks) == 1, report.hooks
    commands = " ".join(h["command"] for h in report.hooks)
    assert "guard_test_runner.py" in commands
    assert all(h["ok"] is True for h in report.hooks), report.hooks
