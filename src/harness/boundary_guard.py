"""Dispatcher único de fronteira: `boundary_guard.py` — Fase 2 do ROADMAP.

Substitui o padrão de N guards por ação (um hook por matcher) por UM único
hook `PreToolUse` que cobre `Edit`, `Write`, `MultiEdit`, `NotebookEdit`,
`PowerShell` e `Bash` ao mesmo tempo, decidindo `allow`/`deny` a partir da
superfície do contrato ATIVO (`.harness/feature_list.json`, compilado por
`contract.py`). Resolve a latência de N subprocessos por tool call que o
design anterior (um guard por ação, em `compiler.py`) pagava.

**Matcher do hook e roteamento explícito (correção do backlog do issue #1,
achado #1 — "bypass de tool de escrita")** — o matcher registrado é `"*"`,
não `"Edit|Write|Bash"`: CONFIRMADO via consulta à documentação oficial do
Claude Code (`https://code.claude.com/docs/en/hooks`, seção de matcher
patterns) que, para `PreToolUse`, o matcher filtra pelo NOME da tool e
`"*"`/`""`/omitido casam TODA tool call — não assumido a partir do padrão de
`session_start.py:212` (aquele é matcher de `SessionStart`, que casa a
ORIGEM da sessão — startup/resume/clear/compact —, namespace DIFERENTE de
`PreToolUse`, que casa nome de tool; a semântica de `"*"` coincidiu nos dois
casos, mas por MOTIVOS diferentes, confirmados independentemente). Com
matcher `"Edit|Write|Bash"`, qualquer tool de escrita fora desse conjunto
(PowerShell, NotebookEdit, MCP filesystem tools) nunca invocava o hook — o
Claude Code aplicava o allow implícito ANTES de o `else: allow` de `main()`
sequer rodar. Alargar o matcher sozinho não bastaria (só trocaria "nunca
avaliado" por "avaliado só pelo fallback genérico"); por isso `main()` agora
roteia EXPLICITAMENTE: `Edit`/`Write` → `_evaluate_file`; `MultiEdit`
(múltiplas edições `old_string`/`new_string` sobre um ÚNICO arquivo,
`tool_input["file_path"]` — correção adicional pós-implementação, validação
adversarial Opus: sem esta rota, `MultiEdit` caia no ramo de tool
desconhecida e era `deny` SEMPRE, mesmo dentro da superfície aprovada, já
que o nome contém "edit"; fail-safe mas quebrava fluxo legítimo) →
`_evaluate_file` também, sem o caso especial de feature-lock (o formato de
`tool_input` de `MultiEdit` — array `edits[]` — não bate com o que
`_evaluate_feature_list_edit` espera; uma `MultiEdit` sobre
`feature_list.json` cai na superfície genérica, hoje já `deny` por padrão —
mesmo comportamento seguro documentado para `Edit`/`Write` sem transição);
`NotebookEdit` → `_evaluate_file` sobre `tool_input["notebook_path"]` (com
fallback para `file_path` — a doc oficial não expôs o schema exato de
`tool_input` do `NotebookEdit`, então a robustez extra do fallback cobre o
caso de o nome do campo divergir do assumido, sem enfraquecer o floor:
qualquer path extraído ainda passa pela mesma avaliação de superfície);
`PowerShell` → `_evaluate_powershell` (Item 2, ver mais abaixo); `Bash` →
`_evaluate_bash`. Uma allowlist pequena e FIXA de tools read-only/utilitárias
conhecidas
(`Read`, `Glob`, `Grep`, `Task`, `WebFetch`, `TodoWrite`) passa sem análise —
`Task` é usado pelo próprio harness (subagentes) e NÃO pode cair em deny.
Para qualquer tool NÃO enumerada acima (MCP arbitrária, tool nova do Claude
Code, etc.): política MÍNIMA para o deploy single-user interno deste
plugin — NÃO é um framework de governança MCP abrangente, NÃO é
default-deny-tudo (que quebraria `Task`/`WebFetch` e qualquer tool
utilitária futura não antecipada aqui). Nome com cara de escrita
(`mcp__*__write*`, ou contendo `create`/`edit`, case-insensitive) → `deny`;
resto → `allow` LOGADO (a razão da decisão cita explicitamente que é
allow-logado por política mínima). **Risco residual assumido, por
escrito:** uma tool MCP de escrita cujo nome não contenha
`write`/`create`/`edit` (ex.: `mcp__foo__persist`, `mcp__foo__save`) passa
sem análise — aceitável no contexto de deploy single-user interno descrito
no backlog; se o conjunto de MCP servers conectados mudar para incluir
ferramentas de terceiros não confiáveis, esta política mínima deve ser
revisada (idealmente allowlist explícita por nome, não por padrão de
substring).

Quatro garantias, nesta ordem, sempre:

1. **Runtime floor** — roda incondicionalmente ANTES de qualquer outra
   verificação, inclusive antes de checar se existe contrato ativo:
   `git push`, publicação/rede não planejada (`curl`, `wget`, `npm publish`,
   `pip upload`, `twine upload`, `gh release`, e — via PowerShell —
   `Invoke-WebRequest`/`Invoke-RestMethod`/`iwr`/`irm`) e escrita em arquivo
   de segredo (`.env`, `.pem`, `id_rsa`, `*credentials*`) NUNCA viram
   `allow`, com ou sem contrato ativo. Não é um guard a mais na cascata — é
   avaliado primeiro, sem exceção, porque "sem contrato → allow" avaliado
   antes do floor abriria uma falha real de segurança (push/segredos
   liberados em qualquer repo sem `feature_list.json`). **Escopo do floor de
   segredo no caminho Bash/PowerShell (correção do achado #3 do backlog do
   issue #1):** restrito a REDIRECIONAMENTO (`>`, `>>`, `tee` no Bash;
   `Set-Content`/`Out-File`/`Add-Content`/`>`/`[IO.File]::WriteAllText` e
   variantes no PowerShell) cujo alvo casa `is_floor_secret_path` —
   deliberadamente NÃO persegue escrita indireta via interpretador (`python
   -c "open('.env','w')...`, `node -e ...`): é uma corrida armamentista de
   custo desproporcional para este mecanismo; a redireção/cmdlets de escrita
   cobrem o caso comum e observável (foi o vetor usado na prática no issue
   #1). Antes desta correção, esta promessa era FALSA no caminho Bash
   sem contrato ativo — `_evaluate_bash` retornava `allow` antes de checar o
   alvo de qualquer redirecionamento. Mesma classe de limite aceita (não
   corrigida, avaliada e descartada por custo desproporcional — validação
   adversarial Opus pós-implementação): ofuscação do alvo do redirecionamento
   via concatenação de fragmentos entre aspas adjacentes no Bash (`echo x >
   ".e"nv`, que o shell reagrupa em `.env` mas a tokenização vê como dois
   tokens `.e`+`nv`) ou via ANSI-C quoting (`echo x > $'\x2eenv'`) também
   escapa do floor de redirecionamento — assumido pelo mesmo motivo do
   interpretador acima.
2. **Proteção contra enfraquecimento de teste** — arquivo que casa
   `test_glob` (do `repo-profile.json`) só é editável se alguma tarefa do
   contrato ativo o declarar em `files[]`; substitui o `guard_tests.py`
   estático (sempre-`ask`) do `compiler.py` por uma decisão por-tarefa.
3. **Superfície de docs dedicada (`docs/**`, Item 4 do backlog do issue
   #1)** — escrita sob `docs/**` é sempre permitida (análoga à exceção já
   existente de `.harness/work/**`, sem `verify_cmd` nem gate de aprovação:
   prosa não quebra teste), MAS com exclusão EXPLÍCITA (defense-in-depth) de
   `AGENTS.md`, `CLAUDE.md`, `Plans.md`, `spec.md` (por nome-base,
   case-insensitive) e `.harness/harness.yaml` (path exato) — mesmo que,
   hoje, nenhum desses arquivos more fisicamente dentro de `docs/**` (todos
   vivem na raiz ou em `.harness/`, então já cairiam fora do prefixo
   `docs/`); a exclusão explícita blinda contra qualquer path que tente
   escapar para fora de `docs/**` via segmentos `..` (o path é normalizado
   com `posixpath.normpath` antes da checagem de prefixo). Deliberadamente
   NÃO usa allowlist `*.md` na raiz — essa proposta original do issue #1 foi
   REJEITADA porque abriria `AGENTS.md` (documento de governança lido no
   início de toda sessão, `lifecycle.py:35,67`) a reescrita livre pelo
   próprio agente que ele governa.
4. **Superfície de scratch (`.harness/scratch/**`, correção do backlog de
   fricção do dogfood elegant-heisenberg)** — artefatos temporários de
   verificação manual de UI (screenshots, dumps de rede, HTML de debug),
   exigidos pelo Passo 8 do plan SKILL.md, não pertencem a `files[]` de
   nenhuma tarefa e não devem poluir a raiz do repo-alvo (na sessão real,
   6 PNGs de verificação ficaram untracked na raiz até remoção manual).
   `.harness/scratch/**` é sempre gravável (mesmo padrão de
   `.harness/work/**`/`docs/**`), com `.gitignore` auto-contido
   (`*` + `!.gitignore`) criado por `install_boundary_guard` — git status
   fica limpo mesmo que o agente esqueça artefatos lá, sem tocar no
   `.gitignore` da raiz do usuário. A checagem
   (`_is_scratch_surface_path`) normaliza com `posixpath.normpath` antes
   do prefixo, e a MESMA normalização foi retrofitada ao check de
   `.harness/work/**` (`_is_work_surface_path`): o check anterior usava
   `startswith` sobre o path bruto e deixava
   `.harness/work/../../qualquer.py` escapar por traversal — furo
   pré-existente, corrigido junto. O floor de segredo continua
   precedendo: `.harness/scratch/credentials.json` permanece deny.
   Enforcement é só metade da correção: tools MCP de screenshot
   (`browser_take_screenshot` etc.) caem no branch de tool desconhecida
   (allow-logado, nome sem write/create/edit) e nunca foram bloqueadas na
   raiz — quem redireciona o agente é a orientação (bullet no bloco de
   AGENTS.md gerado por `compiler._render_agents_block`, Passo 8 do plan
   SKILL.md, e a deny message de superfície de `_evaluate_file`, que
   agora aponta `.harness/scratch/` como destino de artefato temporário).
   `claude-progress.md` (raiz do repo) é igualmente sempre gravável
   (`_is_progress_file_path`, match EXATO pós-normalização,
   case-insensitive — um `claude-progress.md` em subdiretório NÃO casa):
   é bookkeeping do PRÓPRIO harness — o lifecycle (passo 12) manda o
   agente atualizá-lo a cada sessão e o `runtime_audit` dá warning se
   ausente, mas a superfície negava a escrita (contradição interna,
   issue 3 do dogfood aegis_rpa_suite). Tensão aceita e documentada: o
   arquivo também é LIDO no início de toda sessão (lifecycle passo 3),
   mesma classe de canal de injection persistida que motivou excluir
   `AGENTS.md` de `docs/**` — mas ser escrito pelo agente É a função
   deste arquivo (notas de estado, não regras de governança); risco
   residual aceito, distinção deliberada em relação a `AGENTS.md`.

O script gerado por `render_boundary_guard()` é standalone (stdlib apenas:
`json`, `re`, `sys` — nada de `import harness`), porque hooks do Claude
Code rodam fora do pacote instalado. `install_boundary_guard()` é quem
escreve esse script em disco e registra o hook em `.claude/settings.json`,
com merge não-destrutivo via `.harness/compiled-state-session.json` — um
arquivo PRÓPRIO deste mecanismo, distinto de `.harness/compiled-state.json`
(que `compiler.py::_write_state` continua reconstruindo do zero a cada
`harness compile`; escrever a chave nova ali seria apagada na próxima
compilação do mecanismo antigo). `compiled-state-session.json` é
COMPARTILHADO com os hooks irmãos de sessão (`session_permissions.py`,
`session_start.py`): cada um grava sob sua própria chave, sempre
preservando as chaves alheias já presentes no arquivo.

**Feature-lock em `.harness/feature_list.json`** — caso especial avaliado
ANTES da checagem genérica de superfície (mas só quando o path editado é o
próprio `feature_list.json`): uma edição (`Edit`/`Write`) que faz alguma
feature transicionar de `passes` não-`true` (ausente, `false` ou qualquer
valor != `True`) para `passes: true` só vira `allow` se, para CADA feature
transicionada, existir `.harness/evidence/<id>.json` (schema fixado em
`verify.py`) válido, com `feature_id` correspondente e `recorded_at`
(ISO8601) mais novo que `git log -1 --format=%cI` (mesmo padrão de
subprocess de `session_start.py::_read_git_log`); sem timestamp de
commit (repo sem commits / não é repo git), exige-se apenas evidência
válida. Se QUALQUER transicionada não tiver evidência fresca, `deny`
citando o(s) id(s) problemáticos. Se a edição não transicionar NENHUMA
feature para `passes:true`, delega ao comportamento genérico de superfície
(hoje resulta em `deny`, já que `feature_list.json` normalmente não é
declarado em `files[]` de nenhuma tarefa).

As PEÇAS PURAS desta lógica (sem dependência de `harness.review`) —
`_parse_iso8601`, `_feature_passes_map`, `_transitions_to_true`,
`_read_last_commit_timestamp`, `_evidence_freshness_problem`,
`_read_team_manifest`, `_manifest_requires_review`, `_feature_by_id`, mais
abaixo — têm UMA fonte de verdade: `render_boundary_guard()` extrai o
código-fonte real destas funções via `inspect.getsource()` e o embute no
script standalone gerado, em vez de manter uma segunda cópia digitada à
mão. O ORQUESTRADOR (`evaluate_feature_list_edit` aqui vs.
`_evaluate_feature_list_edit` na versão standalone) continua com duas
implementações hand-typed — mas hoje só orquestra chamadas às peças
importadas acima (na versão real) ou geradas (na versão standalone) mais o
veto do revisor abaixo; mudou o fluxo de orquestração em si (não as peças
de frescor), muda dos dois lados.

O mesmo padrão de fonte única via `inspect.getsource()` foi ESTENDIDO
(correção do backlog do issue #1, itens 2-4) para as peças de floor/superfície
abaixo, todas puras e stdlib-only: `is_floor_powershell_network` (rede/
publicação específica de PowerShell — `Invoke-WebRequest`/`Invoke-RestMethod`/
`iwr`/`irm` —, reusando `is_floor_bash_command` para o resto, não duplicando
`git push`/`curl`/`wget`/etc.), `is_floor_powershell_secret_write` (heurística
de escrita-em-segredo via PowerShell), `is_floor_bash_secret_redirect`
(heurística de redirecionamento/`tee`-em-segredo via Bash, achado #3) e
`_is_docs_surface_path`+`DOCS_SURFACE_EXCLUDED_BASENAMES`/
`DOCS_SURFACE_EXCLUDED_PATHS` (superfície `docs/**`, achado #4). Os
ORQUESTRADORES que as consomem (`_evaluate_bash`, `_evaluate_file`, e o novo
`_evaluate_powershell`) continuam SEM contraparte importável — mesma razão de
sempre: dependem de outras peças (`_load_json`, `_collect_allowed_files`,
`_glob_to_regex`, `_path_in_surface`) que só existem no script standalone,
então promovê-los a importável exigiria promover a árvore inteira, fora do
escopo desta correção.

**Veto do revisor (Fase 4, padrão Produtor-Revisor)** — checagem ADICIONAL
avaliada depois que a evidência fresca de TODAS as features transicionadas
já foi confirmada (a checagem acima, intocada): se
`.harness/team/manifest.json` existir, for JSON válido e declarar os papéis
`producer` e `reviewer` (`{"producer", "reviewer"} <= set(roles)`), cada
feature transicionada exige ADICIONALMENTE `.harness/review/<id>.json` com
`status == 'approved'` (lido via `harness.review.load_review` na versão
importável; réplica stdlib-only equivalente na versão standalone) e
`updated_at` mais novo que o último commit (mesmo padrão de comparação da
evidência) E não mais antigo que `evidencia.recorded_at` da mesma feature
(reusa o dict de evidência já carregado pela checagem de frescor acima — uma
aprovação anterior à ÚLTIMA evidência gravada está cobrindo um diff que o
revisor nunca viu, portanto obsoleta). Se a feature transicionada tem
`files[]` tocando o `test_glob` do repo-profile (`harness.review.is_test_diff`
na versão importável; réplica standalone equivalente, sem import), o registro
de revisão aprovado também precisa ter `justification` não-vazia (defesa em
profundidade — `review.py` já barra isso na escrita, esta é uma reconfirmação
de leitura, caso o arquivo tenha sido editado por fora da API). Sem
`manifest.json` (ausente, JSON inválido, ou sem os dois papéis), esta
checagem inteira é pulada — comportamento IDÊNTICO à Fase 3. Esta checagem
(`_review_gate_problem`/`_load_review_record`) depende de `harness.review`
(`ReviewError`, `load_review`, `is_test_diff`) e por isso NÃO é gerada via
`inspect.getsource()` — permanece com implementação própria em cada lado,
documentada onde está definida mais abaixo.

**Raiz do repo fixada — deriva de `cwd` (Item 6 do backlog de correção do
issue #1).** Investigação (pré-condição obrigatória do item, ANTES de
codar): consultada a doc oficial do Claude Code
(`https://code.claude.com/docs/en/hooks`, seção "Common input fields") — o
campo `cwd` do payload `PreToolUse` é descrito literalmente como "Current
working directory when the hook is invoked", ou seja, o cwd CORRENTE do
shell no momento da tool call, NÃO uma raiz de projeto fixa; a existência de
um evento dedicado `CwdChanged` ("[w]hen the working directory changes, for
example when Claude executes a `cd` command") confirma independentemente
que essa deriva é um fenômeno real e documentado, não uma hipótese. Logo, o
cenário (b) do backlog se confirma (não o (a)): quando o agente roda `cd
frontend/` sem voltar, o PRÓPRIO `cwd` do payload passa a reportar
`<repo>/frontend` em toda tool call subsequente — não é só o `file_path`
relativo que sofre. Isso é FAIL-OPEN, não apenas falso-deny: em
`_evaluate_file`/`_evaluate_bash`/`_evaluate_powershell`, `_load_json(cwd,
FEATURE_LIST_PATH)` (que junta `cwd` derivado + `.harness/feature_list.json`,
path que só existe sob a raiz real) falha ANTES de qualquer checagem de
superfície, retorna `None`, e o guard responde `allow` com o motivo "sem
contrato ativo" — a checagem de superfície (que produziria só um
falso-deny) nunca chega a rodar, porque o "sem contrato" de curto-circuito
vem primeiro. Por isso a correção ancora `_resolve_path` **e** `_load_json`
na mesma âncora, não só um.

Mecanismo: `install_boundary_guard` grava a raiz absoluta do projeto-alvo
(`target_dir.resolve()`, já calculado ali) sob `REPO_ROOT_STATE_KEY`
(`"repo_root"`) em `SESSION_STATE_FILE`, UMA vez, no momento da compilação —
mesmo merge não-destrutivo já usado para `BOUNDARY_STATE_KEY` (preserva
chaves de `session_permissions.py`/`session_start.py`). Em runtime, o hook
standalone gerado localiza esse arquivo subindo a partir do diretório do
PRÓPRIO script instalado (`__file__`, que sempre mora em
`<repo_root>/.harness/hooks/boundary_guard.py` — não do `cwd` do payload,
que é exatamente o valor que pode ter derivado) via
`_find_session_state_path`/`_read_repo_root_from_state`/
`_resolve_repo_root_anchor` (Python real, IMPORTÁVEL, testável via pytest
direto; embutidas no script gerado via `inspect.getsource()`, mesmo padrão
do commit `4d682d7` — não há uma segunda cópia digitada à mão). `main()`
troca o `cwd` efetivo por essa âncora ANTES de chamar `_resolve_path`/
`_evaluate_file`/`_evaluate_bash`/`_evaluate_powershell` — como todos esses
consumidores recebem o mesmo `cwd` de `main()`, uma única substituição
ancora os dois (e também `_evaluate_feature_list_edit`, que sofre da mesma
classe de bug). Zero subprocess (ao contrário da proposta original do issue,
`git rev-parse --show-toplevel` por tool call — reintroduziria exatamente o
custo que o design deste módulo existe para evitar, docstring linhas 3-8,
além de footguns de submódulo/worktree/repo-sem-git). Fallback OBRIGATÓRIO e
testado: `SESSION_STATE_FILE` ausente, sem a chave, com JSON inválido, ou
com `repo_root` apontando para um diretório que não existe mais em disco →
`_resolve_repo_root_anchor` devolve `None` e `main()` mantém o `cwd` do
payload sem alteração (comportamento ATUAL, idêntico ao pré-correção) —
repos sem `compile-session` recente não quebram.
"""

