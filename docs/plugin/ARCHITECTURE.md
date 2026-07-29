# harness-creator — Arquitetura

> **Fórmula:** `Agente = Modelo + Harness`.
> O modelo fornece o raciocínio; o harness garante execução confiável,
> segurança e governança.

**v0.27.0** · versão navegável e interativa deste documento:
[`arquitetura-visual.html`](arquitetura-visual.html) (abre offline, com
diagramas clicáveis e um simulador da cascata de decisão do
`boundary_guard`).

---

## 1. A decisão fundadora: compilar, não executar

O produto é um **plugin do Claude Code** que cria, avalia e compila estrutura
de harness. A execução fica com o próprio Claude Code.

O desenho anterior — abandonado no pivot de 2026-07 — era um orquestrador
próprio: chamava a API, rodava o modelo em contêiner e aplicava política no
meio. Custava infraestrutura, chave de API, Docker e uma segunda
implementação de tudo que o host já faz.

O desenho atual não tem executor, não tem credencial e não tem runtime
paralelo:

```
.harness/harness.yaml  ──harness compile──►  .claude/settings.local.json  (permissions + hooks)
      (a spec)                               .harness/hooks/*.py          (guards standalone)
                                             AGENTS.md                    (blocos gerenciados)
```

A consequência que importa: o enforcement roda **no mesmo processo que faz as
tool calls**. Não existe caminho por fora.

### Três leis transversais

1. **O repositório é a fonte da verdade.** Todo estado vive em arquivo.
   Sessão fria + injeção no `SessionStart` vence conversa longa — contexto que
   só existe no chat some no primeiro compact.
2. **Prova executável é a única moeda de "pronto".** Não é uma afirmação do
   agente; é um `exit_code == 0` gravado com timestamp e hash do conteúdo
   verificado.
3. **O harness deve barrar o mínimo.** Um `deny` difícil demais empurra o
   operador para o kill-switch, e o kill-switch é desproteção total. Toda
   mensagem de recusa carrega o escape sancionado.

E um princípio que amarra os três: **sem teatro de enforcement**. O que não é
enforçável é declarado advisory. O orçamento de tokens, por exemplo, vira
orientação no `AGENTS.md` com a frase explícita de que o Claude Code não expõe
contagem de tokens a hooks.

---

## 2. Camadas

| Camada | Módulos | Responsabilidade | O que ela NÃO faz |
|---|---|---|---|
| **0 · Host** | Claude Code | Executa: lê `permissions`, dispara hooks, carrega skills e subagentes | — |
| **1a · Skills** | `skills/` (7) | Conduz a conversa com o humano | Não escreve nada direto — toda escrita passa pela CLI |
| **1b · CLI** | `cli.py` | Dispatch dos 19 subcomandos, validação de `--dir` | Não decide `allow`/`deny` em runtime |
| **2 · Compiladores** | `compiler`, `contract`, `analyzer`, `session_permissions`, `lifecycle`, `templates`, `branching`, `profile_edit`, `install_command` | Transformam entrada humana em artefato. Determinísticos, zero LLM, zero rede | Não rodam no caminho da tool call |
| **3 · Enforcement** | `boundary_guard`, `guard_tests`, `guard_test_runner`, `session_start`, `stop_hook` | Decidem `allow`/`ask`/`deny` a cada tool call | Não importam a biblioteca — stdlib puro |
| **4 · Prova e controle** | `verify`, `review`, `supervisor`, `teams`, `finish` | Produzem e consomem evidência; ordenam o trabalho | Nenhum chama git de escrita |
| **5 · Diagnóstico** | `preflight`, `audit`, `runtime_audit`, `team_audit`, `doctor`, `metrics` | Emitem laudo + o comando exato de correção | Nunca corrigem sozinhos |
| **Base** | `config`, `governance/approval`, `patterns`, `settings_paths`, `hook_launcher`, `killswitch` | Cada um é fonte **única** de uma verdade | — |

### Por que a camada 3 é stdlib puro

Os hooks rodam num processo separado, lançado pelo Claude Code, **fora do
pacote instalado**. Um `import harness` ali quebraria assim que o venv mudasse.
Por isso o compilador **embute o código-fonte** dos guards — inclusive o regex
derivado do `test_glob` e o trecho que lê o contrato — em arquivos
autocontidos.

### Fonte única, nunca tabela duplicada

A duplicação de tabela entre camadas é exatamente o bug que este desenho
existe para prevenir:

- `_POLICY_MATRIX` / `_ALWAYS_GATED` (`governance/approval.py`) — quais classes
  de risco cada modo gateia. O `compiler` importa, não recria.
