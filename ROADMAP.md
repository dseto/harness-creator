# Roadmap — Automação de Codificação por Contrato: de governança por interrupção a delegação autônoma

> **Pivô 2026-07-15.** Este documento substitui o roadmap anterior, que evoluía
> o plugin acumulando bloqueios duros (hooks `ask`/`deny` por ação) — um design
> que a própria revisão de coerência condenou: latência de subprocess por tool
> call, interrupções constantes e fadiga de aprovação que termina com o usuário
> desligando os hooks (harness vira decoração). O novo alvo é **Automação de
> Codificação com Mínima Interferência Humana**: microgerenciamento de ações dá
> lugar a **Delegação Baseada em Contratos e Times Autônomos**.
>
> Base estrita: três projetos de referência, verificados diretamente nos repos
> em 2026-07-15 — [Chachamaru127/claude-code-harness](https://github.com/Chachamaru127/claude-code-harness)
> (ciclo Plan→Work→Review com contrato aprovado), [walkinglabs/learn-harness-engineering](https://github.com/walkinglabs/learn-harness-engineering)
> (5 subsistemas + Agent Session Lifecycle autônomo) e
> [revfactory/harness](https://github.com/revfactory/harness)
> (Team-Architecture Factory L3, padrões Produtor-Revisor e Supervisor).
>
> Validado por revisão independente (agent Fable, esforço máximo,
> 2026-07-15) contra as três fontes lidas no raw: veredito "coerente com
> ressalvas". As 5 correções apontadas — citação real do `/harness-work` +
> runtime floor, colisão rede×init, superfície de comandos enumerada,
> proteção contra enfraquecimento de testes, enforcement do veto do revisor —
> estão aplicadas nesta versão.

---

## A falha arquitetônica que este pivô corrige

O paradigma anterior era **governança por interceptação**: cada Edit/Write/Bash
atravessava guards Python que decidiam `allow`/`ask`/`deny`. Isso é *prompt
engineering com interrupções* — o humano continua no caminho crítico de cada
ação, só que mediado por scripts.

A distinção que muda o design inteiro:

| Decisão de hook | Quem ela interrompe | Papel no novo design |
|---|---|---|
| `ask` | **o humano** (prompt de aprovação) | Reduzida a **um único gate**: aprovação do contrato na fase Plan |
| `deny` com razão | **o agente** (recebe a razão e se autocorrige — humano nem vê) | Mantida **só na fronteira do contrato**: feedback máquina-a-máquina |
| `allow` | ninguém | **O padrão dentro do raio de impacto aprovado** |

O insight dos três projetos de referência é o mesmo: confiabilidade não vem de
vigiar cada ação, vem de **(1) um contrato explícito aprovado uma vez, (2) um
ciclo de vida de sessão que o agente executa sozinho, (3) prova executável
como única moeda de "pronto", e (4) revisão feita por outro agente, não pelo
humano**. O humano *"review, not rescue"* (learn-harness-engineering).

### Pontos de contato humano — antes e depois

| Momento | Roadmap anterior | Este roadmap |
|---|---|---|
| Análise do repo | confirma entrevista | confirma `unknowns` do profile (1× por repo) |
| Planejamento | aprova plano | **aprova/corrige `spec.md` + `Plans.md` — o único gate obrigatório por demanda** |
| Cada edição de arquivo | `ask` (política balanced) | nada — `allow` dentro do raio |
| Cada comando/teste | `ask` | nada — agente roda a própria suíte |
| Teste falhou | humano vê prompt | agente entra em loop de autocorreção |
| Fim de tarefa | humano confere | Produtor-Revisor: outro agente dá o veredito |
| Release/merge | humano | humano (deliberadamente mantido — *"PR ready is not release ready"*) |

**Duas interações humanas por demanda** (aprovar contrato; aceitar release) —
contra dezenas de prompts por sessão no design anterior. Por **projeto**
somam-se dois toques amortizados de setup, fora do fluxo de demanda:
confirmar os `unknowns` do profile (1× por repo) e aprovar a arquitetura do
time (1× na criação, Fase 4).

### Arquitetura-alvo

```
/harness-creator:plan          humano aprova (ÚNICO gate)
  repo-profile + demanda  ──►  spec.md + Plans.md  ──►  contrato COMPILA para:
                                                          • feature_list.json (escopo)
                                                          • permissions da sessão (allow no raio)
                                                          • AGENTS.md (lifecycle de 16 passos)
                                        │
                                        ▼
                     Agent Session Lifecycle (autônomo, sem humano)
                     ler estado → escolher 1 feature → implementar
                        → verificar → autocorrigir até prova passar
                        → registrar evidência → commit seguro → handoff
                                        │
                                        ▼
                     Time autônomo (F4): Supervisor distribui,
                     Produtor implementa, Revisor veta/aprova em loop
                                        │
                                        ▼
                     humano: aceita release (2º e último toque)
```

---

## Fase 1 — Delegação Baseada em Contratos

**Objetivo:** acabar com o microgerenciamento movendo TODA a autoridade humana
para um artefato: o contrato `spec.md` + `Plans.md`, aprovado antes de
qualquer código. Depois disso, pedir permissão vira exceção, não rotina.

**Mecânica (o que controla o comportamento):**
- `.harness/repo-profile.json` — análise determinística do repo
  (`src/harness/analyzer.py`, novo): stack, comando real de teste, lint/build,
  CI, convenções. Cada achado com `evidence`; o não-observado entra em
  `unknowns[]` — o contrato só pode referenciar fatos com evidência (gate de
  investigação do claude-code-harness: *"dados não observados permanecem
  incógnitas, não viram fatos"*).
- `/harness-creator:plan` (skill nova, molde `/harness-plan`) — recebe a
  demanda em linguagem natural, lê o profile e escreve:
  - **`spec.md`** — o *quê*: escopo, critérios de aceitação executáveis,
    unknowns, **stop conditions** (quando o agente deve parar e devolver ao
    humano em vez de insistir);
  - **`Plans.md`** — o *como*: sequência de tarefas, dependências, **arquivos
    afetados por tarefa** (nasce aqui o raio de impacto da Fase 2) e a
    validação exigida de cada uma.
- **Gate único:** humano aprova ou corrige o contrato (frontmatter
  `approved_by`/`approved_at`). Sem aprovação, nada compila.
- Na aprovação, o contrato **compila** (mesmo eixo `render()` do
  [compiler.py](src/harness/compiler.py)) para `feature_list.json` —
  `{id, desc, files[], verify_cmd, passes:false}` por tarefa — o formato que o
  lifecycle da Fase 2 consome.

**Entregas no plugin:** `analyzer.py`, skill `plan`, template de contrato,
`harness compile-contract` (Plans.md → feature_list.json), testes com repos
sintéticos.

**Valor:** o humano passa de aprovador-de-ações a **assinante de contrato** —
interação concentrada onde ela tem mais alavancagem (errar na spec custa uma
fração de errar no diff), e o resto do sistema ganha uma fonte de verdade
legível por máquina.

---

## Fase 2 — Execução Autônoma no "Raio de Impacto"

**Objetivo:** dentro do contrato aprovado, o agente trabalha sem interromper
o humano — como o `/harness-work` da referência, que executa a tarefa
aprovada e *"keeps work inside the plan"* (citação real do README — a versão
anterior deste documento colocava "sem permissões intermediárias" entre
aspas como se fosse da fonte; era paráfrase, corrigido). A própria fonte
mantém um **runtime floor** mesmo no modo autônomo: leitura de segredos,
envio externo e operações destrutivas **não planejados** continuam parando em
`ask`, e `git push` exige confirmação. Isso valida o desenho abaixo:
autonomia ampla *dentro* do contrato, piso de segurança imutável fora dele.
Os bloqueios duros do design anterior são **removidos dinamicamente** pela
compilação do próprio contrato.

**Mecânica:**
- **Permissions compiladas do contrato, por sessão de trabalho:** aprovação
  do plano recompila `.claude/settings.json` com `allow` para a **superfície
  completa que o lifecycle usa — enumerada, não implícita** (qualquer passo
  do ciclo que caísse no prompt default do Claude Code quebraria o
  zero-prompts na prática):
  - Edit/Write nos `files[]` da(s) tarefa(s) do plano;
  - comandos de verificação/build/lint do profile (`verify_cmd`, suíte,
    health check do `init`) e `harness verify`;
  - git local do ritual — `git status/log/diff/add/commit` (os passos 5 e 15
    do lifecycle; sem isso o handoff trava ou prompta);
  - rede: **instalação de dependências roda na aprovação do contrato**
    (dentro do toque humano 1, via `init` completo), não no meio da sessão —
    resolve a colisão entre "rede gateada" e o passo 2 do lifecycle.
    Complemento opcional: allows de rede **com evidência do profile** (ex.:
    `Bash(npm ci)` quando há lockfile detectado).
  - **Runtime floor — nunca vira `allow`, alinhado à fonte 1:** segredos,
    envio externo/destrutivo não planejado e `git push` (push pertence ao
    toque de release, não à sessão autônoma).

  Desfazer o contrato (release ou abandono) recompila de volta ao estado
  conservador — o merge não-destrutivo via `compiled-state.json` que o plugin
  já faz hoje é exatamente o mecanismo necessário.
- **Um único guard de fronteira** (`boundary_guard.py`, dispatcher único por
  evento PreToolUse — resolve a latência de N subprocessos), cobrindo
  Edit/Write **e Bash**: ação fora da superfície enumerada acima → **`deny`
  com razão** (*"arquivo fora do contrato da tarefa 1.2; replaneje via
  /harness-creator:plan se o escopo mudou"*). O deny volta para o **agente**,
  que se autocorrige ou replaneja — o humano não é interrompido, e comando
  desconhecido nunca cai no prompt default.
- **Proteção contra enfraquecimento de testes** (substitui o `edit_test`
  sempre-gateado do design anterior sem reabrir prompts humanos): arquivo de
  teste só é editável se a tarefa ativa **declarar testes no escopo**
  (`files[]` do `Plans.md` incluindo o teste, ou tarefa marcada TDD); teste
  fora do escopo declarado → `deny`. Todo diff em teste fica marcado para
  **revisão obrigatória do agente revisor** (Fase 4). Motivo: a fonte 1 é
  explícita — falha não se resolve *"enfraquecendo, pulando ou afrouxando a
  expectativa do teste"*; sem esta regra, o `allow` de Edit no raio deixaria
  o agente afrouxar o teste para o `verify_cmd` passar sem detecção.
- **Agent Session Lifecycle compilado nas Instruções:** o bloco gerenciado do
  AGENTS.md passa a conter o ciclo de 16 passos da referência como manual
  operacional (progressive disclosure: AGENTS.md fino aponta para skills
  locais geradas):
  1. ler AGENTS.md → 2. rodar `init.sh`/`init.ps1` (gerado do profile:
  deps, health check) → 3. ler `claude-progress.md` → 4. ler
  `feature_list.json` → 5. checar `git log` → 6. **escolher exatamente UMA
  feature pendente** → 7–11. implementar e verificar (Fase 3) → 12–16.
  atualizar progresso, marcar feature, documentar o quebrado, commit apenas
  em estado retomável, deixar caminho limpo.
- Hook **SessionStart** injeta o estado (resumo do progress + feature ativa +
  git log) — a sessão nasce sabendo onde parou, sem o humano recontar
  contexto.

**Entregas no plugin:** compilação contrato→permissions, `boundary_guard.py`
dispatcher, seções `state`/`lifecycle` no yaml, templates
`claude-progress.md` + `init.*`, hook SessionStart.

**Valor:** elimina a fadiga de aprovação **sem abrir mão da fronteira** — a
autonomia é literalmente do tamanho do contrato. Latência cai (1 dispatcher em
vez de N guards). O agente deixa de ser interrogado e passa a ser **auditado
pelo próprio sistema**.

---

## Fase 3 — Auto-verificação e Correção em Loop

**Objetivo:** *"confidence ≠ correctness"* — o agente roda a própria suíte,
conserta as próprias falhas e só declara vitória com prova executável. O
humano não vê nenhuma falha intermediária; vê o resultado verificado.

**Mecânica:**
- `harness verify <feature-id>` — roda o `verify_cmd` da tarefa (vindo do
  contrato, validado contra o profile); sucesso grava
  `.harness/evidence/<id>.json` (timestamp, comando, hash). É o passo 11 do
  lifecycle ("registra a prova").
- **Loop de autocorreção (passos 9–10):** verificação falhou → a instrução
  compilada manda corrigir e re-rodar — sem envolver o humano. As **stop
  conditions do `spec.md`** são o disjuntor: N falhas consecutivas da mesma
  suíte ou sinal de impossibilidade → o agente para, registra o estado no
  `claude-progress.md` e devolve ao humano com diagnóstico (única situação em
  que a Fase 3 escala para uma pessoa — por design do contrato, não por
  prompt de permissão).
- `passes: true` no `feature_list.json` **só com evidência fresca**: o
  boundary guard da Fase 2 cobre também este arquivo — edição que marca
  feature concluída sem `evidence/<id>.json` mais novo que o último commit →
  `deny` com razão (feedback ao agente: *"rode harness verify primeiro"*).
  Mata a manipulação de lista de tarefas sem nenhum prompt humano.
- Hook **Stop** fecha o loop da sessão: feature `in_progress` com verificação
  nunca rodada ou falhando → o encerramento devolve a razão ao agente
  (continua o ciclo ou executa o ritual de handoff dos passos 12–16). De novo:
  redireciona o **agente**, não interrompe o humano.
- Auditoria dos artefatos vivos (`claude-progress.md`, `feature_list.json`,
  `evidence/`): schema + frescor + invariantes (1 feature in_progress; todo
  `passes:true` com evidência válida) — mecanismo distinto do diff byte-exato
  que o [audit.py](src/harness/audit.py) aplica aos artefatos compilados, que
  permanece para settings/hooks/blocos gerenciados.

**Entregas no plugin:** `harness verify`, formato de evidência, regra de
feature-lock no boundary guard, hook Stop, segunda máquina de audit
(schema/frescor/invariantes).

**Valor:** o gap número 1 da literatura ("declarar vitória cedo") é fechado
por um mecanismo que **nunca toca o humano** — toda a pressão de qualidade é
feedback máquina-a-máquina dentro do loop do agente.

---

## Fase 4 — Team-Architecture Factory (Nível L3)

**Objetivo:** remover o humano também da revisão. O plugin vira uma fábrica
que desenha, para o domínio do projeto, um **time de agentes** com revisão de
qualidade independente embutida — o padrão da revfactory/harness.

**Mecânica (workflow de geração em 6 fases, molde da referência):**
1. **Análise de domínio** — repo-profile + descrição em linguagem natural;
2. **Design da arquitetura do time** — seleção do padrão e do modo de
   execução (Agent Teams com fila de mensagens nativa como default — recurso
   **experimental** do Claude Code, dependência de disponibilidade declarada;
   Subagents como alternativa estável e fallback);
3. **Geração dos agentes** — `.claude/agents/<papel>.md` (role,
   responsabilidades, ferramentas mínimas do papel);
4. **Geração das skills** do time — `.claude/skills/<capacidade>/SKILL.md`
   com progressive disclosure;
5. **Integração e orquestração** — template de orquestrador conectando os
   papéis;
6. **Validação** — dry-run, verificação de triggers entre agentes.

**Padrões priorizados neste roadmap (dois primeiros a implementar):**
- **Produtor-Revisor** — automatiza o code review: o produtor termina uma
  tarefa do `feature_list.json` → o revisor é acionado automaticamente pela
  orquestração, valida contra os critérios do `spec.md` + evidência da
  Fase 3 → problema encontrado devolve feedback e **re-dispara o produtor**;
  loop até aprovação **ou limite de 2–3 iterações** (a fonte exige o limite
  para evitar loop infinito). Divergência declarada da fonte: o veredito lá é
  `PASS | FIX | REDO` com **PASS forçado** ao estourar o limite; este roadmap
  adota um state machine **[design próprio]** `pending → in_review →
  rejected|approved` e é deliberadamente **mais estrito** — estourar o limite
  NÃO força aprovação, escala ao humano via stop condition do contrato.
  **Enforcement do veto (não só instrução):** o feature-lock da Fase 3 é
  estendido — em tarefa com revisão obrigatória, `passes:true` exige
  evidência fresca **e** estado `approved` do revisor; major finding bloqueia
  o `done` por mecanismo. Diffs de teste têm gate adicional do revisor
  (proteção da Fase 2): aprovar mudança de teste exige justificativa de por
  que a expectativa mudou.
- **Supervisor** — automatiza a distribuição: um agente central pega o
  `feature_list.json` do contrato aprovado e despacha tarefas
  dinamicamente para produtores (respeitando dependências do `Plans.md`),
  monitora conclusão e aciona o par revisor de cada entrega. `/harness-work
  all` da referência, generalizado para N workers.
- Os outros quatro padrões do catálogo (Pipeline, Expert Pool, Fan-out/Fan-in,
  Delegação Hierárquica) entram como templates declarativos no catálogo
  (`teams/patterns/*.yaml`), selecionáveis pelo mesmo workflow — a fábrica
  recomenda com justificativa e o humano confirma a arquitetura **uma vez**,
  na criação do time (não a cada uso).
- **Escopo vs. a referência atual:** a revfactory evoluiu o workflow para 8
  fases (Phase 0: auditoria do estado atual; Phase 7: evolução contínua do
  harness). Este roadmap segue o molde de 6 do README — a Phase 0 já é
  coberta pelo `harness audit` existente do plugin; a Phase 7 (evolução do
  time gerado) fica **declaradamente fora de escopo** desta versão.
- **Handoff sem humano:** contratos de comunicação entre papéis são o próprio
  estado tipado (`feature_list.json` + status JSON + evidência) — nenhuma
  aprovação humana entre produtor e revisor.
- **Validação da fábrica** no método da referência: experimento A/B
  (tarefas com/sem harness; win rate, quality score, variância de output —
  a referência reporta +60% de qualidade e 100% de win rate em n=15,
  medição do autor). A suíte headless que o repo já domina
  (`claude -p` + `permission_denials`) vira o teste de regressão
  determinístico; o A/B é a métrica de produto.

**Entregas no plugin:** `src/harness/teams.py`, catálogo de padrões, skill
`/harness-creator:team`, templates de orquestrador/produtor/revisor/
supervisor, audit de time (papel órfão, revisor com ferramentas além do
papel, drift do bloco gerenciado dos agentes).

**Valor:** o ciclo inteiro — distribuir, implementar, verificar, revisar,
consolidar — roda entre agentes. Sobram para o humano exatamente os dois
toques do contrato: **aprovar o plano e aceitar o release**.

---

## Gate de Encerramento por Fase — E2E Dogfood com Evidência

**Nenhuma fase (1–4) é considerada concluída só por `pytest tests -q` verde em
repos sintéticos `tmp_path`.** Cada fase fecha com um teste E2E real, opt-in
(mesmo padrão de custo/skip de `tests/e2e/test_headless.py`), rodado numa
**cópia fresca de `C:\Projetos\MinimumAPI`** (a cobaia real que o repo já usa
via `tests/e2e/conftest.py`), que prova duas coisas ao mesmo tempo — nunca só
uma:

1. **Zero regressão** — tudo que as fases anteriores entregaram continua
   funcionando na mesma cobaia: se a Fase 2 compila `boundary_guard.py`, o
   teste da Fase 2 tem que provar de novo, na prática, que o fluxo de
   contrato da Fase 1 (analyze→spec/Plans→compile-contract) ainda compila e
   ainda gera `feature_list.json` correto, além de provar a novidade da
   própria Fase 2.
2. **Nova funcionalidade de verdade** — a capacidade que a fase entrega
   resolve um caso real (não um cenário de brinquedo em `tmp_path`): uma
   melhoria genuína identificada por leitura do código real da cobaia,
   implementada e verificada com o comando de teste real do projeto
   (`dotnet test`), nunca por asserção sobre o texto que o agente disse.

**Evidência gravada em arquivo, não só verde no terminal.** Cada teste E2E de
fechamento grava um relatório em `tests/e2e/evidence/<fase>-dogfood-<slug>.md`
(commitado no repo, histórico auditável) contendo, no mínimo: comandos
executados, resultado da suíte real *antes* e *depois* da mudança (prova de
regressão), diff do(s) arquivo(s) tocado(s), e o resumo da execução do agente
real (`is_error`, `permission_denials` se aplicável). O humano abre esse
arquivo para conferir — o teste passar não é o suficiente, o objetivo é dar
ao humano algo legível para checar sem precisar reler código de teste.

**Molde:** [SUBAGENTE 08] do backlog da Fase 1
(`ROADMAP-fase1.backlog.md`) — cópia real, gap real (`Document` sem checagem
de dígitos em `CustomerValidators.cs`), TDD real (vermelho antes, verde
depois), contrato pré-aprovado tocando só o arquivo de produção, `claude -p`
headless real, prova por `dotnet test` real rodado de novo fora do agente,
evidência em markdown. Todo backlog gerado para as Fases 2–4 (via
`plan-to-backlog`) tem que incluir um subagente equivalente como último bloco,
sequencial, opt-in, e que amplia o teste E2E da fase anterior em vez de
recomeçar do zero — cada fase soma prova sobre a da anterior.

---

## Fundamentos preservados do roadmap anterior

Três achados da revisão de coerência continuam valendo e estão absorvidos:

1. **Duas classes de artefato, dois audits:** compilado-determinístico
   (settings, hooks, blocos gerenciados, agentes) → diff byte-exato existente;
   runtime-mutável (`claude-progress.md`, `feature_list.json`, `evidence/`,
   contrato) → schema + frescor + invariantes (novo, Fase 3).
2. **Dispatcher único por evento de hook** — nunca N subprocessos por tool
   call; a latência era sintoma do design por interceptação e cai junto
   com ele.
3. **Sem teatro de enforcement** — o que não é enforçável nativamente é
   advisory declarado. O relaxamento de permissions da Fase 2 é real
   (compilação de `allow` a partir do contrato), não promessa: usa o merge
   gerenciado que o compilador já executa hoje.

## Resumo

| Fase | Paradigma que instala | Arquivos/fluxos que controlam o comportamento | Contato humano | Depende de |
|---|---|---|---|---|
| 1. Delegação por Contratos | autoridade humana concentrada num artefato aprovável | `repo-profile.json`, `spec.md`, `Plans.md`, `feature_list.json` | aprova contrato (único gate) | — |
| 2. Autonomia no Raio de Impacto | allow na superfície enumerada do contrato (inclui git local e deps no toque 1); deny-como-feedback na fronteira; runtime floor imutável; lifecycle autônomo | permissions compiladas, `boundary_guard.py`, AGENTS.md (16 passos), `claude-progress.md`, `init.*`, SessionStart | nenhum durante execução (piso: segredos/destrutivo/push nunca viram allow) | F1 |
| 3. Auto-verificação em Loop | prova executável como moeda de "pronto"; autocorreção até passar | `harness verify`, `evidence/`, feature-lock, hook Stop, stop conditions do spec | só se stop condition disparar | F1 + F2 |
| 4. Team Factory L3 | revisão e distribuição por agentes; humano só assina e aceita | `.claude/agents/*.md`, catálogo de padrões, estado `pending→in_review→rejected\|approved` [design próprio; fonte usa PASS/FIX/REDO], veto ligado ao feature-lock | aprova arquitetura do time (1×) + aceita release | F1–F3 |

Toda fase fecha com o **Gate de Encerramento E2E Dogfood** (seção acima):
cobaia real (`MinimumAPI`), zero regressão das fases anteriores + nova
funcionalidade real provada, evidência em markdown para conferência humana.
