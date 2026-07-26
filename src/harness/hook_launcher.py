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

**Risco residual assumido, por escrito:** se o venv do projeto for
recriado, movido ou apagado, o caminho bakeado aponta para um
interpretador que não existe mais — mesmo fail-open de antes. A diferença
é que agora o estado é DETECTÁVEL: `interpreter_problem` (consumido por
`harness doctor`) reporta o caminho morto, em vez de o sintoma ficar
invisível em runtime.
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
    `C:\\Users\\<nome> Sobrenome\\...`)."""
    return f'"{resolve_interpreter()}" "{script_path}"'


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