- `_glob_to_regex` (`patterns.py`) — matching de arquivo de teste, compartilhado
  por compiler, analyzer, audit e pelos guards gerados.
- `is_floor_bash_command` / `is_floor_secret_path` (`boundary_guard.py`) —
  importados por `session_permissions.py`, para as duas camadas nunca
  divergirem sobre o que é floor.
- `DISABLED_CHECK_SRC` (`killswitch.py`) — o snippet `_harness_disabled()`
  embutido literalmente por cada render de hook.
- `hook_command()` (`hook_launcher.py`) — o único ponto que monta o `command`
  gravado em settings.

---

## 3. A falha aberta, e como ela foi fechada

É o achado de arquitetura mais importante do projeto, porque o modo de falha
era **silencioso e no sentido inseguro**.

Os hooks eram registrados como `python "<script>"` — interpretador **nu**,
resolvido pelo PATH do shell que executa o hook, no instante da tool call. Se
`python` não resolvesse ali (venv desativado, PATH divergente, ou o stub da
Microsoft Store no Windows, que sai com 9009), o processo morria **antes** de o
script rodar.

E a documentação do Claude Code é explícita: apenas `exit 2` bloqueia; qualquer
outro código não-zero é erro **não-bloqueante** e a execução continua.

> Interpretador irresolúvel ⇒ a tool call passa sem runtime floor, sem proteção
> de segredo, sem bloqueio de push, sem gate de evidência. **O guard falha
> aberto**, e a única pista é uma linha de `hook error` no transcript.

A correção não cabia no script: o `boundary_guard` gerado já é fail-closed por
dentro (qualquer exceção durante a avaliação vira `deny`), mas não há como
fechar de dentro do Python o caso em que o Python nunca inicia. A única
superfície de correção é o comando registrado:

```
"<interpretador absoluto>" "<script>" || exit 2
```

O caminho absoluto vem do `sys.executable` que rodou o `compile-session`. O
sufixo `|| exit 2` é sintaxe comum a `sh` e a `cmd.exe`, então o mesmo string
funciona nos dois shells que o Claude Code pode usar — sem gerar arquivo de
lançador, que teria o problema simétrico (`.cmd` não roda sob `sh`, `.sh` não
roda sob `cmd.exe`).

`harness doctor` diagnostica o resíduo desse problema: hook registrado cujo
interpretador não existe mais.

---

## 4. O `boundary_guard`: um hook, uma cascata

`boundary_guard.py` substitui o padrão de N guards por ação (um hook por
matcher) por **um único** hook `PreToolUse`, resolvendo a latência de N
subprocessos por tool call.

### Roteamento explícito

O matcher registrado é `"*"`, não `"Edit|Write|Bash"`. Com o matcher restrito,
qualquer tool de escrita fora daquele conjunto (`PowerShell`, `NotebookEdit`,
tools MCP de filesystem) **nunca invocava o hook** — o Claude Code aplicava o
allow implícito antes de o fallback do `main()` sequer rodar.

Alargar o matcher sozinho não bastaria; por isso `main()` roteia
explicitamente:

| Tool | Rota |
|---|---|
| `Edit`, `Write` | `_evaluate_file` (+ caso especial de feature-lock em `feature_list.json`) |
| `MultiEdit` | `_evaluate_file` sobre `tool_input.file_path`, sem o caso especial |
| `NotebookEdit` | `_evaluate_file` sobre `notebook_path`, com fallback para `file_path` |
| `PowerShell` | `_evaluate_powershell` |
| `Bash` | `_evaluate_bash` |
| `Read`, `Glob`, `Grep`, `Task`, `WebFetch`, `TodoWrite` | allowlist fixa read-only/utilitária — passa sem análise |
| qualquer outra | nome com cara de escrita (`write`/`create`/`edit`) → `deny`; resto → **allow logado** |

**Risco residual assumido, por escrito:** uma tool MCP de escrita cujo nome não
contenha `write`/`create`/`edit` (ex.: `mcp__foo__persist`) passa sem análise.
Aceitável no contexto de deploy single-user interno deste plugin; se o conjunto
de MCP servers conectados mudar para incluir ferramentas de terceiros não
confiáveis, esta política mínima deve ser revista.

### A ordem da cascata é a segurança

