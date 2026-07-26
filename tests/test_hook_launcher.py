"""Testes do lançador de hooks (`harness.hook_launcher`) — Item 1 do backlog
do dogfood `Savant.Backend.APP-15167`.

O que está sendo protegido aqui não é ergonomia: um hook registrado com
interpretador irresolúvel NÃO RODA, e pela semântica de exit code de hook do
Claude Code (só `exit 2` bloqueia; qualquer outro não-zero é erro
não-bloqueante) a tool call PASSA sem runtime floor, sem proteção de segredo
e sem bloqueio de push. Estes testes fixam as duas metades da correção:
bakear o caminho absoluto na instalação, e detectar o estado quebrado depois.
"""

from __future__ import annotations

import sys
from pathlib import Path

from harness.hook_launcher import (
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
    assert command.startswith(f'"{sys.executable}" "')
    assert command.endswith('"')


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
