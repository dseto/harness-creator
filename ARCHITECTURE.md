# harness-creator — Arquitetura

> **Fórmula de 2026:** `Agente = Modelo + Harness`.
> O modelo fornece o raciocínio; o harness garante execução confiável, segurança e governança.

## Pivot (2026-07): modo plugin — compilar governança, não executar

O produto atual é um **plugin do Claude Code** que cria/avalia/compila
estrutura de harness. A execução fica com o próprio Claude Code:

- **`src/harness/compiler.py`** — `.harness/harness.yaml` → `.claude/settings.json`
  (permissions + hooks PreToolUse), `.harness/hooks/*.py` (guards standalone,
  só stdlib, com o regex do test_glob embutido) e bloco gerenciado no
  `AGENTS.md` do projeto-alvo. Fontes de verdade reusadas, não duplicadas:
  `_POLICY_MATRIX`/`_ALWAYS_GATED` (Camada 4) e `_glob_to_regex` (Camada 2).
- **`src/harness/audit.py`** — score 0-100 + findings estruturados;
  dogfooding: recompila em memória e compara com o disco (drift).
- **Skills** — `/harness-creator:init|audit|compile`.
- **Budget de tokens** — o Claude Code não expõe usage a hooks; compila para
  orientação no AGENTS.md, explicitamente advisory.
- **Merge não-destrutivo** — settings.json: entradas gerenciadas registradas
  em `.harness/compiled-state.json`; recompilar troca só o que é do harness,
  preservando regras/hooks manuais do usuário.

**Tudo abaixo desta seção descreve o modo de EXECUÇÃO (orquestrador próprio +
sandbox Docker), que está CONGELADO como referência** — funcional e testado,
mas exige `ANTHROPIC_API_KEY` e não é o caminho do produto.

---

## Visão Geral (modo execução, congelado)

O `harness-init` é um arcabouço (framework de execução) que envolve um LLM de fronteira
com **6 camadas operacionais** de controle. Nenhuma ação do modelo toca o mundo real
sem atravessar as camadas de governança.

```
┌─────────────────────────────────────────────────────────────────┐
│                      AgentOrchestrator                          │
│              (loop agêntico: perceive → plan → act)             │
├──────────────┬──────────────┬───────────────┬───────────────────┤
│  L6 Routing  │ L3 Contexto  │  L2 TDD Loop  │  L5 Telemetria    │
│  ModelRouter │ ContextMgr   │  TDDCycle     │  ExecutionTracer  │
│  EETEvaluator│ CodeIndexer  │  (Red-Green-  │  (JSONL spans,    │
│              │ AGENTS.md    │   Refactor)   │   tokens, ROI)    │
├──────────────┴──────────────┴───────────────┴───────────────────┤
│  L1 Tool Orchestration                                          │
│  ToolRegistry ── MCPClient (Model Context Protocol)             │
│               └─ TerminalTool (recuperação dinâmica de erros)   │
├─────────────────────────────────────────────────────────────────┤
│  L4 Guardrails & Governança                                     │
│  ApprovalPolicy (HITL) ─ TokenBudget ─ SandboxEnvironment       │
│                                        (Docker, network=none)   │
└─────────────────────────────────────────────────────────────────┘
```

## Camada 1 — Orquestração de Ferramentas (`src/harness/tools/`)

- **`ToolRegistry`**: catálogo único de ferramentas com JSON Schema. Ferramentas
  nativas e ferramentas MCP são indistinguíveis para o modelo.
- **`MCPClient`**: cliente do **Model Context Protocol**. Conecta a servidores MCP
  via stdio ou SSE, descobre ferramentas dinamicamente (`tools/list`) e as registra
  no `ToolRegistry` com namespace (`mcp__<server>__<tool>`).
- **`TerminalTool`**: execução de comandos **sempre dentro do sandbox** (nunca no
  host). Retorna resultado estruturado (`exit_code`, `stdout`, `stderr`,
  `recovery_hints`). Em falha, o harness injeta o stderr + dicas de recuperação
  de volta no contexto do modelo, forçando o ciclo de autocorreção.