```
0 · kill-switch      sentinel presente → allow e encerra (precede TUDO, inclusive o floor)
1 · runtime floor    push / rede / segredo / plano de controle / auto-desativação
2 · superfícies      .harness/work · .harness/scratch · progress.md · docs/ · memória do Claude
3 · contrato         ausente → deny (escrita) / bootstrap mínimo (comando); concluído → allow
4 · raio de impacto  test_glob protegido; files[] do contrato ativo
```

**Por que o floor vem antes de tudo.** Se "sem contrato → allow" fosse avaliado
primeiro, qualquer repositório sem `feature_list.json` teria push, rede e
escrita em segredo liberados. Era uma falha real de segurança. O floor é
avaliado primeiro, sem exceção, com ou sem contrato ativo.

**A única exceção do floor** é estreita: `git push` da branch do contrato ativo
(`contract/<slug>`) para ela mesma, com `-u`/`--set-upstream`. Branch protegida,
outra branch, branch indeterminada (detached HEAD, worktree linkado — postura
fail-**closed** aqui), refspec explícito, `--force`/`--mirror`/`--delete` e push
encadeado a outro comando seguem negados.

### Ancoragem da raiz

O guard não confia no `cwd` do payload — ele se ancora no próprio `__file__`,
que mora sempre em `<repo>/.harness/hooks/`. Um agente que fez `cd frontend/` e
não voltou não desloca a raiz sob a qual a superfície é avaliada. Um
`file_path` **relativo**, porém, é absolutizado contra o `cwd` original do
payload antes da checagem — senão a âncora produziria falso-deny.

### Limites declarados, não esquecidos

- **Floor de segredo** cobre redirecionamento (`>`, `>>`, `tee`) e cmdlets de
  escrita do PowerShell. **Não** persegue escrita indireta via interpretador
  (`python -c "open('.env','w')"`): é corrida armamentista de custo
  desproporcional para este mecanismo.
- Ofuscação do alvo do redirecionamento por concatenação de aspas adjacentes
  (`echo x > ".e"nv`) ou ANSI-C quoting escapa pelo mesmo motivo.
- **Floor de segredo é de escrita, não de leitura.** `cat .env` é liberado —
  ler `.env.example` é rotina — com um AVISO anexado à razão, porque o conteúdo
  entra no contexto da sessão. Repositório que não pode nem ser lido é política
  de permissions (`paranoid`), não de floor.

---

## 5. O contrato como único ponto de autoridade

### Os dois portões, antes do contrato

O ciclo tem duas avaliações read-only que precedem qualquer escrita, e é útil
não confundi-las — uma julga o **repositório**, a outra a **demanda**:

| | `preflight` | `assess` |
|---|---|---|
| Avalia | o repositório está pronto para o harness? | esta demanda é executável aqui? |
| Roda | uma vez por projeto, antes do `init` | uma vez por demanda, antes do `plan` |
| Fontes | git, manifesto, runner de teste, linter | código, docs, git, `.harness/work/` |
| Veredito | `READY` / `READY_WITH_WARNINGS` / `NOT_READY` | `COERENTE` / `PRECISA_ESCLARECER` / `CONFLITANTE` / `FORA_DE_ESCOPO` |
| Bloqueia? | `NOT_READY` | só `FORA_DE_ESCOPO` |
| Implementação | Python (`preflight.py`) — determinístico | prompt (`skills/assess/`) — semântico |

A assimetria de implementação é deliberada. Prontidão de repositório é
verificável por checagem objetiva; aderência de demanda não é. Um `files[]`
apontando arquivo inexistente é normal (arquivo novo); um `verify_cmd` que
falha é normal (TDD). **Todo sinal estático disponível é indistinguível do caso
legítimo** — daí o `assess` ser julgamento, não parser, e daí a Fase 5 propor
um juiz semântico para o contrato em vez de mais validação.

`assess` **não substitui o gate humano** — é insumo para ele. `COERENTE`
significa "não achei impedimento nas quatro dimensões", nunca "deve ser feito".

### O contrato

Toda autoridade humana se concentra em **um** artefato aprovável: o par
`spec.md` (o quê — escopo, critérios executáveis, `stop_conditions`) +
`Plans.md` (o como — tarefas, `files[]`, `verify:`).

```
.harness/work/<slug>/spec.md     frontmatter: slug, approved_by, approved_at, stop_conditions
.harness/work/<slug>/Plans.md    ## [T-01] descrição / - files: ... / - verify: ...
        │
        ▼  harness compile-contract --slug <slug>
.harness/feature_list.json       id, desc, files[], verify_cmd, depends[], cwd, passes
```

**O gate é enforçado no código, não por instrução.** `compile_contract` levanta
exceção e **não escreve um byte** se `approved_by`/`approved_at` estiverem
vazios.

