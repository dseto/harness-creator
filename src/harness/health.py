"""Health check de abertura — o §7.2 do design de loop engineering.

O protocolo de retomada tem cinco passos e quatro já têm mecanismo. O que
faltava é o segundo: **as ferramentas respondem?** Sem ele, ferramenta ausente
entra no loop disfarçada de teste vermelho — e o design dá respostas OPOSTAS
para os dois casos. Falha estrutural (§8.2) manda corrigir e re-verificar;
falha de infraestrutura (§8.3) manda parar e escalar, porque "loop não conserta
a própria jaula". Sem alguém para separar os dois, o loop aplica a resposta
errada e queima o budget consertando código que está certo.

**Por que perguntar em vez de executar.** O passo 2 do lifecycle já mandava
rodar `.harness/init.sh`/`init.ps1`, que instala dependências e roda a suíte
inteira. Ninguém roda — porque custa uma suíte por abertura. Um check caro é um
check opcional na prática, e um check opcional não cobre o modo de falha que
ele existe para pegar: o §8.3 é a família que **não gera feedback, gera
silêncio**. Então este módulo não executa nada do contrato. Ele resolve o
executável de cada `verify_cmd` no PATH e, quando a forma é `<python> -m
<módulo>`, confirma que o módulo importa. É o que separa "instalado" de
"responde" pelo preço de um `import`.

Duas fronteiras estreitas guardam essa única execução, porque ela roda sozinha
na abertura da sessão, sem humano olhando: o executável só é procurado dentro
da árvore quando o token É um caminho (ver `_resolve_executable`), e só vira
`import` o que é nome de módulo (ver `_MODULE_NAME_RE`). Sem as duas, o
conteúdo do repositório decide o que este módulo lança.

O que este módulo NUNCA faz: instalar, recompilar, reativar. Ver §8.3 — não há
healing automático de infraestrutura.
"""

from __future__ import annotations

import json
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

FEATURE_LIST_FILE = ".harness/feature_list.json"

#: Classificações de problema de ferramenta. Duas, porque a correção é
#: diferente: executável ausente é PATH/instalação do sistema; módulo ausente é
#: dependência do projeto, e o `init.sh`/`init.ps1` do próprio harness resolve.
HEALTH_KIND_TOOL = "tool_missing"
HEALTH_KIND_MODULE = "module_unimportable"

#: As outras duas famílias que o §8.3 nomeia junto com "tool indisponível".
#: `governance_stale` é o hook morto e o settings ausente — o `doctor` já sabia
#: achar, e só falava quando perguntado. `protection_disabled` é o kill-switch:
#: o harness rodando em no-op, que neste repositório passou quatro dias ligado
#: sem ninguém ver (issue #52).
HEALTH_KIND_GOVERNANCE = "governance_stale"
HEALTH_KIND_PROTECTION = "protection_disabled"

#: A única informação do laudo que muda a REAÇÃO de quem lê. §8.2 (estrutural)
#: manda corrigir e re-verificar; §8.3 (infra) manda parar e escalar. Sem a
#: etiqueta, ferramenta ausente chega ao loop com cara de teste vermelho.
HEALTH_CLASSIFICATION = "infra"

#: `-m <módulo>` só é importação quando quem recebe a flag é um interpretador
#: Python. `npm -m test` casa o formato e não importa nada — probar ali daria
#: falso positivo em todo projeto Node. Cobre `python`, `python3`,
#: `python3.12`, o launcher `py` do Windows e os `.exe` correspondentes.
_PYTHON_EXECUTABLE_RE = re.compile(r"^(python|py)(\d+(\.\d+)?)?(\.exe)?$", re.IGNORECASE)

#: Nome de módulo pontilhado, e nada além disso. O token do `-m` entra
#: interpolado num `-c "import ..."`, e o `shlex` só quebra em ESPAÇO: um
#: payload sem espaços — `pathlib;pathlib.Path(...).write_text(...)` —
#: atravessava inteiro e virava código executado. E isto roda sozinho na
#: abertura da sessão, pelo hook `SessionStart`, antes de qualquer humano olhar
#: a branch: o pior lugar possível para confiar no conteúdo de um arquivo.
#: Token que não casa não vira problema no laudo, só deixa de ser perguntado —
#: `-m` com argumento estranho é defeito do contrato, e alarmar sobre ele aqui
#: seria o laudo opinando sobre coisa que não é da alçada dele.
_MODULE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$")