from __future__ import annotations

import inspect
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from harness.config import HarnessConfig
from harness.killswitch import DISABLED_CHECK_SRC
from harness.review import ReviewError, is_test_diff, load_review

HOOKS_DIR = ".harness/hooks"
BOUNDARY_HOOK_FILENAME = "boundary_guard.py"
SESSION_STATE_FILE = ".harness/compiled-state-session.json"
BOUNDARY_STATE_KEY = "boundary_guard_hook_command"
# Item 6 do backlog de correção do issue #1 (deriva de cwd): chave gravada em
# SESSION_STATE_FILE por `install_boundary_guard`, uma vez, no momento da
# compilação (`compile-session`) — a raiz absoluta do projeto-alvo, lida em
# runtime pelo hook standalone para ancorar `_resolve_path`/`_load_json` em
# vez do `cwd` reportado pela tool call (que pode derivar). Ver
# `_resolve_repo_root_anchor` mais abaixo e a seção correspondente do
# docstring do módulo.
REPO_ROOT_STATE_KEY = "repo_root"
LEGACY_GUARD_TESTS_MARKER = "guard_tests.py"

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


def is_floor_bash_command(command: str) -> bool:
    """True se `command` casa alguma sequência do runtime floor (git push,
    curl, wget, npm publish, pip upload, twine upload, gh release)."""
    tokens = _tokenize_command(command)
    return any(_has_sequence(tokens, seq) for seq in FLOOR_BASH_SEQUENCES)


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


