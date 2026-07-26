"""Lançador dos hooks instalados: monta o `command` gravado em
`.claude/settings.json` e valida, sob demanda, que ele ainda é executável.

**Por que este módulo existe (Item 1 do backlog do dogfood
`Savant.Backend.APP-15167`).** Os três hooks do harness
(`boundary_guard.py`, `session_start.py`, `stop_hook.py`) eram registrados
como `python "<script>"` — interpretador NU, resolvido pelo PATH do shell
que executa o hook, no instante da tool call. Se `python` não resolver ali
(venv desativado, PATH divergente entre o shell do Claude Code e o do
usuário, ou o stub da Microsoft Store no Windows, que sai com 9009), o
processo morre ANTES de o script rodar — e a doc oficial do Claude Code
(`code.claude.com/docs/en/hooks`, seção de exit codes) é explícita: apenas
`exit 2` bloqueia; qualquer outro código não-zero é erro NÃO-bloqueante e
"execution continues".

Consequência: interpretador irresolúvel ⇒ a tool call passa sem runtime
floor, sem proteção de segredo, sem bloqueio de push, sem gate de
evidência. O guard falha ABERTO, e a única pista é uma linha de `hook
error` no transcript.

**Por que a correção mora no lançador e não no script.** O
`boundary_guard` gerado já é fail-closed internamente — qualquer exceção
durante a avaliação vira `deny` (ver o `except Exception` de `main()` em
`boundary_guard.render_boundary_guard`). Não existe como fechar de dentro
do Python o caso em que o Python nunca inicia. A única superfície de
correção é o comando registrado: bakear o caminho ABSOLUTO do
interpretador que rodou o `compile-session` (`sys.executable`), em vez de
delegar a resolução ao PATH de runtime.

**O bake sozinho NÃO fecha o fail-open — Item 1b do plano v2.** Bakear o
caminho absoluto troca a CAUSA da falha (PATH divergente) por outra (venv
recriado, que é operação rotineira justamente em repo Python com venv), mas
o modo de falha continua idêntico: processo morre com código != 2, tool
call passa. O que fecha é o sufixo `|| exit 2` no próprio `command`:

    "<interpretador>" "<script>" || exit 2

`||` e `exit` são sintaxe comum a `sh` e a `cmd.exe`, então o mesmo string
funciona nos dois shells que o Claude Code pode usar para rodar o hook — sem
gerar arquivo de lançador, que teria o problema simétrico (`.cmd` não roda
sob `sh`, `.sh` não roda sob `cmd.exe`).

A semântica é exata porque o `main()` do script gerado **nunca** sai com
código != 0: ele imprime a decisão JSON (inclusive `deny`) e retorna, e o
`except Exception` interno já converte qualquer erro de avaliação em `deny`.
Logo, todo exit não-zero do processo é, por construção, "o hook não rodou" —
e o `|| exit 2` o converte no único código que o Claude Code trata como
bloqueio. Fail-open vira fail-closed.

**Escape, por escrito:** um guard quebrado (script corrompido, interpretador
morto) passa a bloquear TODA tool call em vez de nenhuma — postura correta,
mas que precisa de saída. A saída é a mesma do kill-switch: `harness disable`
no terminal do usuário, fora do Claude Code, onde nenhum hook intercepta.

**Risco residual assumido, por escrito:** o caminho bakeado pode morrer
(venv recriado, movido ou apagado). Com o `|| exit 2` isso deixa de ser um
bypass silencioso e vira bloqueio visível; e o estado continua DETECTÁVEL a
frio por `interpreter_problem` (consumido por `harness doctor`), que nomeia
o caminho morto.
"""

from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

# Fallback quando `sys.executable` vem vazio — acontece em interpretadores
# embarcados/congelados, onde o Python não sabe o próprio caminho. Volta ao
# comportamento pré-correção (PATH em runtime), que é pior mas nunca deixa
# de instalar o hook; `interpreter_problem` sinaliza o caso ao `doctor`.
_FALLBACK_INTERPRETER = "python"

# Sufixo fail-closed do `command` — ver a seção "O bake sozinho NÃO fecha o
# fail-open" no docstring do módulo. Portátil entre `sh` e `cmd.exe`.
FAIL_CLOSED_SUFFIX = "|| exit 2"


def resolve_interpreter() -> str:
    """Caminho absoluto do interpretador a bakear no comando do hook.

    É `sys.executable` — o interpretador que está rodando o
    `compile-session`, portanto o mesmo venv onde o `harness` está
    instalado. Os scripts de hook são stdlib-only por design, então
    qualquer interpretador 3.x serve; o que importa é ser um caminho que
    não dependa do PATH de runtime."""
    return sys.executable or _FALLBACK_INTERPRETER