#: Tempo máximo do `import`. Generoso de propósito: um pacote pesado pode levar
#: segundos para importar na primeira vez, e um timeout apertado transformaria
#: ambiente lento em ambiente quebrado.
_PROBE_TIMEOUT = 60


@dataclass(frozen=True)
class ToolCheck:
    """Veredito sobre UMA ferramenta exigida pelo contrato."""

    verify_cmd: str
    executable: str
    module: str | None
    ok: bool
    kind: str | None
    problem: str | None


def probe_targets(verify_cmd: str) -> tuple[str, str | None]:
    """`verify_cmd` -> `(executável, módulo a importar ou None)`.

    `posix=False` no split porque este harness roda em Windows: com
    `posix=True` o `shlex` come as contrabarras de um caminho como
    `C:\\Python\\python.exe` e o executável chega destruído. O preço é que as
    aspas ficam no token, e é por isso que elas são removidas logo depois.
    """
    try:
        tokens = [t.strip('"').strip("'") for t in shlex.split(verify_cmd, posix=False)]
    except ValueError:
        # Aspas desbalanceadas. Não é papel deste módulo julgar a sintaxe do
        # comando — quem faz isso é o shell, na hora de rodar.
        return ("", None)
    if not tokens:
        return ("", None)

    executable = tokens[0]
    module: str | None = None
    if _PYTHON_EXECUTABLE_RE.match(Path(executable).name) and "-m" in tokens[1:]:
        index = tokens.index("-m", 1)
        if index + 1 < len(tokens) and _MODULE_NAME_RE.match(tokens[index + 1]):
            module = tokens[index + 1]
    return (executable, module)


def _load_contract(target_dir: Path | str) -> dict[str, Any]:
    path = Path(target_dir) / FEATURE_LIST_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def contract_verify_cmds(target_dir: Path | str) -> list[tuple[str, str | None]]:
    """Os pares `(verify_cmd, cwd)` DISTINTOS do contrato ativo, na ordem em que
    aparecem.

    Distintos porque um contrato de doze fatias costuma ter dois ou três
    comandos: perguntar doze vezes a mesma coisa custaria doze subprocessos na
    abertura, e o custo é justamente o que faz um check ser abandonado.

    O par, e não o comando sozinho, porque é o par que identifica uma prova —
    mesma regra de `regression.reproof_targets`. O mesmo comando em outro
    diretório procura o executável em outro lugar.
    """
    seen: list[tuple[str, str | None]] = []
    for feature in _load_contract(target_dir).get("features") or []:
        if not isinstance(feature, dict):
            continue
        cmd = (feature.get("verify_cmd") or "").strip()
        if not cmd:
            continue
        entry = (cmd, feature.get("cwd"))
        if entry not in seen:
            seen.append(entry)
    return seen


def _resolve_executable(
    executable: str,
    *,
    target_dir: Path | str,
    cwd: str | None,
    which: Callable[[str], str | None],
) -> str | None:
    """Onde o executável está, procurando de ONDE a prova vai rodar **apenas
    quando o token é um caminho**.

    O `cwd` da tarefa existe no contrato exatamente para o binário que só
    resolve de dentro do workspace (ver `harness.verify`), e `shutil.which`
    sozinho não enxerga caminho relativo ao alvo quando o processo do harness
    roda de outro lugar. Sem esta busca, `tools/run.bat` presente no
    repositório voltava como `tool_missing` — e falso positivo é o jeito mais
    rápido de treinar quem lê a ignorar o laudo inteiro.

    A fronteira é a MESMA do shell: token com separador é caminho, token nu é
    PATH. Sem ela, o conteúdo da working tree passa a decidir o veredito, das
    duas piores formas possíveis — um arquivo qualquer chamado `pytest` faria o
    laudo dizer VERDE para uma ferramenta que não existe em lugar nenhum
    (silêncio verde, o modo de falha do §8.3 que este módulo existe para
    pegar), e um arquivo chamado `python` escolheria qual binário o hook da
    abertura lança sozinho.
    """
    if not executable:
        return None
    if "/" in executable or "\\" in executable:
        base = Path(target_dir)
        if cwd:
            base = base / cwd
        candidate = base / executable
        if candidate.is_file():
            return str(candidate)
    return which(executable)