PROGRESS_FILE_NAME = "claude-progress.md"


def _is_progress_file_path(path: str) -> bool:
    """True se `path` (já `/`-separado) é o `claude-progress.md` da RAIZ do
    repo — bookkeeping do próprio harness (o lifecycle, passo 12, manda o
    agente atualizá-lo a cada sessão; `runtime_audit` dá warning se ausente),
    sempre gravável. Match EXATO pós-`posixpath.normpath`, case-insensitive
    (filesystem Windows): um `claude-progress.md` dentro de subdiretório NÃO
    casa — só o canônico da raiz; a normalização cobre variantes como
    `docs/../claude-progress.md`. Correção do issue 3 do dogfood
    aegis_rpa_suite (guard negava escrita no arquivo que o próprio harness
    manda manter)."""
    import posixpath

    normalized = posixpath.normpath(path or "")
    return normalized.lower() == PROGRESS_FILE_NAME


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
# itens 3 do parecer cético sobre os issues 1-2 do dogfood aegis_rpa_suite.
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
    "cat", "head", "tail", "wc", "grep", "rg", "ls", "echo", "find",
})
FIND_WRITE_FLAGS = frozenset({
    "-delete", "-exec", "-execdir", "-ok", "-okdir",
    "-fprint", "-fprintf", "-fprint0", "-fls",
})
GREP_RG_EXEC_FLAGS = ("--pre", "--pre-glob", "--hostname-bin")


