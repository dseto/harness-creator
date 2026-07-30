# Histórico de decisões — `boundary_guard.py`

Este documento preserva o histórico de decisão que antes vivia no docstring
de módulo de `src/harness/boundary_guard.py` (284 linhas). Movido como parte
da tarefa T-02 do contrato
[onda-1-flags-e-facas](../../.harness/work/onda-1-flags-e-facas/spec.md) —
o hook compilado nunca carrega esse texto (`render_boundary_guard()` gera um
cabeçalho próprio de 33 linhas), então o histórico completo só custava
leitura no arquivo-fonte. O docstring atual do módulo é um contrato de
comportamento conciso; este arquivo é a arqueologia por trás de cada
cláusula dele.

## Origem: Fase 2 do ROADMAP

Substitui o padrão de N guards por ação (um hook por matcher) por UM único
hook `PreToolUse` que cobre `Edit`, `Write`, `MultiEdit`, `NotebookEdit`,
`PowerShell` e `Bash` ao mesmo tempo, decidindo `allow`/`deny` a partir da
superfície do contrato ATIVO (`.harness/feature_list.json`, compilado por
`contract.py`). Resolve a latência de N subprocessos por tool call que o
design anterior (um guard por ação, em `compiler.py`) pagava.

## Matcher do hook e roteamento explícito (issue #1, achado #1 — "bypass de tool de escrita")

O matcher registrado é `"*"`, não `"Edit|Write|Bash"`: CONFIRMADO via
consulta à documentação oficial do Claude Code
(`https://code.claude.com/docs/en/hooks`, seção de matcher patterns) que,
para `PreToolUse`, o matcher filtra pelo NOME da tool e `"*"`/`""`/omitido
casam TODA tool call — não assumido a partir do padrão de
`session_start.py:212` (aquele é matcher de `SessionStart`, que casa a
ORIGEM da sessão — startup/resume/clear/compact —, namespace DIFERENTE de
`PreToolUse`, que casa nome de tool; a semântica de `"*"` coincidiu nos dois
casos, mas por MOTIVOS diferentes, confirmados independentemente).