Cuidado na recompilação: `passes: true` só é preservado se a **identidade** da
tarefa não mudou — a tripla (`id`, `verify_cmd`, `files`). Mudar só a descrição
não invalida evidência já registrada; mudar arquivos ou comando de verificação
invalida, porque a evidência antiga não prova mais nada sobre o novo escopo.

### Feature-lock

Marcar `passes: true` exige, para **cada** feature transicionada, evidência
válida em `.harness/evidence/<contrato>/<id>.json` com `recorded_at` **mais novo
que `git log -1 --format=%cI`**. Vale inclusive para `replace_all`: o guard
simula a transição completa, então uma feature sem evidência não pega carona
numa edição em massa.

Com time `producer`+`reviewer` compilado, o lock **aperta**: exige também
aprovação do revisor mais recente que a evidência. Aprovação obsoleta frente a
uma evidência regravada depois dela → `deny`.

---

## 6. Fronteira machine-local

**Política canônica, uma frase:** *especificação, contrato e prova são
versionados; saída de compilação que carrega dado de máquina é machine-local e
regenerada por `compile`.* A íntegra é a **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md` — fonte
canônica; quando qualquer documento divergir dela, ela vence.

Todo output que o harness mescla em settings carrega dado desta máquina: o
comando de hook leva path **absoluto** (o `cmd.exe` não expande `$VAR`) e a
superfície de sessão enumera arquivos do contrato ativo. Por isso o destino é
`.claude/settings.local.json`, que o Claude Code já lê com precedência sobre o
`settings.json` do time.

Antes desta fronteira o merge caía no `settings.json`, que os projetos-alvo
commitam: **um clone em outro path recebia um `PreToolUse` apontando para um
diretório inexistente — o repositório parecia governado e nenhum guard rodava.**

Duas garantias, ambas idempotentes e não-destrutivas:

1. `prepare_managed_settings` é o **único** ponto por onde os cinco escritores
   (`compiler`, `boundary_guard`, `session_start`, `stop_hook`,
   `session_permissions`) resolvem o arquivo — a troca de destino não pode ficar
   pela metade em um deles.
2. `ensure_machine_local_gitignores` escreve as regras em arquivos
   **tool-owned** (`.claude/.gitignore`, `.harness/.gitignore`), nunca no
   `.gitignore` da raiz do usuário.

**Trade-off aceito:** um clone novo **não nasce governado**. É exatamente o que
`harness doctor` existe para acusar.

### Estratégia de merge

Nunca sobrescrever o que o usuário tem. As entradas gerenciadas ficam
registradas em `.harness/compiled-state.json` (mecanismo antigo, reconstruído do
zero a cada `harness compile`) e `.harness/compiled-state-session.json`
(compartilhado pelos hooks de sessão, cada um sob sua própria chave, sempre
preservando as alheias). Recompilar remove as entradas antigas gerenciadas e
insere as novas, preservando regra e hook manuais.

---

## 7. Fluxo de dados de ponta a ponta

```
repositório ──preflight──► READY? ──► analyze ──► repo-profile.json ─┐
                                                                     ├─► session_permissions ──► settings.local.json
harness.yaml ──compile──► permissions                                │                              │
             │            guard_tests                                │                              ▼
             │            AGENTS.md                                  │                     boundary_guard.py
             │                                                       │                     guard_tests.py
demanda ──assess──► laudo ──► spec + Plans ──compile-contract──► feature_list.json ───────┤ session_start.py
   (4 fontes)   FORA_DE_ESCOPO      ▲                                │                     stop_hook.py
                     barra          │                                │                              │
                                GATE HUMANO                          │                              ▼
                             (approved_by/at)                        │                     decisão allow/deny
                                                                     │                     por tool call
                                                                     ▼
                                                      verify ──► evidence/<contrato>/<id>.json
                                                                     │
                                                                     ▼
                                       feature-lock  ·  review  ·  supervise  ·  finish