def _is_grep_exec_flag(token: str) -> bool:
    """True se `token` é flag de exec do grep/rg (`--pre`, `--pre-glob`,
    `--hostname-bin`), em forma exata ou `--flag=valor`. `--pretty`/`-p`
    NÃO casam (match por igualdade/`=`, não por prefixo)."""
    for flag in GREP_RG_EXEC_FLAGS:
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
    return True


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


def _transitions_to_true(old_data: Any, new_data: Any) -> list[Any]:
    old_map = _feature_passes_map(old_data)
    new_map = _feature_passes_map(new_data)
    return [fid for fid, val in new_map.items() if val and not old_map.get(fid, False)]


def _evidence_freshness_problem(
    cwd: Path | str | None, feature_id: Any, commit_ts: str | None
) -> tuple[str | None, dict[str, Any] | None]:
    """`(None, evidence)` se a evidência de `feature_id` existe, é válida e
    (quando `commit_ts` fornecido) mais nova que ele; senão, `(problema,
    None)` descrevendo o problema. O dict de evidência é devolvido junto
    (mesmo objeto já parseado, sem reler o arquivo) para o chamador reusar na
    checagem do veto do revisor (comparação contra `evidencia.recorded_at`)."""
    base = Path(cwd) if cwd else Path(".")
    evidence_path = base / EVIDENCE_DIR_NAME / f"{feature_id}.json"
    if not evidence_path.is_file():
        return f"{feature_id}: sem evidência (.harness/evidence/{feature_id}.json não existe)", None
    try:
        evidence = json.loads(evidence_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return f"{feature_id}: evidência inválida (JSON malformado)", None
    if not isinstance(evidence, dict) or evidence.get("feature_id") != feature_id:
        return f"{feature_id}: evidência inválida (feature_id não corresponde)", None
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
        problem, evidence = _evidence_freshness_problem(base, fid, commit_ts)
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
# (que continua stdlib-only). O valor lido vira uma constante Python
# literal (`EXTRA_ALLOWED_COMMANDS`) baked no script por `render_boundary_guard`
# — mesmo padrão de `FIXED_GIT_SEQUENCES`/`FIXED_HARNESS_SEQUENCES` — em vez
# de o hook reler o YAML em runtime.
# ---------------------------------------------------------------------------
HARNESS_YAML_RELATIVE_PATH = ".harness/harness.yaml"


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

def render_boundary_guard(
    extra_allowed_commands: list[str] | None = None,
    protected_branches: list[str] | None = None,
) -> str:
    """Devolve o código-fonte (string) do hook `PreToolUse` standalone.

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
        inspect.getsource(is_floor_bash_command),
        inspect.getsource(_current_git_branch),
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
        f"DOCS_SURFACE_DIR_PREFIX = {DOCS_SURFACE_DIR_PREFIX!r}",
        f"DOCS_SURFACE_EXCLUDED_BASENAMES = {set(DOCS_SURFACE_EXCLUDED_BASENAMES)!r}",
        f"DOCS_SURFACE_EXCLUDED_PATHS = {set(DOCS_SURFACE_EXCLUDED_PATHS)!r}",
        inspect.getsource(_is_docs_surface_path),
        f"WORK_DIR_PREFIX = {WORK_DIR_PREFIX!r}",
        f"SCRATCH_DIR_PREFIX = {SCRATCH_DIR_PREFIX!r}",
        inspect.getsource(_is_work_surface_path),
        inspect.getsource(_is_scratch_surface_path),
        f"PROGRESS_FILE_NAME = {PROGRESS_FILE_NAME!r}",
        inspect.getsource(_is_progress_file_path),
        inspect.getsource(_is_claude_memory_path),
        f"READONLY_SHELL_UTILITIES = {set(READONLY_SHELL_UTILITIES)!r}",
        f"FIND_WRITE_FLAGS = {set(FIND_WRITE_FLAGS)!r}",
        f"GREP_RG_EXEC_FLAGS = {GREP_RG_EXEC_FLAGS!r}",
        inspect.getsource(_is_grep_exec_flag),
        inspect.getsource(_segment_has_file_redirect),
        inspect.getsource(_is_readonly_shell_segment),
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
        inspect.getsource(_transitions_to_true),
        inspect.getsource(_read_last_commit_timestamp),
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
]

# --- subcomandos do proprio harness sempre liberados quando ha contrato
# ativo: a ferramenta que GERENCIA o contrato nao pode ficar presa no
# guard que ela mesma gerou. Cobre as duas formas de invocacao
# documentadas nas skills (python -m harness.cli) e o console-script real
# (harness). NAO inclui 'run' (orquestrador da era congelada, chama a
# API Anthropic — rede fora do floor — e nao estava na fricao relatada).
# 'task' entrou na correcao do issue 3 do dogfood aegis_rpa_suite: e o
# escape oficial documentado na skill plan (harness task add-file) para
# ampliar a superficie de uma tarefa — sem ele aqui, o guard fechava a
# porta E escondia a chave (o proprio deny message apontava um comando
# que o guard negava).
_HARNESS_SUBCOMMANDS = [
    "compile", "audit", "audit-runtime", "analyze", "preflight",
    "compile-contract", "compile-session", "verify", "team", "review",
    "supervise", "audit-team", "task",
]
FIXED_HARNESS_SEQUENCES = (
    [["harness", sub] for sub in _HARNESS_SUBCOMMANDS]
    + [["python", "-m", "harness.cli", sub] for sub in _HARNESS_SUBCOMMANDS]
)
''' + f"""
# --- comandos extras declarados em governance.extra_allowed_commands
# (.harness/harness.yaml) — bakeado no momento da instalacao, mesmo padrao
# de FIXED_GIT_SEQUENCES/FIXED_HARNESS_SEQUENCES acima ---
EXTRA_ALLOWED_COMMANDS = {list(extra_allowed_commands or [])!r}

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
        "branch protegida '" + branch + "' - commit direto proibido, so via "
        "PR; rode `harness compile-session` para criar/mudar para a branch "
        "de contrato (contract/<slug>)"
    )


