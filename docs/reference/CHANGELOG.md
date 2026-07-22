# Changelog

## Não lançado

Duas correções achadas durante o dogfood do próprio harness-creator
(contrato `hook-reasons-progress-sync`).

### Corrigido
- **Razão concreta nos hooks TDD gerados.** `guard_test_runner.py` e
  `guard_tests.py` (gerados por `compiler._render_guard_test_runner`/
  `_render_guard_tests`) emitiam `permissionDecisionReason` com texto fixo,
  igual em toda aprovação. Agora a razão do `guard_test_runner.py` cita o
  comando Bash executado e a do `guard_tests.py` cita o path do arquivo de
  teste — o humano aprova sabendo o que está em jogo.

### Adicionado
- **Sincronização automática do `claude-progress.md`.** Nova função
  `templates.update_progress_status(target_dir, feature_id, status)`
  (idempotente; no-op silencioso se o arquivo ou a linha não existirem),
  chamada por `verify.run_verify` ao gravar evidência com sucesso: a linha
  da feature na tabela do `claude-progress.md` passa a `done` sem o passo
  manual 12 do lifecycle. A fonte de verdade (`feature_list.json`/`passes`)
  e o rastro legível deixam de divergir. Só a coluna de status muda; a
  seção "Última atualização" e o texto livre do agente ficam intactos.

## 0.17.6 — 2026-07-22

Dogfood real nos repos `entebate`/`elegant-heisenberg`: o `boundary_guard`
bloqueava permanentemente o CLI do próprio produto do repo (ex.:
`python -m mar_committee`), mesmo com contrato `passes:true` — nenhum
`verify_cmd` cobre um comando fora do ciclo de teste, e o único workaround
(compilar um contrato ad-hoc cujos `verify_cmd` SÃO os subcomandos do CLI)
morre a cada recompile e exige plan+aprovação toda vez.

### Adicionado
- **`governance.extra_allowed_commands`** em `.harness/harness.yaml`: lista
  de comandos permanentes que o dono do repo declara, além do que já deriva
  de `verify_cmd`/lint/build/install/git local. Mesma semântica de PREFIXO
  de tokens que `verify_cmd` já tem hoje — sem DSL nova. Vale nas DUAS
  superfícies que já derivam de `verify_cmd`: o `boundary_guard.py`
  (runtime, `_evaluate_bash`/`_evaluate_powershell`) e a enumeração de
  `.claude/settings.json` (`session_permissions.py`, `Bash(<comando>*)`).
  O runtime floor (`git push`, rede não planejada, escrita em segredo)
  continua veto incondicional — uma entrada de floor declarada aqui nunca
  vira `allow`, em nenhuma das duas camadas. Requer `harness compile-session`
  para o hook instalado refletir uma mudança em `harness.yaml` (mesmo baked
  em código gerado que `FIXED_GIT_SEQUENCES`/`FIXED_HARNESS_SEQUENCES` já
  usavam).

## 0.17.5 — 2026-07-22

Itens 3 e 4 da análise dos issues do dogfood aegis_rpa_suite, nas versões
ADAPTADAS pelo parecer cético (agente Fable, avaliação adversarial contra o
código real — pacote original tinha nota 2.5/5; as adaptações abaixo fecham
os furos apontados). Item 5 (`extra_write_globs`) ADIADO por decisão: valor
marginal caiu pós-v0.17.4 (`task add-file` cobre o caso) e a versão proposta
tinha furo de feature-lock.

### Adicionado
- **Utilitários shell read-only sempre permitidos no Bash** (issues 1-2):
  `cat`/`head`/`tail`/`wc`/`grep`/`rg`/`ls`/`echo`/`find` passam como
  segmento avulso ou filtro pós-pipe (`pytest -q | head -40`), com três
  guardas do parecer cético: (1) denylist COMPLETA do `find`
  (`-delete`/`-exec`/`-execdir`/`-ok`/`-okdir` E as flags de escrita sem
  `>`: `-fprint`/`-fprintf`/`-fprint0`/`-fls` — `find . -fprint .env`
  furaria o floor de segredo); (2) `rg`/`grep` com
  `--pre`/`--pre-glob`/`--hostname-bin` negados (exec arbitrário por
  arquivo; match exato/`=`, `--pretty` continua ok); (3) redirecionamento
  de escrita nega o segmento, mas SÓ `>` fora de aspas (`grep "->" src/`
  passa) e ignorando duplicação de fd (`2>&1`); process substitution
  `<(`/`>(` nega.
- **`cd <alvo>` aceito quando o alvo resolve para dentro do repo** (issue
  2): necessário restringir — `git add`/`commit` são liberados
  incondicionalmente e `cd <outro-repo> && git add .` operaria em outro
  repositório. Alvo irresolvível (`$VAR`, `~`, crase, `cd -`, vazio) ou
  âncora de raiz ausente → segue deny. Alvo extraído do texto (não da
  tokenização) — path com espaço funciona.
- `harness verify --timeout <segundos>` (issue 4): o teto fixo de 600s
  matava verify_cmds legítimos (~1100s no dogfood); agora configurável por
  chamada, default preservado. Mensagem de timeout ensina o flag.
- `harness verify --stream` (issue 4): tee de stdout/stderr em tempo real
  para distinguir suíte lenta de travada. OPT-IN por decisão do parecer
  cético: streaming default jogaria toda a saída da suíte no contexto do
  agente a cada verify verde (anti-objetivo de economia de contexto).

### Corrigido
- **`2>&1` não derruba mais o comando** (ponto cego apontado pelo cético):
  o splitter de segmentos cortava no `&` de `2>&1` e o segmento `1` órfão
  causava falso-deny em `pytest -q 2>&1`. `&` precedido de `>` agora é
  tratado como operador de redirecionamento, não de controle.
- **Deny de Bash cita o segmento que falhou** (issue 2): mensagem passa de
  genérica para `segmento '<trecho>' fora da superficie...` — diagnóstico
  imediato de qual parte do pipeline derrubou o comando.
- **`harness verify` não órfã mais netos no timeout** (issue 4): troca de
  `subprocess.run(capture_output=True)` por `Popen` + threads leitoras
  (daemon, join com timeout) + kill de ÁRVORE no timeout E em interrupção
  (`KeyboardInterrupt`) — `taskkill /T /F` no Windows (documentado como
  best-effort: netos reparentados escapam; Job Object descartado por
  custo), `os.killpg` no POSIX. `CREATE_NEW_PROCESS_GROUP` isola o filho
  do Ctrl+C do console para o handler fazer o kill ordenado. Buffer de
  stdout/stderr preservado (alimenta `detect_file_lock_hint` no
  `VerifyFailedError`), exit-code intacto.

### Mudança de comportamento observável
- `echo oi` (e qualquer utilitário da allowlist sem redirect) deixa de ser
  deny sob contrato ativo — era o exemplo canônico de "comando fora da
  superfície" em testes/docs antigos.

### Limites documentados (aceitos, não corrigidos)
- Floor window-match continua negando comando com token do floor no texto
  (`grep -r "curl" src/`) — floor intocável por design.