```

Os dois pontos onde o fluxo pode parar antes de qualquer escrita são os
portões: `preflight` com `NOT_READY` e `assess` com `FORA_DE_ESCOPO`. Todo o
resto ou segue, ou para no gate humano do contrato.

---

## 8. Diagnóstico: quatro laudos, nenhum conserta sozinho

| Comando | Mecanismo | Detecta |
|---|---|---|
| `preflight` | 4 categorias sobre o repo **cru**, read-only | Falta de git, manifest, runner de teste ou linter — antes de instalar |
| `audit` | **Dogfooding**: recompila em memória e faz diff byte-exato contra o disco | Drift de artefato compilado editado à mão |
| `audit-runtime` | Schema + frescor + invariantes | `passes:true` sem evidência, 2+ features em progresso, `progress.md` ausente |
| `audit-team` | Catálogo vs. artefatos gerados | Papel órfão, papel sem agente, revisor com `Edit`/`Write` |
| `doctor` | Compara as 3 camadas de distribuição | Versão dessincronizada, compilação ausente, hook que não roda |

O `audit` não reimplementa as regras do compilador — ele **é** o compilador,
rodado em memória. Regra nova no `compiler.render()` passa a ser auditada de
graça, e nunca há duas definições de "certo".

`audit`, `audit-runtime` e `audit-team` saem com código **1** se houver qualquer
finding `critical`, ou se o score cair abaixo de 60. A regra de exit ficou
explícita depois de um caso real: UM `critical` custa 40 pontos, deixava o score
em exatamente 60, e o comando saía 0 — um repositório sem harness nenhum passava
por qualquer gate de CI que olhasse o exit code.

---

## 9. Kill-switch: o paradoxo e sua resolução

Estado = arquivo-sentinela `.harness/harness.disabled` (machine-local,
gitignored). Presente, cada hook gerado faz no-op no topo do `main()`.

**Invariante de segurança:** o agente dentro do Claude Code **não pode se
auto-desativar** — enquanto o harness está ativo, o `boundary_guard` tem uma
regra de nível *floor* que nega criar o sentinel e rodar `harness disable`. O
usuário, no terminal próprio, não passa por hook nenhum. Sem paradoxo: a
checagem do kill-switch precede o floor, e o floor anti-auto-desativação só roda
enquanto o harness está **ativo**.

É por isso que `enable`/`disable` ficam **fora** de `_HARNESS_SUBCOMMANDS` no
guard — e é a mesma razão de `harness finish` nunca chamar git: um subcomando na
allowlist do agente que faça ação irreversível vira bypass do floor.

**O risco que sobra é operacional.** Um kill-switch ligado é invisível na
sessão; o guard já ficou em no-op por quatro dias sem sinal. Só `harness status`
conta a verdade, e `harness finish` trata `killswitch_active` como bloqueador de
fecho.

---

## 10. Estado atual e limites conhecidos

**Fases 1–4 entregues** (v0.11 → v0.26) e em uso: o projeto se governa com o
próprio harness — os contratos em `.harness/work/` deste repositório são o
histórico real de uso.

**Fases 5–7 são backlog documentado** (`docs/roadmap-autonomous.md`). O
diagnóstico honesto de onde a autonomia ainda trava:

1. **O gate de aprovação exige humano.** É enforçado só na compilação;
   mecanicamente nada impede um agente de preencher o frontmatter — pré-contrato
   o guard libera comando. *"A skill nunca se auto-aprova" é instrução, não
   mecanismo.* A Fase 5 fecha por mecanismo: risk-tier determinístico, juiz
   independente em processo frio, `approval_hash` e regra de floor sobre
   `approved_*`.
2. **Não existe driver de loop.** `supervisor.py` é leitor síncrono deliberado;
   ninguém encadeia feature→feature, sessão→sessão. O orquestrador real só
   existe hoje dentro do teste E2E.
3. **Nenhum sinal é consumido por máquina.** Orçamento é advisory; stop
   conditions são strings que ninguém conta; `verify` só grava sucesso — falha
   não deixa rastro estruturado.

**Achado central da investigação:** os módulos que resolveriam o item 3 não têm
dependência dura de Docker nem de chave de API. O que os prendia à era congelada
era o *sinal* que consumiam, não a infraestrutura. As Fases 5–7 são, em essência,
re-plumbar esses sinais a partir de primitivas nativas do Claude Code —
`--max-budget-usd`, `--resume`, `--output-format json`, Stop bloqueante,
PostToolUse, SubagentStop.

---

## Referências

- [README.md](../../README.md) — o que o plugin é, CLI completa, instalação
- [GUIDE.md](GUIDE.md) — referência do dia a dia, seção por seção
- [TUTORIAL.md](TUTORIAL.md) — do zero à demanda implementada, com exemplos reais
- [arquitetura-visual.html](arquitetura-visual.html) — esta arquitetura em
  diagramas interativos
- [docs/preflight.md](../preflight.md) — detalhe do portão de entrada
- [docs/roadmap-autonomous.md](../roadmap-autonomous.md) — Fases 5–7
- [CHANGELOG.md](../reference/CHANGELOG.md) — histórico de versões