def hook_command(script_path: Path | str) -> str:
    """String do `command` registrado em `.claude/settings.json` para um
    script de hook: interpretador absoluto + caminho do script, ambos entre
    aspas (caminho com espaço é a regra, não a exceção, em
    `C:\\Users\\<nome> Sobrenome\\...`), mais o sufixo fail-closed
    `|| exit 2` — se o interpretador não resolver, o hook BLOQUEIA a tool call
    em vez de deixá-la passar. Ver o docstring do módulo."""
    return f'"{resolve_interpreter()}" "{script_path}" {FAIL_CLOSED_SUFFIX}'


def interpreter_from_command(command: str) -> str | None:
    """Extrai o caminho do interpretador de um `command` de hook.

    Aceita as DUAS formas — a nova (`"<interp>" "<script>"`) e a legada
    (`python "<script>"`, gravada por versões <= 0.17.7) — porque
    `harness doctor` roda sobre `settings.json` que pode ter sido compilado
    por qualquer versão. `None` se a string não tiver nenhum token
    (comando vazio).

    Usa `shlex.split(posix=False)` para não engolir as barras invertidas de
    um caminho Windows (`C:\\venv\\Scripts\\python.exe`); as aspas
    remanescentes são removidas na mão, já que no modo não-POSIX o `shlex`
    as preserva."""
    try:
        tokens = shlex.split(command or "", posix=False)
    except ValueError:
        return None
    if not tokens:
        return None
    head = tokens[0]
    if len(head) >= 2 and head[0] == head[-1] and head[0] in ('"', "'"):
        head = head[1:-1]
    return head or None


def fail_closed_problem(command: str) -> str | None:
    """`None` se o `command` do hook tem o sufixo fail-closed; senão, a
    descrição do problema.

    Detecta o hook compilado por uma versão <= 0.17.7, que registrava só
    `<interpretador> "<script>"`: nesse formato, qualquer falha de partida do
    processo (interpretador morto, script corrompido) sai com código != 2 e a
    tool call PASSA. É o mesmo fail-open do formato legado, e é invisível em
    runtime — daí o check a frio."""
    if FAIL_CLOSED_SUFFIX in (command or ""):
        return None
    return (
        "o hook não tem o sufixo fail-closed `" + FAIL_CLOSED_SUFFIX + "` — se o "
        "processo do hook não iniciar (interpretador morto, script corrompido), ele "
        "sai com código != 2 e a tool call PASSA sem o gate. Rode `harness "
        "compile-session` para regravar o comando."
    )


def interpreter_problem(command: str) -> str | None:
    """`None` se o interpretador do `command` está utilizável; senão, a
    descrição do problema (texto pt-BR, pronto para virar `issue` do
    `doctor`).

    Três estados reportados, todos com a MESMA consequência prática (hook
    não roda ⇒ tool call passa sem gate), mas causas distintas:

    - interpretador NU (sem separador de diretório, ex.: `python`): é o
      formato legado; a resolução volta a depender do PATH de runtime.
    - caminho absoluto que não existe mais em disco: venv recriado/movido.
    - caminho que existe mas não é executável pelo usuário atual.

    Deliberadamente NÃO tenta executar o interpretador para confirmar que
    funciona: `doctor` é diagnóstico barato e sem efeito colateral;
    `os.access(X_OK)` cobre o caso observável sem gastar um subprocess por
    hook."""
    interpreter = interpreter_from_command(command)
    if interpreter is None:
        return "comando de hook vazio — nenhum interpretador para executar"

    if os.sep not in interpreter and (os.altsep or os.sep) not in interpreter:
        return (
            f"o hook é registrado com o interpretador nu `{interpreter}`, resolvido pelo "
            "PATH só no momento da tool call — se não resolver ali, o hook não roda e a "
            "tool call PASSA sem o gate (a doc do Claude Code trata exit != 2 como erro "
            "não-bloqueante). Rode `harness compile-session` para bakear o caminho absoluto."
        )

    path = Path(interpreter)
    if not path.is_file():
        return (
            f"o interpretador bakeado no hook não existe mais em disco (`{interpreter}`) — "
            "venv recriado, movido ou apagado. Enquanto isso, o hook não roda e a tool "
            "call PASSA sem o gate. Rode `harness compile-session` para regravar."
        )
    if not os.access(path, os.X_OK):
        return (
            f"o interpretador bakeado no hook existe mas não é executável pelo usuário "
            f"atual (`{interpreter}`) — o hook não roda e a tool call PASSA sem o gate. "
            "Corrija as permissões ou rode `harness compile-session` de outro ambiente."
        )
    return None