- PowerShell (`_evaluate_powershell`) segue SEM allowlist read-only —
  débito registrado; a fricção reportada era toda no Bash.
- `taskkill /T` é best-effort (ver acima); airtight exigiria Job Object.

## 0.17.4 — 2026-07-22

Itens 1 e 2 (os cirúrgicos) da análise dos 4 issues reportados pelo dogfood
em `aegis_rpa_suite` (`.harness/work/backlog-agentico-design-time/issues/`).
Ambos são correções de coerência interna: o harness negava operações que o
próprio harness manda executar.

### Corrigido
- **`harness task` liberado pelo guard** (issue 3, ponto 3): `task` entrou
  em `_HARNESS_SUBCOMMANDS` — o escape oficial documentado na skill plan
  (`harness task add-file`, melhorado na v0.17.2 pelo issue #5 do GitHub)
  era negado pelo próprio guard dentro da sessão onde ele é necessário
  ("fecha a porta e esconde a chave"). Cobre `harness task ...` e
  `python -m harness.cli task ...`; smuggle via `&&` continua deny
  (regra de todo-segmento-prefixa intacta).
- **`claude-progress.md` sempre gravável** (issue 3, ponto 1): o lifecycle
  (passo 12) manda o agente atualizá-lo a cada sessão e o `runtime_audit`
  dá warning se ausente — mas a superfície negava a escrita
  (auto-derrotante). Nova `_is_progress_file_path` (match exato
  pós-`posixpath.normpath`, case-insensitive, só o canônico da raiz —
  homônimo em subdiretório continua fora da superfície), importável e
  embutida no script gerado via `inspect.getsource`. Tensão documentada no
  docstring: o arquivo também é lido no início de toda sessão (mesma classe
  de canal de injection persistida do `AGENTS.md`), mas ser escrito pelo
  agente é a função dele — risco residual aceito, distinção deliberada.

### Pendente (mesma análise, aguardando decisão/implementação)
- Filtros read-only pós-pipe + `cd` intra-repo + deny message por segmento
  (issues 1-2); process-group kill + streaming no `harness verify` no
  Windows (issue 4); superfície configurável para output de skill de gate e
  política para path fora do repo_root (issue 3, pontos 2 e 4).

## 0.17.3 — 2026-07-22

Superfície de scratch (`.harness/scratch/**`) — achado de sessão real de
dogfood em `elegant-heisenberg`: durante a verificação manual de UI (Passo 8
do plan SKILL.md), artefatos temporários (screenshots PNG, HTML de debug,
dumps de rede) não pertencem a `files[]` de nenhuma tarefa e não tinham
superfície gravável — o agente salvava na raiz do repo-alvo, poluindo
`git status` (6 PNGs ficaram untracked até remoção manual).

### Adicionado
- Garantia 4 do `boundary_guard`: `.harness/scratch/**` sempre gravável
  (mesmo padrão de `.harness/work/**`/`docs/**`; floor de segredo continua
  precedendo — `.harness/scratch/credentials.json` segue deny). Vale para
  Edit/Write/MultiEdit/NotebookEdit e para alvo de escrita PowerShell
  (roteado por `_evaluate_file`).
- `install_boundary_guard` cria `.harness/scratch/.gitignore` auto-contido
  (`*` + `!.gitignore`) — git status limpo sem tocar no `.gitignore` da
  raiz do usuário; não sobrescreve `.gitignore` customizado.
- Deny message genérica de superfície agora ensina o destino correto:
  "artefato temporário de verificação? salve em `.harness/scratch/`".

### Corrigido
- **Traversal na superfície de work** (furo pré-existente): o check de
  `.harness/work/**` usava `startswith` sobre o path bruto —
  `.harness/work/../../AGENTS.md` virava allow. Agora
  `_is_work_surface_path`/`_is_scratch_surface_path` normalizam com
  `posixpath.normpath` antes do prefixo (mesmo padrão de
  `_is_docs_surface_path`), importáveis e embutidas no script gerado via
  `inspect.getsource`.

### Documentado
- Bullet 5 no bloco gerenciado do AGENTS.md gerado
  (`compiler._render_agents_block`) e Passo 8 item 3 do
  `skills/plan/SKILL.md`: artefatos temporários vão SEMPRE para
  `.harness/scratch/`, nunca para a raiz — necessário porque tools MCP de
  screenshot caem no branch de tool desconhecida (allow-logado) e o
  enforcement sozinho não as redireciona.

## 0.17.2 — 2026-07-20

4 itens do backlog de fricção dos issues #2-#5 (dogfood real da v0.17.0/
0.17.1, Story 3.3 em `elegant-heisenberg`). Nenhum é núcleo de segurança —
ergonomia/doc/design de borda. Item do issue #4 (drift de `permissions.allow`
após `task add-file`) foi investigado ANTES de codar: confirmado que o
`boundary_guard.py` (hook `PreToolUse`, matcher `"*"`) sempre decide
`allow`/`deny` explicitamente a partir do `feature_list.json` lido em tempo
de execução — uma decisão explícita de hook tem precedência sobre
`permissions.allow`, então a lista enumerada desatualizada não abre brecha
nem bloqueia o path novo; fechado doc-only, sem mudança de código.