FEATURE_LIST_PATH = ".harness/feature_list.json"
PROFILE_PATH = ".harness/repo-profile.json"
EVIDENCE_DIR_NAME = ".harness/evidence"
TEAM_MANIFEST_RELATIVE_PATH = ".harness/team/manifest.json"
REVIEW_DIR = ".harness/review"
# WORK_DIR_PREFIX (area de autoria de contrato) e SCRATCH_DIR_PREFIX (area de
# scratch para artefato temporario de verificacao) vem da faixa GERADA acima,
# junto com _is_work_surface_path/_is_scratch_surface_path (normalizacao
# anti-traversal) - fonte unica em harness.boundary_guard.

# package_manager.value (analyzer.py) -> comando de instalação EXATO. Mesmo
# mapeamento de harness.session_permissions/harness.templates: o valor bruto
# do profile (ex.: "npm") NUNCA vira um comando permitido por si só - isso
# liberaria qualquer subcomando ("npm run x", "npm exec"), nao so a instalacao.
INSTALL_COMMAND_BY_PACKAGE_MANAGER = {
    "npm": "npm ci",
    "pnpm": "pnpm install --frozen-lockfile",
    "yarn": "yarn install --frozen-lockfile",
    "uv": "uv sync",
    "poetry": "poetry install",
    "pip": "pip install -e .",
}


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
    'aparece em qualquer janela') alguma das sequencias permitidas."""
    for seq in sequences:
        if seq and seg_tokens[:len(seq)] == seq:
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
    for key in ("lint_command", "typecheck_command", "build_command"):
        value = _profile_extra_value(profile, key)
        if value:
            commands.append(value)
    package_manager_value = _profile_entry_value(profile, "package_manager")
    install_cmd = (
        INSTALL_COMMAND_BY_PACKAGE_MANAGER.get(package_manager_value)
        if package_manager_value
        else None
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
        problem, evidence = _evidence_freshness_problem(cwd, fid, commit_ts)
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
            "claude-progress.md e bookkeeping do proprio harness (o lifecycle "
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
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"
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
        "HTML de debug)? salve em .harness/scratch/ ; se o escopo mudou, replaneje "
        "via /harness-creator:plan"
    )


def _evaluate_bash(command, cwd):
    if is_floor_bash_command(command):
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

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"
    if _contract_fully_passed(feature_list):
        return "allow", (
            "contrato concluido (todas as features com passes:true) - boundary_guard "
            "se aposenta da superficie de comando ate o proximo /harness-creator:plan; "
            "floor (segredo/rede/push/kill-switch/branch protegida) continua incondicional"
        )

    if "$(" in command or "`" in command:
        return "deny", (
            "command substitution ($(...) ou crase) nao permitido - cada "
            "sub-comando precisa ser declarado explicitamente na superficie do contrato"
        )

    profile = _load_json(cwd, PROFILE_PATH)
    allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    allowed_sequences = (
        FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES
        + [_tokenize_command(c) for c in allowed_commands]
        + [_tokenize_command(c) for c in EXTRA_ALLOWED_COMMANDS]
    )

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
        return "deny", (
            "segmento '" + failing[:80] + "' fora da superficie compilada do "
            "contrato (verify_cmd/lint/typecheck/build/install/git local) e "
            "nao aceito como utilitario read-only (cat/head/tail/wc/grep/rg/"
            "ls/echo/find sem redirecionamento de escrita) nem cd intra-repo; "
            "replaneje via /harness-creator:plan se precisar de outro comando"
        )
    return "deny", (
        "comando fora da superficie compilada do contrato "
        "(verify_cmd/lint/typecheck/build/install/git local); replaneje via "
        "/harness-creator:plan se precisar de outro comando"
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

    feature_list = _load_json(cwd, FEATURE_LIST_PATH)
    if feature_list is None:
        return "allow", "sem contrato ativo — boundary_guard não gateia fora de uma sessão de contrato"
    if _contract_fully_passed(feature_list):
        return "allow", (
            "contrato concluido (todas as features com passes:true) - boundary_guard "
            "se aposenta da superficie de comando ate o proximo /harness-creator:plan; "
            "floor (segredo/rede/push/kill-switch/branch protegida) continua incondicional"
        )

    target = _extract_powershell_write_target(command)
    if target is not None:
        path = _resolve_path(target, cwd)
        return _evaluate_file(path, cwd)

    profile = _load_json(cwd, PROFILE_PATH)
    allowed_commands = _collect_allowed_bash_commands(feature_list, profile)
    allowed_sequences = (
        FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES
        + [_tokenize_command(c) for c in allowed_commands]
        + [_tokenize_command(c) for c in EXTRA_ALLOWED_COMMANDS]
    )

    segments = _split_shell_segments(command)
    if segments and all(
        _segment_prefixes_any(_tokenize_command(seg), allowed_sequences) for seg in segments
    ):
        return "allow", (
            "comando declarado na superficie compilada do contrato "
            "(verify_cmd/lint/typecheck/build/install/git local) - PowerShell"
        )
    return "deny", (
        "comando fora da superficie compilada do contrato (PowerShell); "
        "replaneje via /harness-creator:plan se precisar de outro comando"
    )


# Tools read-only/utilitarias CONHECIDAS que passam sem analise de escrita
# (Item 1 do backlog de correcao do issue #1). Task e usado pelo proprio
# harness (subagentes) e NAO pode cair no branch de tool desconhecida.
_READONLY_ALLOWLIST_TOOLS = ("Read", "Glob", "Grep", "Task", "WebFetch", "TodoWrite")

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
    em `target_dir/.claude/settings.json` (matcher `"*"`, constante
    `BOUNDARY_HOOK_MATCHER`). Merge não-destrutivo via
    `target_dir/.harness/compiled-state-session.json`
    (chave própria `boundary_guard_hook_command`, preservando outras chaves
    já presentes — o arquivo é compartilhado com hooks irmãos de sessão).
    Também grava, sob `REPO_ROOT_STATE_KEY` (`"repo_root"`), a raiz absoluta
    de `target_dir` — Item 6 do backlog de correção do issue #1 (deriva de
    `cwd`): o hook standalone lê essa chave em runtime (`_resolve_repo_root_anchor`)
    para ancorar a resolução de path/contrato na raiz real do repo, em vez do
    `cwd` reportado pela tool call, que pode ter derivado.

    Também remove, de `hooks.PreToolUse`, qualquer entrada legada cujo
    `command` referencie o `guard_tests.py` gerado pelo `compiler.py`
    (mecanismo antigo, v0.10.0): o `boundary_guard.py` já cobre a proteção
    de teste (por tarefa do contrato), e manter os dois ativos faria o hook
    antigo disparar `ask` (auto-negado em modo headless) para o mesmo Edit
    que este já libera por `allow`. Nenhuma outra entrada de
    `hooks.PreToolUse` é tocada (ex.: `guard_test_runner.py`).
    """
    target_dir = target_dir.resolve()

    hooks_dir = target_dir / HOOKS_DIR
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script_path = hooks_dir / BOUNDARY_HOOK_FILENAME
    extra_allowed_commands = load_extra_allowed_commands(target_dir)
    protected_branches = load_protected_branches(target_dir)
    script_path.write_text(
        render_boundary_guard(extra_allowed_commands, protected_branches),
        encoding="utf-8",
    )

    # Garantia 4 (superfície de scratch): cria .harness/scratch/ com
    # .gitignore auto-contido (`*` + `!.gitignore`) — a pasta se ignora
    # sozinha, sem tocar no .gitignore da raiz do usuário; git status fica
    # limpo mesmo que o agente esqueça screenshots/dumps lá. Não sobrescreve
    # um .gitignore já existente (o usuário pode ter customizado).
    scratch_dir = target_dir / SCRATCH_DIR_PREFIX.rstrip("/")
    scratch_dir.mkdir(parents=True, exist_ok=True)
    scratch_gitignore = scratch_dir / ".gitignore"
    if not scratch_gitignore.is_file():
        scratch_gitignore.write_text("*\n!.gitignore\n", encoding="utf-8")

    # Kill-switch: o sentinel `.harness/harness.disabled` é estado operacional
    # de máquina (machine-local), nunca versionado — garante (idempotente) uma
    # linha em `.harness/.gitignore` para ele. `.harness/` no geral É versionado
    # (work/, feature_list.json viajam pra branch), então o ignore precisa ser
    # explícito por arquivo. Preserva qualquer conteúdo já presente.
    harness_gitignore = target_dir / HOOKS_DIR.split("/")[0] / ".gitignore"
    existing = (
        harness_gitignore.read_text(encoding="utf-8") if harness_gitignore.is_file() else ""
    )
    if DISABLE_SENTINEL_BASENAME not in existing.split():
        harness_gitignore.write_text(
            (existing.rstrip("\n") + "\n" if existing.strip() else "")
            + DISABLE_SENTINEL_BASENAME + "\n",
            encoding="utf-8",
        )

    command = f'python "{script_path}"'

    settings_path = target_dir / ".claude" / "settings.json"
    settings: dict[str, Any] = _load_json_state(settings_path)

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

    kept_entries = [
        e for e in pre if not _is_old_managed(e) and not _is_legacy_guard_tests(e)
    ]
    new_entry = {
        "matcher": BOUNDARY_HOOK_MATCHER,
        "hooks": [{"type": "command", "command": command}],
    }
    hooks["PreToolUse"] = kept_entries + [new_entry]

    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    state[BOUNDARY_STATE_KEY] = command
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
