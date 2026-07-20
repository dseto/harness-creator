# Roadmap — Autonomia Total: da delegação por contrato à execução 100% autônoma (Fases 5–7)

> **Backlog futuro.** Este documento continua o [ROADMAP.md](../project/ROADMAP.md)
> (Fases 1–4, entregues em v0.11.0→v0.14.1) rumo ao objetivo final: o humano
> fornece **uma demanda complexa + critérios de qualidade** e o Claude Code,
> equipado com o harness, executa todo o ciclo — planejar → executar →
> verificar → corrigir — de forma 100% autônoma, por múltiplas sessões, sem
> prompts de aprovação no meio do caminho.
>
> Base: investigação read-only de 2026-07-17 sobre o código v0.14.1 (núcleo
> vivo, era congelada e superfície do plugin, com file:line) + primitivas do
> Claude Code verificadas contra a documentação oficial na mesma data.

---

## Diagnóstico — onde a autonomia trava hoje

O enforcement das Fases 1–4 está sólido (runtime floor, feature-lock, veto do
revisor — tudo por mecanismo, não por instrução). O que falta são três coisas:

1. **O gate de aprovação exige humano** — contrato (`approved_by`/`approved_at`
   no frontmatter) e arquitetura de time são "REGRA DURA" das skills. Pior: o
   gate é enforçado só na compilação ([contract.py](../src/harness/contract.py)
   `compile_contract`); mecanicamente nada impede um agente de preencher o
   frontmatter — pré-contrato o `boundary_guard` libera tudo ("sem contrato
   ativo → allow"). O "a skill nunca se auto-aprova" é instrução, não mecanismo.
2. **Não existe driver de loop** — [supervisor.py](../src/harness/supervisor.py)
   é leitor síncrono deliberado ("não é daemon"); ninguém encadeia
   feature→feature, sessão→sessão, produtor→revisor. Os 5 headless do gate E2E
   da Fase 4 são orquestrados **por pytest** — o orquestrador real só existe
   dentro do teste.
3. **Nenhum sinal é consumido por máquina** — budget é texto advisory; stop
   conditions são strings livres que ninguém conta; `verify` só grava sucesso
   (falha não deixa rastro estruturado); hook Stop é deliberadamente
   não-bloqueante; PostToolUse/SubagentStop/PreCompact/SessionEnd nunca são
   usados.

**Achado central da investigação:** os módulos da era congelada que resolvem o
item 3 — [budget.py](../src/harness/governance/budget.py) (hard stop 500k
tokens/tarefa + 2M/sessão + 120 tool calls), [eet.py](../src/harness/routing/eet.py)
(janela de 10 steps; ≥3 repetições de tool+digest +0.4, ≥3 mesma
failure_signature +0.4, zero progresso +0.3; confiança <0.25 termina, <0.45
escala tier 1×), [tdd_loop.py](../src/harness/verification/tdd_loop.py)
(RED→GREEN→REFACTOR→DONE com `assert_red` exigindo a suíte falhar de verdade e
sha256-freeze dos testes) e [router.py](../src/harness/routing/router.py) —
**não têm dependência dura** (nem Docker, nem `ANTHROPIC_API_KEY`). O que os
prendia à era congelada era o *sinal* que consumiam (usage da própria API,
`made_progress` do próprio loop), não a infraestrutura. Este roadmap é, em
essência, **re-plumbar esses sinais a partir das primitivas nativas do Claude
Code**.

### Primitivas do Claude Code que sustentam o plano (verificadas 2026-07-17)

| Primitiva | Status | Uso neste roadmap |
|---|---|---|
| `--max-budget-usd` (headless) | confirmado | teto duro de custo por sessão, nativo |
| `--resume <session-id>` / `--session-id` / `--max-turns` | confirmado | encadeamento programático de sessões |
| `--output-format json` (custo, `session_id`; `permission_denials`/`num_turns` já provados pelos E2E do repo) | confirmado | ledger de budget + detecção de bloqueio |
| `transcript_path` no stdin de todos os hooks | confirmado | medidor in-session (schema de usage por mensagem não documentado → validar empiricamente) |
| Stop hook bloqueante (exit 2 / `decision:"block"`) | confirmado (o próprio repo verificou contra a doc em 0.13.0) | loop de autocorreção que não deixa a sessão morrer com trabalho não verificado |
| PostToolUse (`additionalContext`/`updatedToolOutput`; **não bloqueia**) | confirmado | coleta de sinais de falha/loop (enforcement fica no PreToolUse/Stop) |
| SubagentStop, SessionEnd | confirmados | gatilhos de revisão/handoff no modo time |
| OTEL (`claude_code.token.usage`, `claude_code.cost.usage`) | confirmado | telemetria contínua |
| `--allowedTools`/`--disallowedTools` | provado empiricamente (revisor E2E usa `--disallowedTools Edit,Write`) | separação de papéis produtor/revisor/juiz |
| PreCompact | existe; capacidade de moldar o resumo **não documentada** | âncora anti-amnésia como advisory declarado |
| Sandbox nativo de Bash | **não roda em Windows nativo** (WSL2 apenas) | isolamento leve = git worktree; pesado = devcontainer opcional |
| API de quota/rate-limit | **não existe** | pacing próprio: ledger + backoff + `--max-sessions` |
| Agent Teams | experimental (`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`) | modo opcional; subagents/headless seguem o caminho estável |

Princípios transversais mantidos: repo = single source of truth (todo estado em
arquivo versionável; sessões frias + SessionStart injection > conversas
longas); progressive disclosure; prova executável como única moeda de
"pronto"; **sem teatro de enforcement** (o que não é enforçável declara-se
advisory). O **Gate de Encerramento por Fase** do ROADMAP.md permanece
obrigatório: toda fase fecha com E2E dogfood na cobaia real, zero regressão
das anteriores + funcionalidade nova provada + evidência em markdown
commitado.

---

## Fase 5 — Aprovação por Máquina com Piso de Segurança

**Objetivo:** eliminar os dois gates humanos duros (contrato e arquitetura de
time) sem afrouxar a fronteira — trocando "humano clica" por "processo
independente decide sob política declarada + piso imutável". A escalação ao
humano vira exceção de política, não rotina.

**Mecânica:**

1. **Risk-tier determinístico do contrato** — `harness contract-risk --slug`
   (novo; zero LLM, molde do `preflight` já contratado em
   `.harness/work/preflight-skill/`): score por checagens objetivas —
   `files[]` ⊆ superfície segura do projeto (nunca CI/infra/`.github`/
   migrations sem tier alto), `verify_cmd` com evidência no profile, teto de
   nº de tasks/files, teste tocado só com `tdd: true` declarado, stop
   conditions estruturadas presentes, zero `unknowns` referenciados, floor
   intocado. Política no `harness.yaml`:
   `contract_policy: {mode: auto|human, auto_approve_max_risk: low, judge: required}`.
2. **Juiz independente** — `harness judge-contract`: spawna `claude -p` FRIO
   (zero contexto do planner — mesmo princípio produtor≠revisor da Fase 4),
   `--disallowedTools Edit,Write`, prompt de crítico de plano, veredito JSON
   schema-validado (approve/reject + findings). O juiz nunca é o processo que
   escreveu o contrato.
3. **Aprovação como ato de processo confiável, não de agente** —
   `harness approve-contract --by "judge:<model>" --verdict <path>`: grava o
   frontmatter + `approval_hash` (sha256 de `spec.md`+`Plans.md` no momento da
   aprovação; conteúdo mudou depois → `compile_contract` invalida). Fecha o
   gap nº 1 por mecanismo: o `boundary_guard` ganha regra **floor-level** —
   Edit/Write de agente em `spec.md`/`Plans.md` que altere frontmatter
   `approved_*` → `deny` SEMPRE, mesmo sem contrato ativo. Hooks interceptam
   só as tools do agente; a CLI roda fora deles → separação real de
   autoridade. Limite honesto declarado: o threat model é drift/negligência,
   não agente malicioso com Bash pré-contrato; `runtime_audit` ganha o
   invariante de assinatura como segunda linha de defesa.
4. **Escalação preservada:** risco acima do teto da política OU juiz rejeita
   2× → único caso que volta ao humano (escalar é feature, não falha).
5. **TDD como máquina de estados, sem Docker** (porta o `tdd_loop.py`):
   tarefa `tdd: true` no `Plans.md` → `harness verify <id> --expect-fail`
   grava `.harness/evidence/<id>.red.json` (exit≠0 + `files_hash` do estado
   red); o **feature-lock passa a exigir o PAR red→green** (red mais antigo
   que green, ambos frescos) para tarefas TDD. `max_green_iterations` (12,
   herdado) vira stop condition estruturada. Red→green volta a ser validado
   por máquina.
6. **Time auto-aprovado:** `team generate --approve-policy auto` aceita
   sozinho quando o padrão ∈ {producer-reviewer, supervisor} (os dois com
   schema `tools` completo) e `harness audit-team` = 100.
7. **Housekeeping (gap nº 10):** reescrever o `AGENTS.md` da raiz (ainda
   descreve a era congelada — TDDGuard/sandbox/ContextManager) e instalar o
   harness no próprio repo (dogfood permanente).

**Entregas no plugin:** `contract-risk` + `judge-contract` +
`approve-contract` na CLI, regra floor de frontmatter no `boundary_guard`,
`--expect-fail` no `verify` + par red→green no feature-lock, política
`contract_policy` no schema do yaml, `--approve-policy` no `team generate`.

**Gate E2E:** demanda real num repo sintético ponta a ponta com **zero toque
humano** (analyze → plan → judge → auto-approve → compile → verify → review →
passes), MAIS prova negativa obrigatória: contrato tier-alto (toca test_glob
sem TDD / floor / arquivo fora da superfície segura) TEM que escalar em vez de
auto-aprovar. Evidência em `tests/e2e/evidence/fase5-*.md`.

---

## Fase 6 — Driver Multi-Sessão, Budget Real e Anti-Amnésia

**Objetivo:** demandas longas atravessam N sessões sem humano: um driver
encadeia sessões frias, o orçamento é medido e enforçado de verdade, e o
disjuntor (stop conditions) conta por máquina.

**Mecânica:**

1. **`harness work [--all|--feature <id>] [--budget-usd X] [--max-sessions N]`**
   — o daemon que o `supervisor.py` deliberadamente não é (o molde JÁ existe
   nos E2E da Fase 4, hoje preso dentro do pytest). Loop:
   `dispatch_next` → monta prompt (feature + lifecycle) →
   `claude -p --output-format json --max-turns M --max-budget-usd <restante>`
   com os settings compilados → coleta o JSON (custo, `permission_denials`,
   `is_error`, `session_id`) → grava `.harness/ledger.json` → roda
   `harness verify` **fora do agente** (nunca confiar em self-report —
   princípio já estabelecido nos E2E) → `on_feature_verified` → sessão
   revisora fria (`--disallowedTools Edit,Write`) → rejected: re-spawna o
   produtor com o feedback (teto do `review.py` já existe); approved → próxima
   feature. **Sessão fria por feature é o default** (contexto vem do repo via
   SessionStart — single source of truth; mais barato e determinístico);
   `--resume <session-id>` reservado para retomar feature interrompida no
   meio.
2. **Budget real em 3 camadas:** por sessão (`--max-budget-usd` nativo), por
   demanda (soma no ledger; estourou → para e escala com relatório em
   `claude-progress.md`), medidor in-session (PostToolUse acumula usage lido
   do `transcript_path` em `.harness/session-usage.json` → warning a 80% via
   `additionalContext`; se o schema do transcript não expuser usage, declarar
   advisory e medir só no driver — sem teatro). O backstop de 120 tool calls
   herdado do `budget.py` vira contador no `boundary_guard`.
3. **Stop conditions compiladas** (fecha o gap nº 5): o frontmatter aceita
   forma tipada — `{type: consecutive_verify_failures, n: 3}`,
   `{type: budget_usd, max: X}`, `{type: wall_clock_minutes}`,
   `{type: impossible_signal}` — compilada para
   `.harness/stop-conditions.json`; **`verify` passa a gravar tentativas
   FALHAS** em `.harness/attempts/<id>.jsonl` (hoje falha não deixa rastro).
   O disjuntor vira contagem por máquina; strings livres continuam aceitas
   como advisory adicional.
4. **Hook Stop bloqueante opt-in** (`compile-session --autonomous`): feature
   in_progress sem evidência + attempts < teto → bloqueia o encerramento com
   razão ("rode verify / corrija e re-rode"); attempts ≥ teto OU stop
   condition batida → deixa parar e grava a escalação. Anti-loop do próprio
   hook: contador de blocks por sessão no `compiled-state-session.json`.
5. **Anti-amnésia nível 2:** handoff enforçado — Stop bloqueia se
   `claude-progress.md` está mais velho que o último edit nos `files[]` da
   feature ativa (os passos 12–16 do lifecycle deixam de ser advisory);
   PreCompact injeta âncora do contrato (feature ativa, attempts, paths) como
   experimento declarado-advisory.
6. **Pacing sem API de quota** (confirmado que não existe): backoff
   exponencial em `is_error`, teto `--max-sessions`, estado 100% em disco →
   `harness work` é retomável de qualquer ponto (kill-safe).

**Entregas no plugin:** `work` na CLI (driver), ledger + attempts + schema de
stop conditions tipadas, modo `--autonomous` do `compile-session` (Stop
bloqueante + handoff gate), medidor PostToolUse, hook PreCompact.

**Gate E2E:** demanda de 3+ features com `depends[]` na cobaia; o driver roda
N sessões reais sem humano; ledger + attempts + evidence + review trail
completos; rodada com teto de budget baixo TEM que parar sozinha e escalar com
relatório legível.

---

## Fase 7 — Early Termination, Telemetria e Delegação Hierárquica

**Objetivo:** reintroduzir a inteligência de corte da era congelada (EET)
sobre sinais nativos, fechar o eixo de observabilidade e destravar os padrões
de time restantes.

**Mecânica:**

1. **EET portado** (o `eet.py` é dependency-free; só re-plumbar sinais):
   - *Sinais no plugin:* o `boundary_guard` (PreToolUse) grava digest sha256
     de (tool+input) em `.harness/eet-window.jsonl` (janela 10, herdada);
     PostToolUse grava `failed`/`failure_signature` (1ª linha do erro, padrão
     herdado); `made_progress` = mudança real de `files_hash` + transições de
     feature — **melhor que a origem** (lá, read nunca contava progresso;
     aqui o sinal é o próprio repo).
   - *Enforcement em 3 alturas:* PreToolUse nega a 4ª chamada idêntica
     consecutiva (limit 3 herdado) com razão; Stop computa o score (pesos
     0.4/0.4/0.3; terminate <0.25, escalate <0.45 — defaults herdados,
     calibráveis no yaml, declarados heurística v0 como na origem) → término
     com relatório em vez de insistência; o driver conta **sessões estéreis**
     (zero transição de feature + zero mudança de hash) — K consecutivas →
     early termination da demanda + escalação.
   - *Escalation de tier* (porta o `router.py`): o driver re-spawna 1× com
     modelo maior (`claude -p --model`, mapa tier→model no yaml; anti
     ping-pong de 1× preservado).
2. **Telemetria:** OTEL nativo ligado por env (token/custo por sessão) +
   ledger/attempts/reviews → `harness stats`: win-rate, custo por feature
   entregue, variância — a métrica A/B da revfactory vira painel contínuo
   (formato JSONL do `tracer.py` reusável).
3. **Delegação hierárquica completa:** schema `tools` nos 4 padrões
   declarativos (pipeline, expert-pool, fan-out-fan-in,
   hierarchical-delegation); `harness work --parallel N` — supervisor real
   despachando M produtores em **git worktrees isolados** (colisão zero;
   funciona em Windows, onde o sandbox nativo não roda), fan-in via merge
   gate (verify da integração antes de consolidar); Agent Teams
   (experimental, env flag) como modo opcional; subagents/headless continuam
   o caminho estável — postura atual do repo, mantida. SubagentStop aciona o
   revisor no modo teams.
4. **Isolamento pesado opcional:** template devcontainer compilado do profile
   (o conceito do `sandbox.py` volta como AMBIENTE do Claude Code via
   WSL2/devcontainer, não como executor próprio). Worktree segue o default
   leve.

**Entregas no plugin:** coleta de sinais EET no guard + PostToolUse, score no
Stop + contagem de sessões estéreis no driver, `--model`/tiers no yaml,
`stats` na CLI, `tools` nos 4 padrões, `--parallel` com worktrees, template
devcontainer.

**Gate E2E:** demanda multi-feature com 2 produtores paralelos + revisor;
feature-armadilha (impossível de propósito) plantada — prova que o EET **para
sozinho**, escala com relatório e não queima o budget; zero regressão das
Fases 1–6.

---

## Riscos declarados (decidir na implementação)

- **Latência de hooks:** o EET adiciona I/O por tool call — manter tudo no
  dispatcher único (append JSONL leve, sem subprocess extra); medir no gate
  E2E.
- **Precedência `ask` > `allow`** (achado documentado do repo): não tentar
  abrir exceções pontuais via allow; superfícies novas entram só pelo
  compilador.
- **Schema de hooks/CLI do Claude Code muda:** os schemas usados já são
  verificados contra a doc no código (padrão do repo); adicionar teste de
  contrato de schema no CI dos E2E.
- **Fadiga inversa (autonomia demais):** o runtime floor NUNCA vira allow —
  git push/segredos/publicação continuam fora do alcance mesmo em modo 100%
  autônomo; release segue humano (*"PR ready is not release ready"*).
- **PreCompact/usage-no-transcript não documentados:** entram como advisory
  declarado até prova empírica (sem teatro de enforcement).

## Resumo

| Fase | Paradigma que instala | Mecanismos-chave | Contato humano |
|---|---|---|---|
| 5. Aprovação por Máquina | gate humano → política + juiz frio + CLI confiável | `contract-risk`, `judge-contract`, `approve-contract` + `approval_hash`, floor de frontmatter, par red→green | só se risco > teto ou juiz rejeitar 2× |
| 6. Driver Multi-Sessão | sessões frias encadeadas por driver; budget e disjuntor por máquina | `harness work`, ledger, attempts, stop conditions tipadas, Stop bloqueante opt-in, handoff gate | só se stop condition/budget disparar |
| 7. EET + Hierarquia | corte por heurística sobre sinais nativos; times paralelos | eet-window, sessões estéreis, `stats`, `--parallel` + worktrees, devcontainer opcional | só escalação do EET + aceite de release |

## Sequência recomendada

`preflight` (contrato já redigido em `.harness/work/preflight-skill/`,
aguardando aprovação) → **Fase 5** (itens 1–5 destravam tudo; housekeeping
junto) → **Fase 6** (driver primeiro, budget depois, Stop-block por último) →
**Fase 7**. Cada fase: backlog via plan-to-backlog + gate E2E dogfood como
último subagente, ampliando o da fase anterior — regra permanente do projeto
preservada.