Com matcher `"Edit|Write|Bash"`, qualquer tool de escrita fora desse
conjunto (PowerShell, NotebookEdit, MCP filesystem tools) nunca invocava o
hook — o Claude Code aplicava o allow implícito ANTES de o `else: allow` de
`main()` sequer rodar. Alargar o matcher sozinho não bastaria (só trocaria
"nunca avaliado" por "avaliado só pelo fallback genérico"); por isso
`main()` agora roteia EXPLICITAMENTE: `Edit`/`Write` → `_evaluate_file`;
`MultiEdit` (múltiplas edições `old_string`/`new_string` sobre um ÚNICO
arquivo, `tool_input["file_path"]` — correção adicional pós-implementação,
validação adversarial Opus: sem esta rota, `MultiEdit` caía no ramo de tool
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
`PowerShell` → `_evaluate_powershell`; `Bash` → `_evaluate_bash`.

Uma allowlist pequena e FIXA de tools read-only/utilitárias conhecidas
(`Read`, `Glob`, `Grep`, `Task`, `WebFetch`, `TodoWrite`) passa sem análise —
`Task` é usado pelo próprio harness (subagentes) e NÃO pode cair em deny.
Para qualquer tool NÃO enumerada acima (MCP arbitrária, tool nova do Claude
Code, etc.): política MÍNIMA para o deploy single-user interno deste
plugin — NÃO é um framework de governança MCP abrangente, NÃO é
default-deny-tudo (que quebraria `Task`/`WebFetch` e qualquer tool
utilitária futura não antecipada aqui). Nome com cara de escrita
(`mcp__*__write*`, ou contendo `create`/`edit`, case-insensitive) → `deny`;
resto → `allow` LOGADO (a razão da decisão cita explicitamente que é
allow-logado por política mínima).

**Risco residual assumido, por escrito:** uma tool MCP de escrita cujo nome
não contenha `write`/`create`/`edit` (ex.: `mcp__foo__persist`,
`mcp__foo__save`) passa sem análise — aceitável no contexto de deploy
single-user interno descrito no backlog; se o conjunto de MCP servers
conectados mudar para incluir ferramentas de terceiros não confiáveis, esta
política mínima deve ser revisada (idealmente allowlist explícita por nome,
não por padrão de substring). **Nota (2026-07-30, achado #17 da auditoria
de simplificação):** este é exatamente o comportamento que negou a tool
nativa `TaskCreate` do próprio Claude Code numa sessão real — o nome
contém "create". Risco confirmado em produção, não só teórico; candidato a
correção de Onda futura (allowlist de tools nativas de task-tracking).

## As quatro garantias, na ordem em que são avaliadas

1. **Runtime floor** — roda incondicionalmente ANTES de qualquer outra
   verificação, inclusive antes de checar se existe contrato ativo:
   `git push`, publicação/rede não planejada (`curl`, `wget`, `npm publish`,
   `pip upload`, `twine upload`, `gh release`, e — via PowerShell —
   `Invoke-WebRequest`/`Invoke-RestMethod`/`iwr`/`irm`) e escrita em arquivo
   de segredo (`.env`, `.pem`, `id_rsa`, `*credentials*`) NUNCA viram
   `allow`, com ou sem contrato ativo. Não é um guard a mais na cascata — é
   avaliado primeiro, sem exceção, porque "sem contrato → allow" avaliado
   antes do floor abriria uma falha real de segurança (push/segredos
   liberados em qualquer repo sem `feature_list.json`).

   **Escopo do floor de segredo no caminho Bash/PowerShell (achado #3 do
   backlog do issue #1):** restrito a REDIRECIONAMENTO (`>`, `>>`, `tee` no
   Bash; `Set-Content`/`Out-File`/`Add-Content`/`>`/
   `[IO.File]::WriteAllText` e variantes no PowerShell) cujo alvo casa
   `is_floor_secret_path` — deliberadamente NÃO persegue escrita indireta
   via interpretador (`python -c "open('.env','w')..."`, `node -e ...`): é
   uma corrida armamentista de custo desproporcional para este mecanismo; a
   redireção/cmdlets de escrita cobrem o caso comum e observável (foi o
   vetor usado na prática no issue #1). Antes desta correção, esta promessa
   era FALSA no caminho Bash sem contrato ativo — `_evaluate_bash`
   retornava `allow` antes de checar o alvo de qualquer redirecionamento.

   Mesma classe de limite aceita (não corrigida, avaliada e descartada por
   custo desproporcional — validação adversarial Opus pós-implementação):
   ofuscação do alvo do redirecionamento via concatenação de fragmentos
   entre aspas adjacentes no Bash (`echo x > ".e"nv`, que o shell reagrupa
   em `.env` mas a tokenização vê como dois tokens `.e`+`nv`) ou via ANSI-C
   quoting (`echo x > $'\x2eenv'`) também escapa do floor de
   redirecionamento — assumido pelo mesmo motivo do interpretador acima.

2. **Proteção contra enfraquecimento de teste** — arquivo que casa
   `test_glob` (do `repo-profile.json`) só é editável se alguma tarefa do
   contrato ativo o declarar em `files[]`; substitui o `guard_tests.py`
   estático (sempre-`ask`) do `compiler.py` por uma decisão por-tarefa.

   **Nota (2026-07-30, T-04 da Onda 1):** o `guard_tests.py` estático
   citado aqui como precedente histórico deixou de ser GERADO por
   `compiler.py` a partir desta mesma onda de simplificação — a proteção
   por-tarefa descrita neste item 2 já cobria integralmente o caso desde a
   Fase 2, tornando a geração do script antigo puro peso morto.

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
   fricção do dogfood venv-Windows)** — artefatos temporários de
   verificação manual de UI (screenshots, dumps de rede, HTML de debug),
   exigidos pelo Passo 8 do `plan` SKILL.md, não pertencem a `files[]` de
   nenhuma tarefa e não devem poluir a raiz do repo-alvo (na sessão real, 6
   PNGs de verificação ficaram untracked na raiz até remoção manual).
   `.harness/scratch/**` é sempre gravável (mesmo padrão de
   `.harness/work/**`/`docs/**`), com `.gitignore` auto-contido (`*` +
   `!.gitignore`) criado por `install_boundary_guard` — git status fica
   limpo mesmo que o agente esqueça artefatos lá, sem tocar no `.gitignore`
   da raiz do usuário. A checagem (`_is_scratch_surface_path`) normaliza com
   `posixpath.normpath` antes do prefixo, e a MESMA normalização foi
   retrofitada ao check de `.harness/work/**` (`_is_work_surface_path`): o
   check anterior usava `startswith` sobre o path bruto e deixava
   `.harness/work/../../qualquer.py` escapar por traversal — furo
   pré-existente, corrigido junto. O floor de segredo continua precedendo:
   `.harness/scratch/credentials.json` permanece deny. Enforcement é só
   metade da correção: tools MCP de screenshot (`browser_take_screenshot`
   etc.) caem no branch de tool desconhecida (allow-logado, nome sem
   write/create/edit) e nunca foram bloqueadas na raiz — quem redireciona o
   agente é a orientação (bullet no bloco de AGENTS.md gerado por
   `compiler._render_agents_block`, Passo 8 do plan SKILL.md, e a deny
   message de superfície de `_evaluate_file`, que agora aponta
   `.harness/scratch/` como destino de artefato temporário).

   `.harness/progress.md` é igualmente sempre gravável
   (`_is_progress_file_path`, match EXATO pós-normalização,
   case-insensitive — um `progress.md` em subdiretório NÃO casa): é
   bookkeeping do PRÓPRIO harness — o lifecycle (passo 12) manda o agente
   atualizá-lo a cada sessão e o `runtime_audit` dá warning se ausente, mas
   a superfície negava a escrita (contradição interna, issue 3 do dogfood
   venv-Windows). Tensão aceita e documentada: o arquivo também é LIDO no
   início de toda sessão (lifecycle passo 3), mesma classe de canal de
   injection persistida que motivou excluir `AGENTS.md` de `docs/**` — mas
   ser escrito pelo agente É a função deste arquivo (notas de estado, não
   regras de governança); risco residual aceito, distinção deliberada em
   relação a `AGENTS.md`.

## Geração via `inspect.getsource()` — fonte única

O script gerado por `render_boundary_guard()` é standalone (stdlib apenas:
`json`, `re`, `sys` — nada de `import harness`), porque hooks do Claude Code
rodam fora do pacote instalado. `install_boundary_guard()` é quem escreve
esse script em disco e registra o hook em `.claude/settings.local.json`
(machine-local — ver `harness.settings_paths`), com merge não-destrutivo
via `.harness/compiled-state-session.json` — um arquivo PRÓPRIO deste
mecanismo, distinto de `.harness/compiled-state.json` (que
`compiler.py::_write_state` continua reconstruindo do zero a cada `harness
compile`; escrever a chave nova ali seria apagada na próxima compilação do
mecanismo antigo). `compiled-state-session.json` é COMPARTILHADO com os
hooks irmãos de sessão (`session_permissions.py`, `session_start.py`): cada
um grava sob sua própria chave, sempre preservando as chaves alheias já
presentes no arquivo.

As PEÇAS PURAS desta lógica (sem dependência de `harness.review`) —
`_parse_iso8601`, `_feature_passes_map`, `_transitions_to_true`,
`_read_last_commit_timestamp`, `_evidence_freshness_problem`,
`_read_team_manifest`, `_manifest_requires_review`, `_feature_by_id`, e
outras — têm UMA fonte de verdade: `render_boundary_guard()` extrai o
código-fonte real destas funções via `inspect.getsource()` e o embute no
script standalone gerado, em vez de manter uma segunda cópia digitada à
mão. O ORQUESTRADOR (`evaluate_feature_list_edit` na versão importável vs.
`_evaluate_feature_list_edit` na versão standalone) continua com duas
implementações hand-typed — mas hoje só orquestra chamadas às peças
importadas/geradas mais o veto do revisor abaixo; mudou o fluxo de
orquestração em si (não as peças de frescor), muda dos dois lados.

O mesmo padrão de fonte única via `inspect.getsource()` foi ESTENDIDO
(correção do backlog do issue #1, itens 2-4) para as peças de floor/
superfície: `is_floor_powershell_network` (rede/publicação específica de
PowerShell — `Invoke-WebRequest`/`Invoke-RestMethod`/`iwr`/`irm` —, reusando
`is_floor_bash_command` para o resto, não duplicando `git push`/`curl`/
`wget`/etc.), `is_floor_powershell_secret_write` (heurística de
escrita-em-segredo via PowerShell), `is_floor_bash_secret_redirect`
(heurística de redirecionamento/`tee`-em-segredo via Bash, achado #3) e
`_is_docs_surface_path`+`DOCS_SURFACE_EXCLUDED_BASENAMES`/
`DOCS_SURFACE_EXCLUDED_PATHS` (superfície `docs/**`, achado #4). Os
ORQUESTRADORES que as consomem (`_evaluate_bash`, `_evaluate_file`, e
`_evaluate_powershell`) continuam SEM contraparte importável — mesma razão
de sempre: dependem de outras peças (`_load_json`, `_collect_allowed_files`,
`_glob_to_regex`, `_path_in_surface`) que só existem no script standalone,
então promovê-los a importável exigiria promover a árvore inteira, fora do
escopo desta correção.

**Nota (2026-07-30, achado #11 da auditoria de simplificação):**
`_evaluate_bash` e `_evaluate_powershell` (e o par
`evaluate_feature_list_edit`/`_review_gate_problem` desta seção) são duas
cópias mantidas à mão com a MESMA sequência lógica de passos e já
divergentes entre si (similaridade textual medida: 0,35–0,56) — candidato a
correção de Onda futura (extrair `_evaluate_command(flavor)` e embutir
`review.py` via o mesmo padrão `getsource()` já usado acima).

## Feature-lock em `.harness/feature_list.json`

Caso especial avaliado ANTES da checagem genérica de superfície (mas só
quando o path editado é o próprio `feature_list.json`): uma edição
(`Edit`/`Write`) que faz alguma feature transicionar de `passes`
não-`true` (ausente, `false` ou qualquer valor != `True`) para
`passes: true` só vira `allow` se, para CADA feature transicionada,
existir `.harness/evidence/<id>.json` (schema fixado em `verify.py`)
válido, com `feature_id` correspondente e `recorded_at` (ISO8601) mais
novo que `git log -1 --format=%cI` (mesmo padrão de subprocess de
`session_start.py::_read_git_log`); sem timestamp de commit (repo sem
commits / não é repo git), exige-se apenas evidência válida. Se QUALQUER
transicionada não tiver evidência fresca, `deny` citando o(s) id(s)
problemáticos. Se a edição não transicionar NENHUMA feature para
`passes:true`, delega ao comportamento genérico de superfície (hoje
resulta em `deny`, já que `feature_list.json` normalmente não é declarado
em `files[]` de nenhuma tarefa).

## Veto do revisor (Fase 4, padrão Produtor-Revisor)

Checagem ADICIONAL avaliada depois que a evidência fresca de TODAS as
features transicionadas já foi confirmada (a checagem acima, intocada): se
`.harness/team/manifest.json` existir, for JSON válido e declarar os
papéis `producer` e `reviewer` (`{"producer", "reviewer"} <= set(roles)`),
cada feature transicionada exige ADICIONALMENTE `.harness/review/<id>.json`
com `status == 'approved'` (lido via `harness.review.load_review` na
versão importável; réplica stdlib-only equivalente na versão standalone) e
`updated_at` mais novo que o último commit (mesmo padrão de comparação da
evidência) E não mais antigo que `evidencia.recorded_at` da mesma feature
(reusa o dict de evidência já carregado pela checagem de frescor acima —
uma aprovação anterior à ÚLTIMA evidência gravada está cobrindo um diff que
o revisor nunca viu, portanto obsoleta). Se a feature transicionada tem
`files[]` tocando o `test_glob` do repo-profile
(`harness.review.is_test_diff` na versão importável; réplica standalone
equivalente, sem import), o registro de revisão aprovado também precisa
ter `justification` não-vazia (defesa em profundidade — `review.py` já
barra isso na escrita, esta é uma reconfirmação de leitura, caso o arquivo
tenha sido editado por fora da API). Sem `manifest.json` (ausente, JSON
inválido, ou sem os dois papéis), esta checagem inteira é pulada —
comportamento IDÊNTICO à Fase 3. Esta checagem
(`_review_gate_problem`/`_load_review_record`) depende de `harness.review`
(`ReviewError`, `load_review`, `is_test_diff`) e por isso NÃO é gerada via
`inspect.getsource()` — permanece com implementação própria em cada lado.

## Raiz do repo fixada — deriva de `cwd` (Item 6 do backlog de correção do issue #1)

Investigação (pré-condição obrigatória do item, ANTES de codar): consultada
a doc oficial do Claude Code (`https://code.claude.com/docs/en/hooks`,
seção "Common input fields") — o campo `cwd` do payload `PreToolUse` é
descrito literalmente como "Current working directory when the hook is
invoked", ou seja, o cwd CORRENTE do shell no momento da tool call, NÃO uma
raiz de projeto fixa; a existência de um evento dedicado `CwdChanged`
("[w]hen the working directory changes, for example when Claude executes a
`cd` command") confirma independentemente que essa deriva é um fenômeno
real e documentado, não uma hipótese. Logo, o cenário (b) do backlog se
confirma (não o (a)): quando o agente roda `cd frontend/` sem voltar, o
PRÓPRIO `cwd` do payload passa a reportar `<repo>/frontend` em toda tool
call subsequente — não é só o `file_path` relativo que sofre. Isso é
FAIL-OPEN, não apenas falso-deny: em
`_evaluate_file`/`_evaluate_bash`/`_evaluate_powershell`, `_load_json(cwd,
FEATURE_LIST_PATH)` (que junta `cwd` derivado + `.harness/feature_list.json`,
path que só existe sob a raiz real) falha ANTES de qualquer checagem de
superfície, retorna `None`, e o guard responde `allow` com o motivo "sem
contrato ativo" — a checagem de superfície (que produziria só um
falso-deny) nunca chega a rodar, porque o "sem contrato" de curto-circuito
vem primeiro. Por isso a correção ancora `_resolve_path` **e** `_load_json`
na mesma âncora, não só um.

**Mecanismo:** `install_boundary_guard` grava a raiz absoluta do
projeto-alvo (`target_dir.resolve()`, já calculado ali) sob
`REPO_ROOT_STATE_KEY` (`"repo_root"`) em `SESSION_STATE_FILE`, UMA vez, no
momento da compilação — mesmo merge não-destrutivo já usado para
`BOUNDARY_STATE_KEY` (preserva chaves de `session_permissions.py`/
`session_start.py`). Em runtime, o hook standalone gerado localiza esse
arquivo subindo a partir do diretório do PRÓPRIO script instalado
(`__file__`, que sempre mora em `<repo_root>/.harness/hooks/boundary_guard.py`
— não do `cwd` do payload, que é exatamente o valor que pode ter derivado)
via `_find_session_state_path`/`_read_repo_root_from_state`/
`_resolve_repo_root_anchor` (Python real, IMPORTÁVEL, testável via pytest
direto; embutidas no script gerado via `inspect.getsource()`, mesmo padrão
do commit `4d682d7` — não há uma segunda cópia digitada à mão). `main()`
troca o `cwd` efetivo por essa âncora ANTES de chamar
`_resolve_path`/`_evaluate_file`/`_evaluate_bash`/`_evaluate_powershell` —
como todos esses consumidores recebem o mesmo `cwd` de `main()`, uma única
substituição ancora os dois (e também `_evaluate_feature_list_edit`, que
sofre da mesma classe de bug). Zero subprocess (ao contrário da proposta
original do issue, `git rev-parse --show-toplevel` por tool call —
reintroduziria exatamente o custo de subprocess por tool call que o design
deste módulo existe para evitar, além de footguns de submódulo/worktree/
repo-sem-git). Fallback OBRIGATÓRIO e testado: `SESSION_STATE_FILE`
ausente, sem a chave, com JSON inválido, ou com `repo_root` apontando para
um diretório que não existe mais em disco → `_resolve_repo_root_anchor`
devolve `None` e `main()` mantém o `cwd` do payload sem alteração
(comportamento ATUAL, idêntico ao pré-correção) — repos sem
`compile-session` recente não quebram.