- **`read_file`/`write_file`**: ferramentas discretas de arquivo, à parte de
  `run_terminal` — existem para que `risk_class` reflita o poder real da ação
  (leitura nunca gateada, escrita gateada em `paranoid`/`balanced`). Bloqueiam
  path traversal (`ToolExecutionError` se o caminho resolver fora do workspace).
- **Limitação conhecida de MCP**: servidores MCP stdio rodam como subprocesso
  **no host**, fora do isolamento do sandbox sem rede. Por isso ficam
  **desligados por default** (`mcp.allow_host_execution: false`); toda
  ferramenta MCP é sempre `risk_class="network"`, gateada em qualquer modo,
  inclusive `auto`. Habilitar é decisão explícita de quem opera o harness.

## Camada 2 — Loop de Verificação Contínua / TDD (`src/harness/verification/`)

- **`TDDCycle`** é uma **máquina de estados obrigatória**: `RED → GREEN → REFACTOR`.
  - **RED**: o agente escreve o teste; o harness executa e **exige falha**. Teste
    que já passa é rejeitado (teste vazio/tautológico).
  - **GREEN**: o agente implementa. O harness roda a suíte no sandbox, captura
    stack traces e os devolve ao modelo até tudo passar (com limite de iterações).
  - **REFACTOR**: melhorias com a suíte verde como invariante.
- **Guardrail anti-regressão estrutural**: no início da fase GREEN os arquivos de
  teste são *hashados*. Qualquer edição em teste durante GREEN é **bloqueada**
  (impede o agente de "passar no teste" apagando o teste).
- **`TDDGuard` — TDD é obrigatório de verdade, não opt-in.** Um hook de
  pré-dispatch (`AgentOrchestrator._execute_tool`) intercepta **toda** chamada
  de ferramenta antes do gate HITL e bloqueia os dois atalhos que contornariam
  a máquina de estados: (1) rodar a suíte de teste direto via `run_terminal`
  em vez de `tdd_try_green`/`tdd_assert_still_green`; (2) editar um arquivo de
  teste protegido (`write_file`) durante `GREEN`/`REFACTOR` sem antes chamar
  `tdd_request_test_edit` (ferramenta com `risk_class="edit_test"`, **sempre**
  gateada, em qualquer política, inclusive `auto`). O re-hash de uma edição
  aprovada só acontece **depois** da escrita real (não no momento da
  aprovação) — re-hashear antes capturaria o conteúdo antigo e não protegeria
  nada contra o que acabou de ser escrito. Desligável via
  `verification.enforce_tdd: false` (saída de emergência, não recomendado).

## Camada 3 — Contexto e Memória Persistente (`src/harness/context/`)

- **`ContextManager`**: elimina a "amnésia do agente".
  1. Lê `AGENTS.md` / `CLAUDE.md` na raiz do repo (diretrizes de governança e
     arquitetura) e injeta em **toda** sessão como contexto imutável.
  2. **`CodeIndexer`**: índice leve de símbolos/arquivos do repositório (interface
     pronta para trocar por embeddings/tree-sitter).
  3. **Memória de sessão** persistida em `.harness/memory/` (fatos, decisões,
     estado de tarefas), recarregada em sessões futuras.

## Camada 4 — Guardrails, Sandbox e Governança (`src/harness/governance/`)

- **`SandboxEnvironment`**: contêiner Docker **efêmero** por tarefa.
  - `network_mode="none"` por padrão (mitiga exfiltração e *confused deputy*).
  - Limites de CPU/memória/pids; workspace montado com escopo mínimo.
  - Destruído ao fim da tarefa (`__exit__`), sem estado residual.
- **`ApprovalPolicy` (HITL)** — decide por `risk_class` (`read | edit | execute
  | network | edit_test`), nunca por heurística sobre o nome da ferramenta.
  `run_terminal` é `execute` porque um shell arbitrário pode editar arquivos
  (`echo > file`) tão bem quanto uma ferramenta de edição dedicada — por isso
  `execute` fica no mesmo balde de risco que `edit` em todo modo que não seja
  `auto`. `network` e `edit_test` são **sempre** gateados, mesmo em `auto`.
  Três modos configuráveis:
  | Modo | Uso | Comportamento |
  |---|---|---|
  | `paranoid` | produção | aprova **literalmente tudo**, inclusive leituras |
  | `balanced` | protótipos | aprova tudo que muda estado: `edit`/`execute`/`network` |
  | `auto` | exploração | aprovação automática, exceto `network`/`edit_test` (sempre gateados) |