def _check_one(
    verify_cmd: str,
    cwd: str | None,
    *,
    target_dir: Path | str,
    run: Callable[..., Any],
    which: Callable[[str], str | None],
) -> ToolCheck:
    executable, module = probe_targets(verify_cmd)

    resolved = _resolve_executable(executable, target_dir=target_dir, cwd=cwd, which=which)
    if resolved is None:
        return ToolCheck(
            verify_cmd=verify_cmd,
            executable=executable,
            module=module,
            ok=False,
            kind=HEALTH_KIND_TOOL,
            problem=(
                f"`{executable or verify_cmd}` não resolve no PATH, e é o que "
                f"`{verify_cmd}` precisa para rodar."
            ),
        )

    if module is None:
        return ToolCheck(verify_cmd, executable, module, True, None, None)

    try:
        proc = run(
            [resolved, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolCheck(
            verify_cmd=verify_cmd,
            executable=executable,
            module=module,
            ok=False,
            kind=HEALTH_KIND_MODULE,
            problem=(
                f"não foi possível perguntar se `{module}` importa em "
                f"`{executable}` ({exc}), e é o que `{verify_cmd}` precisa."
            ),
        )

    if proc.returncode != 0:
        return ToolCheck(
            verify_cmd=verify_cmd,
            executable=executable,
            module=module,
            ok=False,
            kind=HEALTH_KIND_MODULE,
            problem=(
                f"`{module}` não importa em `{executable}`, e é o que "
                f"`{verify_cmd}` precisa. Instale as dependências do projeto "
                f"(`.harness/init.ps1` no Windows, `.harness/init.sh` no resto)."
            ),
        )

    return ToolCheck(verify_cmd, executable, module, True, None, None)


def check_tools(
    target_dir: Path | str,
    *,
    run: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> list[ToolCheck]:
    """Um `ToolCheck` por `verify_cmd` distinto do contrato ativo.

    Sem contrato compilado a lista é vazia, e isso é silêncio e não problema: um
    projeto entre demandas não exige ferramenta nenhuma, e abrir a sessão com
    alarme onde não há exigência é a forma mais rápida de treinar quem lê a
    ignorar o laudo.
    """
    runner = run or subprocess.run
    resolver = which or shutil.which
    return [
        _check_one(cmd, cwd, target_dir=target_dir, run=runner, which=resolver)
        for cmd, cwd in contract_verify_cmds(target_dir)
    ]


def _protection_problem(target_dir: Path | str) -> str | None:
    """Kill-switch ligado — o harness em no-op.

    Aparecia só no `reconcile`, misturado às divergências entre estado
    declarado e estado real. É outra coisa: ali o registro discorda do mundo;
    aqui a proteção simplesmente não está lá. Um guard desligado em silêncio
    transforma semanas de sessões em evidência contaminada, que é literalmente
    o que o §8.3 descreve — e o que aconteceu neste repositório entre
    2026-07-24 e 07-28.
    """
    from harness.killswitch import status

    state = status(target_dir)
    if not state.get("disabled"):
        return None
    note = (state.get("note") or "").strip()
    since = state.get("disabled_at") or "data desconhecida"
    suffix = f' Nota de quem desativou: "{note}".' if note else ""
    return (
        f"o harness está DESATIVADO neste projeto desde {since} — os hooks estão "
        f"em no-op e nada do floor de segurança está sendo aplicado.{suffix} "
        "Reativar é decisão de quem desativou (`harness enable`), não deste check."
    )


def run_health(
    target_dir: Path | str,
    *,
    run: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
) -> dict[str, Any]:
    """Laudo de abertura das três famílias do §8.3, num relatório só.

    O design nomeia as três juntas — "hook morto, tool indisponível, guard em
    no-op" — porque a consequência é uma só: o agente continua trabalhando sem
    as garantias que acha que tem. Três diagnósticos em três comandos é o mesmo
    que nenhum, porque quem não desconfia não pergunta nem uma vez.

    Ordem dos problemas por severidade, e não por família: proteção desligada
    primeiro (nada está sendo aplicado), depois governança (o gate existe mas
    não roda), depois ferramenta (o trabalho não começa). Quem lê para de ler
    no primeiro item; o primeiro item precisa ser o que mais muda a decisão.
    """
    from harness.doctor import repo_issues

    problems: list[dict[str, str]] = []

    protection = _protection_problem(target_dir)
    if protection:
        problems.append({"kind": HEALTH_KIND_PROTECTION, "problem": protection})

    for issue in repo_issues(Path(target_dir)):
        problems.append({"kind": HEALTH_KIND_GOVERNANCE, "problem": issue})

    tools = check_tools(target_dir, run=run, which=which)
    for check in tools:
        if check.problem:
            problems.append({"kind": check.kind or HEALTH_KIND_TOOL, "problem": check.problem})

    return {
        "ok": not problems,
        # Constante mesmo no verde: a etiqueta descreve a NATUREZA do que este
        # laudo julga, não o resultado. Quem lê o JSON precisa saber que um
        # `ok: false` daqui nunca é falha estrutural, sem ter que inferir.
        "classification": HEALTH_CLASSIFICATION,
        "tools": [
            {
                "verify_cmd": check.verify_cmd,
                "executable": check.executable,
                "module": check.module,
                "ok": check.ok,
                "kind": check.kind,
                "problem": check.problem,
            }
            for check in tools
        ],
        "problems": problems,
    }


def render_session_section(report: dict[str, Any]) -> str | None:
    """Seção markdown do `SessionStart`, ou `None` quando tudo responde.

    Silêncio no verde pela mesma razão de `reconcile.render_session_section`: o
    contexto de abertura entra em TODA sessão, e uma seção dizendo "está tudo
    certo" gasta o orçamento de atenção de que o aviso de verdade vai precisar.

    O que a seção carrega é o subconjunto do formato de escalada do §8 que
    existe ANTES de qualquer tentativa: a classificação e o próximo passo. Os
    outros campos do formato — o que foi tentado, o último erro cru — são sobre
    tentativas que ainda não aconteceram; preenchê-los aqui produziria
    exatamente os "templates com campos que ninguém preenche" que o §11 lista
    como sinal de over-engineering.

    A moldura (títulos, classificação, próximo passo) é ASCII, como a do
    `reconcile`: ela atravessa o script gerado do `SessionStart` e é lida em
    consoles Windows. As mensagens interpoladas NÃO são — elas vêm de
    `repo_issues` e dos checks, com acento. O round-trip pelo JSON preserva os
    acentos; o que a moldura ASCII garante é que o aviso continue legível mesmo
    se alguma etapa do caminho degradar a codificação do conteúdo.
    """
    problems = report.get("problems") or []
    if not problems:
        return None

    lines = [
        "## ACAO NECESSARIA: o ambiente nao esta em condicoes de trabalhar",
        "",
        "Classificacao: INFRAESTRUTURA (secao 8.3 do design). Isto NAO e teste "
        "vermelho e nao melhora tentando de novo — os dois tipos de falha tem "
        "respostas opostas, e aplicar a de falha estrutural aqui queima o budget "
        "consertando codigo que esta certo.",
        "",
    ]
    for problem in problems:
        lines.append(f"- **{problem.get('kind')}** — {problem.get('problem')}")
    lines += [
        "",
        "Proximo passo: resolva o que esta acima (cada item diz como) e rode "
        "`harness health --dir .` de novo. Nao escolha fatia antes disso. "
        "Nao tente consertar o proprio harness por conta propria: se o problema "
        "for da governanca ou da protecao, pare e escale ao humano — a secao 8.3 "
        "e explicita em que o loop nao conserta a propria jaula.",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# entrypoint `python -m harness.health`
# ---------------------------------------------------------------------------
#
# Mesma razão do entrypoint de `harness.reconcile`: quem consome isto na
# abertura é o hook `SessionStart`, que roda com `-S` e não importa `harness`.
# Ele delega a um interpretador novo e lê o JSON de volta — se montasse o texto
# do aviso, a formatação ficaria fora do alcance da suíte.

def _main(argv: list[str] | None = None) -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        prog="python -m harness.health",
        description="Health check de abertura (§7.2): as ferramentas respondem?",
    )
    parser.add_argument("--dir", default=".", help="Raiz do projeto-alvo")
    args = parser.parse_args(argv)

    report = run_health(Path(args.dir))
    print(json.dumps(
        {**report, "section": render_session_section(report)}, ensure_ascii=False,
    ))
    return 2 if report["problems"] else 0


if __name__ == "__main__":
    import sys

    sys.exit(_main())