### Adicionado
- `harness task add-file`: `--slug` agora é opcional — se omitido e houver
  exatamente um contrato em `.harness/work/`, é inferido automaticamente;
  com 0 ou 2+ contratos, erro pedindo `--slug` explícito (comportamento
  atual preservado nesses dois casos) (issue #5).

### Documentado
- `TUTORIAL.md`/`README.md`: nota explicando que `task add-file` recompila
  o contrato mas não o `permissions.allow` enumerado — sem impacto
  funcional, o `boundary_guard.py` decide a partir do contrato em tempo de
  execução (issue #4).
- `skills/plan/references/contract-templates.md`: nota de granularidade
  para tarefas de UI com estado visual condicional — lembrar o arquivo de
  estilo (`.scss`/`.css`) em `files[]` (issue #2).
- `skills/plan/SKILL.md` (Passo 6): nota sobre o escopo da detecção
  MSB3027/EBUSY — só cobre `harness verify`/`--dry-run-verify`, não comandos
  ad-hoc rodados durante debug ativo (issue #3).

## 0.17.1 — 2026-07-20

Achado do dogfood real da v0.17.0 (Story 3.3 em `elegant-heisenberg`): a
implementação completou os 9/9 tasks com suíte automatizada 100% verde, mas
só o teste manual em browser (pedido à parte pelo usuário) revelou 2 defeitos
reais — migration nunca aplicada no Oracle de dev (design-time factory usa
credenciais fictícias) e locale `pt-BR` nunca registrado (formatação de
moeda `R$1,000.00` em vez de `R$ 1.000,00`). Nenhum teste automatizado
(unit/integration/component) pega esses dois.

### Adicionado
- `skills/plan/SKILL.md`: **Passo 8 — Teste manual de UI**, regra dura
  obrigatória sempre que alguma tarefa do contrato tocou frontend. Depois de
  `harness supervise` devolver `next: null`, exige subir a app real
  (backend+frontend+banco real, nunca mock), navegar os critérios de
  aceitação do `spec.md`, capturar evidência real (screenshot/DOM) e corrigir
  defeitos achados antes de declarar a demanda concluída — suíte
  automatizada verde deixa de ser suficiente por si só.

## 0.17.0 — 2026-07-19

7 itens do backlog de fricção do issue #1 (sessão real de 5 contratos
sequenciais), priorizados por análise em múltiplas passadas (triagem →
auditoria adversarial → arbitragem → reflexão → veredito anti-overengineering).

**BREAKING CHANGE:** o hook `boundary_guard.py` passa a ser registrado com
matcher `"*"` (era `"Edit|Write|Bash"`). Toda tool de escrita agora passa pelo
guard. Contratos já compilados continuam válidos; recompile via
`compile-session` para que o hook novo (com `repo_root` no state e o matcher
abrangente) seja instalado.

### Corrigido (segurança)
- **Bypass de tool de escrita fechado:** qualquer tool fora de Edit/Write/Bash
  (PowerShell, NotebookEdit, MultiEdit, MCP filesystem) contornava o floor
  inteiro — nunca invocava o hook. Agora `main()` roteia explicitamente todas
  as tools de escrita conhecidas; avaliador de PowerShell próprio (floor-first);
  allowlist de utilitárias read-only; deny por padrão-de-nome pra MCP de escrita
  desconhecido.
- **Fail-open por deriva de cwd fechado:** o `cwd` do payload PreToolUse é o CWD
  corrente (deriva via `cd`), não a raiz do projeto — sob deriva, o contrato não
  era achado e o guard degenerava em allow. Agora a raiz é gravada
  (`repo_root` em `compiled-state-session.json`) e o hook ancora a resolução de
  path nela.
- **Paridade do floor de segredo no Bash:** redirecionamento (`>`/`>>`/`tee`)
  para arquivo de segredo agora é barrado também no caminho Bash sem contrato.

### Adicionado
- **Superfície de docs:** allowlist `docs/**` (sem verify_cmd nem aprovação),
  excluindo explicitamente arquivos de governança (AGENTS.md/CLAUDE.md/
  Plans.md/spec.md/harness.yaml). Elimina o motivo do bypass via shell.
- **`harness task add-file <task-id> <path>`:** append em `files[]` de uma task
  no Plans.md + recompila, sem editar o markdown à mão. Mantém o gate de
  aprovação.
- **Detecção de lock de arquivo em verify_cmd:** MSB3027/MSB3021/EBUSY/etc.
  disparam mensagem acionável (causa provável: processo do projeto-alvo
  rodando). Detecção-only — nunca mata processo.

### Nota
Limites residuais aceitos e documentados no floor (deploy single-user interno):
escrita de segredo via interpretador (`python -c`) ou ofuscação do alvo por
concatenação de aspas/ANSI-C; MCP de escrita cujo nome não contenha
write/create/edit. Ver `ROADMAP-issue1-friccao-sessao-real.correction.backlog.md`
e issue #1.

## 0.16.1 — 2026-07-19

8 achados da auditoria skill-audit (2026-07-19) + backlog de fricção do
dogfood (Story 2.6 em elegant-heisenberg), sem breaking change.

### Corrigido
- `verify.py`/`contract.py`: `UnicodeDecodeError` (cp1252) em `subprocess.run`
  de `verify_cmd` no Windows — `encoding="utf-8", errors="replace"` explícito.

### Adicionado
- `harness verify <id> --mark-passed`: flag opt-in que grava `passes:true`
  em `feature_list.json` quando `exit_code==0`, pra sessão orquestradora
  sequencial única (não usar com múltiplos agentes em paralelo).
- `skills/plan/SKILL.md`: nota sobre `verify_cmd` de build compilado falhar
  por lock de arquivo (`MSB3027`/`EBUSY`) quando um processo do próprio
  projeto-alvo está rodando.

### Alterado
- `config/harness.yaml`: removidas 7 seções órfãs da era congelada
  (`sandbox`/`routing`/`generation`/`eet`/`context`/`telemetry`/`mcp`),
  nunca lidas por `HarnessConfig`. `sandbox/Dockerfile` órfão removido.
- `skills/plan/SKILL.md`: templates de `spec.md`/`Plans.md` extraídos para
  `skills/plan/references/contract-templates.md` (229→154 linhas,
  progressive disclosure).
- `boundary_guard.py`: seção standalone de `render_boundary_guard()` agora
  é gerada via `inspect.getsource()` a partir da versão importável (14
  funções/constantes), eliminando duplicação manual hand-synced. Sem
  mudança de decisão allow/deny.

## 0.16.0 — 2026-07-19

**BREAKING CHANGE:** subcomando `harness run` e `harness.AgentOrchestrator`
removidos — modo de execução autônoma congelado, sem uso no plugin
compilador.

Remoção final da era congelada (3 fases). Fase 0/1 já haviam apagado a
árvore de código (`orchestrator`, `context/`, `routing/`, `telemetry/`,
`tools/`, `verification/`, `governance/sandbox`+`budget`) e o subcomando
`harness run`. Esta fase fecha as pontas soltas de dependências e
documentação.

### Removido
- `pyproject.toml`: dependências `anthropic>=0.40.0`, `mcp>=1.2.0`,
  `docker>=7.0.0` (sem consumidor — a árvore que as usava foi apagada nas
  fases anteriores). `pydantic`/`pyyaml` mantidos.
- `src/harness/config.py`: `SandboxConfig`, `RoutingConfig`, `EETConfig`,
  `ContextConfig`, `GenerationConfig`, `TelemetryConfig`, `MCPConfig`,
  `MCPServerConfig` — existiam só para o modo execução congelado, sem
  nenhum consumidor sobrevivente (confirmado por grep). `HarnessConfig`
  fica só com `governance`/`verification`, os dois campos que o
  compilador/audit realmente usam.
- `README.md`: seção "Modo execução (congelado)" e a menção a
  orchestrator/sandbox na árvore de arquivos.
- `ARCHITECTURE.md`: seção inteira do modo de execução congelado
  (6 camadas: tool orchestration, TDD loop, contexto, guardrails/sandbox,
  telemetria, model routing/EET) — ficou só a descrição do modo
  compilador ativo.

### Corrigido
- `boundary_guard.py`: `_split_shell_segments` agora trata `\n`/`\r` como
  operador de controle — comando Bash com newline embutido não escapa
  mais do matching de prefixo permitido.
- `boundary_guard.py`: `main()` do hook gerado envolve o corpo em
  try/except e emite decisão `deny` explícita em erro interno (antes:
  fail-open — exceção não tratada deixava a tool call passar).
- `verify.py`: `subprocess.TimeoutExpired` do `verify_cmd` agora vira
  `VerifyError` com mensagem de comando+timeout, em vez de traceback cru.
- `compiler.py`, `lifecycle.py`, `teams.py`: `re.sub` com replacement cru
  trocado por `lambda` — conteúdo do usuário com barra invertida (paths
  Windows) não corrompe mais o bloco gerenciado.

## 0.15.8 — 2026-07-18

Sem forma de saber, num repo consumidor (ex.: `elegant-heisenberg`), qual
versão do plugin `harness-creator` compilou os artefatos ali — nem
`settings.json`, nem `.harness/hooks/boundary_guard.py`, nem
`feature_list.json` guardavam isso, e `src/harness/__init__.py::__version__`
estava travado em `"0.1.0"` desde sempre, dessincronizado das outras 3
fontes de versão (`plugin.json`, `marketplace.json`, `pyproject.toml`).

### Adicionado
- `harness.__version__` agora é a fonte única de verdade pra versão em
  runtime (bumpado junto de `plugin.json`/`marketplace.json`/`pyproject.toml`
  a cada release — os quatro precisam concordar).
- `contract.py::compile_contract` grava `compiled_with_version` em
  `.harness/feature_list.json` (ao lado de `contract`/`compiled_at`).
- `compiler.py::compile_project` grava `plugin_version` em
  `.harness/compiled-state.json` (bookkeeping interno do fluxo
  `harness.yaml`, não afeta `settings.json`).
- 2 testes novos (`tests/test_contract.py`, `tests/test_compiler.py`)
  confirmando o stamp em cada fluxo.

## 0.15.7 — 2026-07-18

Corrige 5 pontos de fricção real achados numa sessão de dogfood (harness
rodando sob seu próprio contrato) + fecha um bypass do runtime floor achado
na revisão do plano. Duas rodadas de revisão do plano (reflect/Fable +
llm-as-judge/Opus) e duas do código implementado (mesma dupla), veredito
final: commitar.

### Corrigido
- `boundary_guard.py` + `session_permissions.py`: subcomandos enumerados do
  `harness` CLI (`analyze`, `verify`, `compile-contract`, `compile-session`,
  `compile`, `audit`, `audit-runtime`, `audit-team`, `preflight`, `review`,
  `supervise`, `team`) liberados sob contrato ativo nas duas camadas (hook +
  `settings.json` compilado) — a ferramenta que gera o contrato não ficava
  mais presa no próprio guard que ela gerou. `harness run` fica de fora
  deliberadamente (orquestrador da era congelada, chama a API Anthropic —
  rede fora do floor).
- `boundary_guard.py`: feature-lock devolve mensagem específica pros dois
  caminhos que antes caíam na mensagem genérica de superfície — JSON
  inválido pós-edição e `old_string` não encontrado (`Edit` combinado
  editando várias features de uma vez). Corrigido nas duas cópias
  (importável + standalone do hook instalado).
- `verify.py` + `contract.py`: fecha bypass do runtime floor achado pelo
  llm-as-judge na revisão do plano — liberar `compile-contract`/`verify`
  via Bash tornava `_dry_check_verify_cmd` e `run_verify` alcançáveis com um
  `verify_cmd` malicioso (`curl`/`git push`) escrito pelo próprio agente em
  `.harness/work/**` e auto-aprovado (gate de aprovação é só textual). Fix:
  `is_floor_bash_command` é a primeira ação nos dois, antes de qualquer
  subprocess — provas adversariais (`assert_not_called()`) nos dois
  caminhos + prova end-to-end sem mock.

### Adicionado
- `contract.py` + `cli.py`: `compile-contract --dry-run-verify` roda cada
  `verify_cmd` distinto do contrato com timeout curto (8s) e avisa (stderr,
  nunca bloqueia) quando um comando falha rápido — sinal de erro de
  parse/flag inválida, descoberto antes só depois que um subagente rodava e
  falhava.
- `skills/plan/SKILL.md`: notas de granularidade de tarefa em linguagem
  compilada (C#/.csproj, Java/Maven-Gradle, Go, Rust) e de concorrência em
  `feature_list.json` entre agentes paralelos (fix real fica pra Fase 6 de
  `docs/roadmap-autonomous.md`).

458 testes verdes, ruff limpo. Trade-off aceito e documentado: liberar
`compile-contract` via Bash dá ao agente um primitivo de auto-expansão da
própria superfície de edição (o gate de aprovação é só textual) — o
floor-check acima é o que mantém esse trade-off contido; fix estrutural
real (`approval_hash` verificável por máquina) fica pra Fase 5 de
`docs/roadmap-autonomous.md`.

## 0.15.6 — 2026-07-18

Fix de bug real achado durante implementação no `elegant-heisenberg`
(dogfooding): `harness verify` sempre rodava `verify_cmd` com `cwd` = raiz
do projeto. Num monorepo (`backend/`+`frontend/`), um `verify_cmd` como
`ng test`/`npx playwright test` só resolve o binário de dentro do workspace
do frontend — rodando na raiz, falha com `'ng' não é reconhecido`. Sem
alternativa, a evidência das tarefas de frontend (T-07/T-08/T-09) teve que
ser gravada manualmente chamando `compute_files_hash` direto, fora de
`harness verify`.

### Adicionado
- `Plans.md` aceita campo opcional `cwd` por tarefa (`src/harness/contract.py`
  — `Task.cwd`, `_FIELD_RE`, `parse_plans`): diretório relativo à raiz onde
  `verify_cmd` roda. Propagado para `feature_list.json` e incluído na
  identidade da tarefa — mudar `cwd` invalida `passes:true` preservado na
  recompilação, igual a mudar `files`/`verify_cmd`.
- `src/harness/verify.py::run_verify` — `subprocess.run` usa
  `target_dir / feature["cwd"]` quando declarado (senão `target_dir`,
  comportamento inalterado); `feature_list.json` continua sempre resolvido
  na raiz (`target_dir`), só o `cwd` do comando muda. `cwd` inexistente
  levanta `VerifyError` citando o caminho, antes de tentar rodar o comando.
- 6 testes novos (`tests/test_contract.py`: parse de `cwd` presente/ausente,
  mudança de `cwd` invalida `passes`; `tests/test_verify.py`: `verify_cmd`
  roda no `cwd` declarado, comportamento inalterado sem `cwd`, `cwd`
  inexistente levanta erro claro).

## 0.15.5 — 2026-07-18

Fix de bug real achado durante implementação no `elegant-heisenberg`
(dogfooding): `boundary_guard` negava `Write` de uma migration EF Core nova
(`Migrations/20260718020000_AddTarefaDescricao.cs`) declarada em `files[]`
como diretório (`backend/.../Migrations/`), e teria o mesmo problema com
qualquer glob (`Migrations/*.cs`) apontando pra arquivo ainda inexistente —
`_collect_allowed_files` só expandia glob via `os.walk` do disco, e um
arquivo que o `Write` está prestes a CRIAR nunca existe no disco no momento
em que o hook roda. Autorização pontual foi necessária na sessão-alvo.

### Corrigido
- `src/harness/boundary_guard.py` — `_collect_allowed_files` não faz mais
  disco-walk; devolve `(literais, prefixos_de_diretório, padrões_glob)` e um
  novo `_path_in_surface(path, surface)` casa o path do CANDIDATO
  diretamente contra prefixo/glob, sem depender do arquivo já existir.
  `files[]` com entrada terminada em `/` agora vale como prefixo de
  diretório (qualquer arquivo novo dentro é liberado); glob (`*`/`?`) casa
  contra o candidato sem depender de `os.walk`.
- 2 testes novos em `tests/test_boundary_guard.py` (arquivo novo sob
  diretório declarado; arquivo novo casando glob declarado, ambos ausentes
  do disco no momento da checagem).

## 0.15.4 — 2026-07-17

Fix de gap de usabilidade relatado por outra sessão: com um contrato ativo,
o `boundary_guard` bloqueava `Write`/`Edit` no `spec.md`/`Plans.md` do
PRÓXIMO contrato (`.harness/work/<slug-novo>/`) — a superfície do contrato
corrente só conhece os `files[]` das tarefas ativas, e a área de autoria do
próximo contrato nunca está entre eles. Resultado: planejar a próxima feature
(`/harness-creator:plan`) esbarrava num `deny` da própria ferramenta.

### Corrigido
- `src/harness/boundary_guard.py` — `_evaluate_file` (dentro do script gerado
  por `render_boundary_guard`) passa a liberar incondicionalmente qualquer
  path sob `.harness/work/**`, avaliado DEPOIS do floor de segredo
  (`.env`/`.pem`/`id_rsa`/`credentials` escondidos lá dentro continuam `deny`)
  e ANTES da checagem de superfície do contrato. Autoria de contrato não é
  código sob feature-lock; bloqueá-la era um impasse (não dá pra planejar o
  próximo contrato sem escrever fora da superfície do atual).
- 2 testes novos em `tests/test_boundary_guard.py` (autoria em
  `.harness/work/**` liberada mesmo com contrato ativo; segredo dentro de
  `work/` ainda negado pelo floor).

## 0.15.3 — 2026-07-17

Fix de bug relatado por outra sessão: `harness compile-contract` recusava
`spec.md`/`Plans.md` gerados com BOM UTF-8 (comum em editores/ferramentas no
Windows) — o BOM (`﻿`) ficava colado na primeira linha, quebrando o
match do delimitador de frontmatter (`spec.md`) e do header `## [T-XX]`
(`Plans.md`).

### Corrigido
- `src/harness/contract.py` — `parse_spec`, `parse_plans` e
  `_load_existing_features` trocaram `read_text(encoding="utf-8")` por
  `read_text(encoding="utf-8-sig")`, que descarta o BOM se presente e é
  no-op se ausente.
- 2 testes novos em `tests/test_contract.py` confirmando parse correto de
  `spec.md`/`Plans.md` gravados com BOM.

## 0.15.2 — 2026-07-17

Fix de falso-positivo no `preflight` (achado em dogfooding real no projeto
`elegant-heisenberg`, um repo Angular): `test_files_present` acusava WARNING
("convenção de testes não observada") num repo com 8 arquivos de teste reais
— a stack usa `*.spec.ts` (Jasmine/Karma), e o analyzer só reconhecia
`*.test.ts` (Jest/Vitest) como convenção de teste para JS/TS.

### Corrigido
- `src/harness/analyzer.py` — `_TEST_GLOB_BY_LANGUAGE` (um glob fixo por
  linguagem) virou `_TEST_GLOB_CANDIDATES_BY_LANGUAGE` (lista de candidatos
  em ordem de prioridade). `_detect_test_glob` tenta cada candidato contra o
  disco e usa o primeiro que casar; nenhum casando continua indo para
  `unknowns`, nunca virando fato inventado. JavaScript/TypeScript agora
  tentam `**/*.test.ts` antes de `**/*.spec.ts` (prioridade preservada
  quando os dois existem no mesmo repo). Python/C#/Go inalterados (só um
  candidato cada, sem convenção concorrente conhecida).
- 2 testes novos em `tests/test_analyzer.py` (convenção `*.spec.ts` sozinha;
  prioridade `*.test.ts` quando ambas presentes). Suíte completa: 439 passed,
  10 skipped, zero regressão.

Instalação persistente do plugin sem `--plugin-dir` — necessário para uso
fora do terminal (app **desktop**, que não aceita flags de CLI).

### Adicionado
- `.claude-plugin/marketplace.json` — o próprio repo se auto-registra como
  marketplace de um plugin só (`harness-creator`, `source: "./"`), habilitando
  o registro via `extraKnownMarketplaces` (fonte `directory`) +
  `enabledPlugins` (`harness-creator@harness-creator-local`) em
  `~/.claude/settings.json` do usuário — sem precisar de `--plugin-dir` em
  toda sessão.
- `README.md`/`GUIDE.md` §10 atualizados com a sintaxe real
  (`enabledPlugins`/`extraKnownMarketplaces`) — a seção anterior descrevia uma
  chave `plugins.path` que não existe no schema de settings desta versão do
  Claude Code.

## 0.15.0 — 2026-07-17

Laudo de prontidão de repositório cru: um portão de entrada que roda ANTES de
`analyze`/`plan` e diz se um repo ainda não governado tem o mínimo para o ciclo
Plan→Work→Review funcionar (git para baseline/diff/rollback, manifest para o
analyzer ter fatos, testes para o `verify_cmd`, lint para o quality gate).
100% read-only — não escreve um byte no repo avaliado.

### Adicionado
- `src/harness/preflight.py` — `run_preflight(target_dir)` emite um laudo
  com veredito `READY` / `READY_WITH_WARNINGS` / `NOT_READY` sobre 4
  categorias, cada check não-PASS carregando um **Actionable Fix** concreto:
  - **1. Controle de Versão (Git)** — peça nova (o analyzer ignora `.git` de
    propósito): binário `git` no PATH, `<alvo>/.git` presente, commit de
    baseline (HEAD resolve), working tree limpa e `.gitignore` na raiz. Os
    checks de subprocess usam `git --no-optional-locks -C <alvo> ...`
    (read-only estrito — sem a flag o próprio git reescreveria `.git/index`
    como efeito colateral do `status`); presença de repo decidida por
    `(alvo/.git).exists()`, nunca por `--is-inside-work-tree`, para um mock
    dentro de outro repo não passar de carona.
  - **2. Manifestos de Projeto**, **3. Verificação/TDD** e **4. Qualidade
    Estática/Linting** — camada de política de severidade sobre o
    `RepoProfile` de `analyze_project()` (reuso obrigatório, sem
    reimplementar detecção): `languages` vazio → `manifest_present` FAIL;
    `test_command is None` → `test_runner_detected` FAIL; `test_glob is None`
    → `test_files_present` WARNING; `extras.lint_command` ausente →
    `linter_configured` WARNING. Chamado uma vez, puro, sem `write_profile`.
  - Status da categoria = pior status dos checks (FAIL > WARNING > PASS);
    veredito global `NOT_READY` se ≥1 FAIL, `READY_WITH_WARNINGS` se 0 FAIL e
    ≥1 WARNING, `READY` caso contrário. Todo check não-PASS tem `fix`
    não-vazio (invariante testada).
- `harness preflight --dir <alvo>` na CLI — imprime o laudo como JSON no
  stdout (convenção do repo, igual a `audit`/`analyze`); exit code `0`
  (READY/READY_WITH_WARNINGS), `1` (NOT_READY), `2` (alvo inexistente ou
  não-diretório, mensagem em stderr).
- Skill `/harness-creator:preflight` (`skills/preflight/SKILL.md`) — roda o
  CLI, apresenta o laudo como tabela `[PASS]/[WARNING]/[FAIL]` por categoria
  com o Actionable Fix de cada não-PASS, e roteia pelo veredito: `READY` →
  aponta `/harness-creator:plan`; `NOT_READY` → oferece aplicar os fixes UM A
  UM só com confirmação explícita (a skill nunca aplica fix sozinha) e re-roda
  o preflight.
- 47 testes novos em `tests/test_preflight.py` (AC-1 a AC-9, incluindo o ramo
  FAIL de `git_worktree_clean` sob erro inesperado de subprocess e o caminho
  "gitfile" de `git worktree add`) + E2E real com subprocess
  (`tests/e2e/test_preflight_e2e.py`) e evidência legível colada em
  `tests/e2e/evidence/preflight-dogfood-2026-07-17.md`. Suíte completa verde
  (437 passed, 10 skipped), zero regressão.
- Fix de encoding no CLI: `sys.stdout.reconfigure(encoding="utf-8")` no início
  de `main()` — sem isso, stdout redirecionado/piped no Windows usa a locale
  (cp1252), corrompendo o JSON `ensure_ascii=False` do laudo e crashando com
  `UnicodeEncodeError` em alvos com caminho fora do cp1252 (ex. cirílico/CJK).
  Achado e corrigido por um ciclo de reflect (Opus, effort xhigh) + LLM-as-judge
  (Fable 5, effort xhigh) sobre a implementação já concluída — o mesmo ciclo
  também eliminou um parâmetro morto/armadilha em `_run_git` (não escopava o
  subprocess ao alvo por si só) e fechou os dois gaps de cobertura acima.
- Documentação dedicada: [docs/preflight.md](docs/preflight.md).

## 0.14.1 — 2026-07-16

Correção de segurança no `boundary_guard.py` (o hook `PreToolUse` único que
governa Edit/Write/Bash dentro do raio de impacto de um contrato) — 2 bugs
reais encontrados por auditoria independente (Fable) contra o `ROADMAP.md`,
confirmados por reflect (Opus), corrigidos com TDD e provados em condições
reais (2 dogfood E2E novos, sessão `claude -p` headless de verdade, cobaias
externas), validados de ponta a ponta por uma
segunda rodada independente (Fable + subagentes, reproduzindo do zero).

### Corrigido
- **Command smuggling no guard de Bash** — um comando permitido seguido de
  `&&`/`;`/`|` + comando arbitrário (ex.: `"<verify_cmd> && rm -rf src"`) era
  liberado inteiro: o guard só checava se a sequência permitida aparecia em
  alguma janela contígua dos tokens, não se o comando inteiro era composto
  só de segmentos permitidos. Corrigido: o comando agora é segmentado nos
  operadores de controle de shell, command substitution (`$(...)`/crase) é
  negada de cara, e cada segmento precisa **prefixar** (não mais "aparecer
  em qualquer janela") uma sequência permitida. O runtime floor (`git push`,
  `curl`, `wget`, `npm publish`, `pip upload`, `twine upload`, `gh release`)
  não mudou — continua pegando floor smuggled do jeito que já pegava.
- **feature-lock ignorava `replace_all=true`** — um `Edit` em
  `.harness/feature_list.json` com `replace_all=true` fazia o guard simular
  só a 1ª ocorrência da transição `passes:false → true` (aprovando se ela
  tivesse evidência fresca), mas o Edit real do Claude Code flippava
  **todas** as ocorrências — inclusive features sem evidência ou sem
  aprovação do revisor. Corrigido: o guard agora ramifica em `replace_all` e
  simula a transição completa antes de decidir, nas duas cópias (importável
  e a gerada dentro do hook standalone).

### Adicionado (prova)
- 10 testes novos em `tests/test_boundary_guard.py` provando os dois fixes
  isoladamente (smuggling via `&&`/`;`/`|`/command substitution nas duas
  direções; `replace_all` com features mistas evidência/sem-evidência) —
  suíte completa: 389 passed, 8 skipped, zero regressão.
- Dois testes E2E de dogfood real de segurança (opt-in,
  `HARNESS_E2E_DOGFOOD=1`) — sessão `claude -p` headless real tentando os
  dois ataques em cobaias externas frescas, confirmando `deny` via
  `permission_denials` estruturado **e** prova de disco (arquivo malicioso
  nunca criado, feature sem evidência continua `passes:false`).
- Primeiro dogfood real numa segunda cobaia (`projeto-exemplo-3.0`,
  Python/FastAPI/pytest), provando
  que o harness generaliza além de C#/.NET: gap real corrigido (`GET
  /leaderboard?limit=` sem validação de faixa — SQLite trata `LIMIT`
  negativo como "sem limite").

## 0.14.0 — 2026-07-16

Fase 4 do roadmap (Team-Architecture Factory, Nível L3): de uma sessão só
para um time de agentes com revisão de qualidade independente embutida — o
único toque humano é aprovar a arquitetura do time, uma vez por projeto.
Backlog revisado por plan-critic + judge antes da execução (5 achados reais
corrigidos: precedência da heurística de recomendação, teto duro de
iterações, comparação review-vs-evidência no feature-lock, `on_feature_verified`
acionado de verdade pelo comando `verify`, e o gate de encerramento
redesenhado para usar sessões de revisor genuinamente independentes).

### Adicionado
- `src/harness/teams.py` — catálogo declarativo de 6 padrões de time
  (`teams/patterns/*.yaml`, conteúdo do plugin): `producer-reviewer` e
  `supervisor` com schema completo (papéis + `tools` mínimas — revisor e
  supervisor nunca têm `Edit`/`Write`); `pipeline`, `expert-pool`,
  `fan-out-fan-in`, `hierarchical-delegation` declarativos, sem enforcement
  dedicado nesta fase. `analyze_domain`/`recommend_pattern` (heurística
  determinística e documentada, com ordem de precedência fixa: sinal
  explícito da descrição vence `has_tests`). `generate_team` — entrypoint de
  topo que compõe a geração de `.claude/agents/<papel>.md`,
  `.claude/skills/<papel>/SKILL.md`, o bloco de time em `AGENTS.md` +
  `.harness/TEAM.md` (progressive disclosure) e o manifesto
  `.harness/team/manifest.json`, tudo via substituição por blocos gerenciados
  (idempotente, preserva conteúdo do usuário e os blocos de
  `compiler.py`/`lifecycle.py`).
- `src/harness/review.py` — state machine de revisão do padrão
  Produtor-Revisor: `pending → in_review → rejected|approved`
  (`.harness/review/<feature_id>.json`). Teto duro de iterações
  (`max_review_iterations`, default 3): esgotado, `submit_for_review` recusa
  nova submissão e `record_decision` liga `escalate=True` — o estado
  **nunca** vira `approved` por esgotamento, escala ao humano. Gate de
  justificativa: aprovar uma feature cujos `files[]` tocam o `test_glob`
  exige `justification` não-vazia (defesa da Fase 2 contra reescrever o
  próprio teste, agora também no revisor).
- `src/harness/supervisor.py` — despacho dinâmico: `ready_features`/
  `dispatch_next` respeitam `depends[]` do `feature_list.json` (primeiro
  consumidor real desse campo desde a Fase 1), sem executar nada por conta
  própria (leitor de estado síncrono, não um daemon). `on_feature_verified`
  aciona `submit_for_review` automaticamente quando o time declara
  `producer`+`reviewer`.
- `src/harness/boundary_guard.py` — feature-lock estendido: com
  `.harness/team/manifest.json` declarando os papéis `producer`+`reviewer`,
  `passes: true` exige, além da evidência fresca da Fase 3, aprovação do
  revisor (`status == 'approved'`) mais recente que o último commit **e**
  mais recente que a evidência gravada (aprovação obsoleta em relação a uma
  evidência regravada depois dela → `deny`); diff de teste aprovado sem
  `justification` registrada → `deny`. Sem manifesto (ou sem os dois
  papéis), comportamento idêntico à Fase 3 — zero regressão.
- `src/harness/team_audit.py` — segunda máquina de audit dedicada a
  artefatos de TIME (distinta de `audit.py`/`runtime_audit.py`): papel órfão,
  papel do padrão sem agente gerado, agente com ferramenta além do mínimo do
  catálogo (`reviewer`/`supervisor` nunca deveria ganhar `Edit`/`Write`) e
  drift do bloco gerenciado do agente frente ao catálogo atual. Ausência de
  time compilado é `info`, não penaliza o score.
- `harness team design|generate`, `harness review <id> submit|approve|reject`,
  `harness supervise`, `harness audit-team` na CLI. O subcomando `verify` já
  existente passa a acionar `on_feature_verified` automaticamente após
  gravar evidência com sucesso.
- Skill `/harness-creator:team` — análise de domínio → proposta de padrão →
  **aprovação explícita da arquitetura do time (único toque humano da Fase
  4, uma vez por projeto)** → geração dos artefatos → `harness audit-team`.
- Gate de encerramento: `tests/e2e/test_contract_dogfood.py` ampliado com
  **5 sessões `claude -p` headless reais e independentes** (produtor e
  revisor em processos separados, sem memória entre si, revisor com
  `--disallowedTools Edit,Write`) provando revisão independente de verdade —
  o revisor rejeita um gap real e objetivo (regra de validação aplicada só
  num dos dois validators que o `spec.md` exige), o produtor corrige, o
  revisor aprova só depois — evidência em
  `tests/e2e/evidence/fase4-dogfood-producer-reviewer.md`. Mais 21 testes de
  outcome independentes (`tests/e2e/test_fase4_outcomes.py`), evidência em
  `tests/e2e/evidence/fase4-outcomes-verification.md`.

## 0.13.0 — 2026-07-16

Fase 3 do roadmap (Auto-verificação e Correção em Loop): *"confidence ≠
correctness"* — o agente roda a própria suíte, conserta as próprias falhas e
só declara vitória com prova executável. Backlog revisado por plan-critic +
judge antes da execução.

### Adicionado
- `src/harness/verify.py` — `harness verify <feature-id>`: roda o
  `verify_cmd` da tarefa (vindo do contrato, validado contra o profile);
  sucesso grava `.harness/evidence/<id>.json` (timestamp, comando, hash). É o
  passo 11 do lifecycle ("registra a prova").
- `src/harness/contract.py` — `get_stop_conditions`: expõe as stop conditions
  do `spec.md` como disjuntor do loop de autocorreção (passos 9–10): N falhas
  consecutivas da mesma suíte ou sinal de impossibilidade → o agente para,
  registra o estado no `claude-progress.md` e devolve ao humano com
  diagnóstico.
- `src/harness/boundary_guard.py` — feature-lock: `passes: true` no
  `feature_list.json` só com evidência fresca (`evidence/<id>.json` mais novo
  que o último commit). Edição que marca feature concluída sem evidência
  válida → `deny` com razão ("rode harness verify primeiro"). Mata a
  manipulação de lista de tarefas sem nenhum prompt humano.
- `src/harness/stop_hook.py` — hook `Stop`: feature `in_progress` com
  verificação nunca rodada ou falhando → o encerramento devolve a razão ao
  agente (continua o ciclo ou executa o ritual de handoff dos passos 12–16).
  Redireciona o agente, não interrompe o humano.
- `src/harness/runtime_audit.py` — segunda máquina de audit, distinta do diff
  byte-exato do [audit.py](src/harness/audit.py): audita os artefatos
  runtime-mutáveis (`claude-progress.md`, `feature_list.json`, `evidence/`)
  por schema + frescor + invariantes (1 feature `in_progress`; todo
  `passes:true` com evidência válida).
- `harness verify <feature-id>` e `harness audit-runtime` na CLI.

## 0.12.0 — 2026-07-16

Fase 2 do roadmap (Execução Autônoma no Raio de Impacto): dentro do contrato
já aprovado (Fase 1), o agente passa a trabalhar sem interromper o humano —
o microgerenciamento por `ask`/`deny` por ação dá lugar a uma superfície de
`allow` enumerada e compilada do próprio contrato.

### Adicionado
- `src/harness/session_permissions.py` — compila `.harness/feature_list.json`
  + `.harness/repo-profile.json` para `allow` ENUMERADO (nunca genérico) em
  `.claude/settings.json`: `Edit`/`Write` nos `files[]` de todas as tarefas,
  `Bash` dos `verify_cmd` e extras de lint/build do profile, e o comando de
  instalação de dependências derivado do `package_manager` detectado (ex.:
  `npm ci`) — a instalação roda na aprovação do contrato, não no meio da
  sessão. Git local do ritual (`status/log/diff/add/commit`) fixo. Estado
  gerenciado em `.harness/compiled-state-session.json`, chave
  `managed_session_permissions`.
- `src/harness/boundary_guard.py` — dispatcher único de hook `PreToolUse`
  cobrindo `Edit`/`Write`/`Bash` numa passada só (resolve a latência de N
  subprocessos por tool call do design anterior). Duas garantias, nesta
  ordem, sempre: (1) **runtime floor** avaliado incondicionalmente antes de
  qualquer outra checagem — `git push`, rede/publicação não planejada
  (`curl`, `wget`, `npm publish`, `pip upload`, `twine upload`, `gh
  release`) e escrita em arquivo de segredo (`.env`, `.pem`, `id_rsa`,
  `*credentials*`) nunca viram `allow`, com ou sem contrato ativo; (2)
  **proteção contra enfraquecimento de teste** — arquivo que casa
  `test_glob` só é editável se alguma tarefa do contrato ativo o declarar em
  `files[]`. Remove o hook legado `guard_tests.py` (sempre-`ask` estático)
  quando presente, substituindo-o pela decisão por-tarefa.
- `src/harness/lifecycle.py` — compila o Agent Session Lifecycle de 16
  passos como bloco gerenciado adicional no `AGENTS.md` (progressive
  disclosure, detalhe em `.harness/LIFECYCLE.md`). **[Design próprio]**:
  diverge deliberadamente do texto literal do ROADMAP.md, que descrevia a
  entrega como seções `state`/`lifecycle` no `harness.yaml`; implementado em
  vez disso via bloco em `AGENTS.md` + arquivo de detalhe, sem estender o
  schema do yaml, por ser essencialmente texto/instrução e não configuração.
- `src/harness/templates.py` — gera `claude-progress.md` (esqueleto runtime,
  só se ainda não existir — recompilar nunca sobrescreve progresso já
  registrado) e `init.sh`/`init.ps1` (determinísticos a partir do
  `repo-profile.json`, sempre regenerados).
- `src/harness/session_start.py` — hook `SessionStart` (schema
  `hookSpecificOutput.additionalContext`, confirmado contra a documentação
  oficial, distinto do schema de `PreToolUse`) que injeta no início da
  sessão o resumo do progresso, a feature ativa/pendente e o `git log`
  recente.
- `harness compile-session --dir` na CLI — orquestra os cinco módulos acima
  numa única compilação da sessão de trabalho autônoma.

### Corrigido (achados da revisão plan-critic + judge)
- Bypass do runtime floor sem contrato ativo: uma primeira versão do
  `boundary_guard.py` só aplicava o runtime floor depois de confirmar que
  havia contrato ativo, o que liberaria `git push`/segredos por omissão em
  qualquer repo sem `feature_list.json`. Corrigido — o runtime floor agora
  roda incondicionalmente, antes de qualquer checagem de contrato.
- Colisão de estado com o mecanismo antigo: os novos hooks de sessão
  (`session_permissions.py`, `boundary_guard.py`, `session_start.py`)
  gravavam risco de colidir com `.harness/compiled-state.json`, que
  `compiler.py::_write_state` reconstrói do zero a cada `harness compile` —
  uma chave nova ali seria apagada silenciosamente na próxima compilação do
  mecanismo antigo. Resolvido com arquivo próprio,
  `.harness/compiled-state-session.json`, compartilhado só entre os três
  hooks de sessão, cada um sob sua própria chave.

## 0.11.0 — 2026-07-15

Fase 1 do roadmap (Delegação Baseada em Contratos): move a autoridade humana
de aprovar cada ação para aprovar um único contrato por demanda, antes de
qualquer código.

### Adicionado
- `src/harness/analyzer.py` — análise determinística do repo-alvo (stack,
  comando de teste, lint/build, CI, convenções). Cada achado grava
  `evidence`; o que não foi observado entra em `unknowns[]` — o contrato só
  pode referenciar fatos com evidência.
- `.harness/repo-profile.json` — saída persistida do analyzer, consumida
  pela skill `plan`.
- `src/harness/contract.py` — parseia `spec.md` + `Plans.md` e compila para
  `.harness/feature_list.json` (`{id, desc, files[], verify_cmd, passes}`
  por tarefa). Gate de aprovação: exige `approved_by`/`approved_at`
  preenchidos no frontmatter do `spec.md`; sem isso, `ContractNotApprovedError`.
- `harness analyze --dir` e `harness compile-contract --dir --slug` na CLI.
- Skill `/harness-creator:plan` — entrevista a demanda, apresenta o profile e
  os `unknowns`, escreve o contrato (`spec.md`/`Plans.md`) em
  `.harness/work/<slug>/` e só compila depois da aprovação humana explícita
  (a skill nunca preenche `approved_by`/`approved_at` por conta própria).
- `tests/e2e/test_contract_flow.py` — E2E do fluxo completo
  analyze → spec/Plans → gate de aprovação → compile-contract.
- `tests/e2e/test_contract_dogfood.py` — gate de encerramento da fase: contrato
  aprovado + `claude -p` real implementando uma melhoria genuína numa cobaia
  externa (validação de `Document` só por dígitos), provada por
  `dotnet test` real antes/depois; evidência em
  `tests/e2e/evidence/fase1-dogfood-document-digits.md`.
- `tests/e2e/test_fase1_outcomes.py` — suíte de verificação independente dos
  6 outcomes prometidos pela Fase 1, com evidência acumulada em
  `tests/e2e/evidence/fase1-outcomes-verification.md`.

### Corrigido
- Arnês de verificação independente (`test_fase1_outcomes.py`): o teste do
  fluxo headless da skill `plan` não compilava baseline de permissões
  (`approval_policy: auto`) antes de invocar `claude -p`, então o headless
  negava toda ação `ask` e os outcomes "skill usa o profile"/"skill nunca se
  auto-aprova" ficavam sem veredito; e a fixture de evidência sobrescrevia o
  `.md` inteiro a cada processo pytest separado, apagando vereditos de rodadas
  anteriores. Ambos corrigidos — evidência agora mescla entre execuções e o
  teste headless compila o baseline antes de rodar.

## 0.10.0 — 2026-07-15

Pivot: de executor agêntico próprio para **plugin do Claude Code** que cria,
avalia e compila governança de harness — sem executar tarefas, sem
`ANTHROPIC_API_KEY`.

### Adicionado
- `src/harness/compiler.py` — `.harness/harness.yaml` → `.claude/settings.json`
  (permissions + hooks PreToolUse) + `AGENTS.md` (bloco gerenciado). Reusa
  `_POLICY_MATRIX`/`_ALWAYS_GATED` e `_glob_to_regex` da biblioteca existente.
- `src/harness/audit.py` — score 0-100 + findings via dogfooding (recompila
  em memória e compara com o disco).
- `harness compile --dir` / `harness audit --dir` na CLI.
- Plugin (`.claude-plugin/plugin.json`) com 3 skills:
  `/harness-creator:init|audit|compile`.
- Merge não-destrutivo do `settings.json` (preserva regras/hooks manuais do
  usuário; estado gerenciado em `.harness/compiled-state.json`).
- Suíte de testes em 3 camadas: 77 unit + 8 E2E (cópia real de API .NET via
  subprocess) + 2 headless reais (`claude -p`, opt-in).
- `scripts/make_playground.py` — gera playground reprodutível pra teste
  manual contra API real.

### Corrigido
- `guard_test_runner.py` sobre-bloqueava `test_command` de 2+ palavras (ex.:
  `dotnet test` marcava `dotnet build` também) — trocado por matching de
  sequência consecutiva de tokens.
- `audit.py` só procurava arquivo de teste `.py` (hardcoded) — agora varre
  qualquer extensão respeitando `test_glob`.

### Descoberto e documentado
- `claude -p` (headless) nunca trava numa ação `ask` — nega automaticamente
  e a sessão termina normal (exit 0). O sinal de bloqueio pra scripts é o
  campo `permission_denials` do `--output-format json`, não o exit code.
- Razão específica do hook de TDD não aparece na UI de aprovação do Claude
  Code — visualmente idêntica a um `ask` genérico (achado de UX, não bug).
- Regra `ask` sempre vence `allow` por precedência de bucket, independente
  de especificidade — não dá pra abrir exceção pontual pras próprias skills
  sem afrouxar o gate geral de `Bash`.

### Congelado (referência, fora do produto atual)
- Orquestrador próprio (`orchestrator.py`) + sandbox Docker + TDD loop — a
  versão anterior deste projeto, um executor agêntico completo de 6 camadas.
  Segue no repo, testado, mas fora do caminho principal.

## 0.1.0

Versão inicial: arcabouço de execução agêntica com orquestrador próprio,
sandbox Docker, aprovação HITL, roteamento de modelo e telemetria.