- **`TokenBudget`**: teto rígido de tokens por tarefa e por sessão. Estourou →
  `BudgetExceededError` → o orquestrador encerra o loop (mata *runaway loops*).
  Contrato: **1 `AgentOrchestrator` por tarefa** — o orquestrador não é
  reutilizável entre tarefas (o `ToolRegistry` e o `MCPClient` internos não
  reinicializam). Para o teto de **sessão** acumular de verdade entre
  tarefas, quem lança múltiplas tarefas (ex.: um TaskManager de cockpit) cria
  **um único** `TokenBudget` e injeta via `session_budget=` no construtor de
  cada `AgentOrchestrator` novo.

## Camada 5 — Observabilidade e Telemetria (`src/harness/telemetry/`)

- **`ExecutionTracer`**: log estruturado JSONL em `.harness/traces/`.
  - Cada evento: timestamp, `trace_id`, `span_id`, tipo, tokens in/out, custo
    estimado, snapshot de estado do ambiente e o raciocínio completo do modelo.
  - Exportador de métricas de ROI: custo total por tarefa → base para
    **"Custo por PR Mesclado"**.

## Camada 6 — Model Routing e EET (`src/harness/routing/`)

- **`ModelRouter`**: classifica a tarefa (`trivial | simple | standard | complex`)
  e roteia:
  - navegação de arquivos, pequenas edições → modelo pequeno/barato (ex: Haiku);
  - coordenação e raciocínio arquitetural → modelo de fronteira (ex: Opus).
  - Mapa `tier → model_id` é 100% configurável em `config/harness.yaml`.
  - **Escalonamento acionado de verdade**: quando a confiança do `EETEvaluator`
    cai abaixo de `eet.escalate_confidence_threshold` (soft, default `0.45`)
    mas ainda acima do limiar duro de terminação (`eet.confidence_threshold`,
    default `0.25`), o `_agent_loop` chama `router.escalate(decision)` — no
    máximo uma vez por tarefa, para não alternar (ping-pong) entre tiers.
- **`EETEvaluator`** (*Experience-Driven Early Termination*) — **placeholder
  estrutural**: interface `score(trajectory) → confidence` + `should_terminate()`.
  Detecta sinais de trajetória degenerada (repetição de ações, ausência de
  progresso, mesma falha N vezes) e interrompe cedo, evitando gasto de API em
  tarefas impossíveis. Implementação futura: modelo aprendido sobre trajetórias
  históricas do `ExecutionTracer`.

## Fluxo de uma Tarefa

```
task ──▶ ContextManager.build()          # AGENTS.md + índice + memória
     ──▶ ModelRouter.route(task)         # escolhe modelo por complexidade
     ──▶ loop:
           TokenBudget.enforce()         # teto rígido
           EETEvaluator.evaluate()       # corte precoce ou escalonamento de tier
           model.generate(context)
           ├─ tool_call?
           │    TDDGuard.check_pre_dispatch()  # bloqueia atalhos de TDD
           │    ApprovalPolicy.gate()          # HITL
           │    ToolRegistry.dispatch()        # sandbox / read_file / write_file / MCP
           │    Tracer.record(result)
           │    (falha? → stderr volta ao contexto → autocorreção)
           └─ done? → tdd_finish() → fim
```

## Decisões de Projeto

1. **Sandbox é a única via de execução.** `TerminalTool` não tem caminho de
   execução no host — impossível "esquecer" o isolamento.
2. **TDD como máquina de estados, não como convenção.** O harness rejeita
   transições ilegais (implementar antes do teste falhar).
3. **Telemetria é síncrona ao loop.** Todo turn gera evento; ROI é derivado,
   nunca instrumentado depois.
4. **EET desacoplado do orquestrador** via interface — trocar heurística por
   modelo aprendido não toca o loop principal.
