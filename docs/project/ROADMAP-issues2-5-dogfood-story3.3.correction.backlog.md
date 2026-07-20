# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Correção da fricção relatada nos issues #2-#5 (dogfood real da v0.17.0/0.17.1,
# implementação da Story 3.3 em `elegant-heisenberg` via /harness-creator:plan).
# Achados registrados no handoff `HANDOFF-2026-07-20-v0.17-dogfood-story-3.3.md`
# e abertos individualmente no GitHub. Nenhum destes 4 é núcleo de segurança
# (diferente do backlog do issue #1) — são ergonomia/doc/design de borda.
#
# Alvo de código principal: `src/harness/cli.py`, `src/harness/contract.py`,
# `skills/plan/references/contract-templates.md`, `skills/plan/SKILL.md`.
# Investigação (item 4): docs oficiais de hooks/permissions do Claude Code +
# teste empírico.
#
# Validação global ao fechar CADA item: `$env:PYTHONPATH = "src"; python -m
# pytest tests -q` 100% verde, sem regressão de contagem (baseline 514).
#
# Ordem: item 4 primeiro (investigação decide se vira fix real ou só nota);
# itens 2 e 5 são triviais e independentes, fazer em qualquer ordem; item 3 é
# decisão de design já tomada aqui (fix doc-only, ver rejeitados).
#
# Nenhum item é breaking change → bump de versão 0.17.1 → 0.17.2 ao fechar.

---

## Item 1 (issue #4) — Investigar drift de `permissions.allow` após `task add-file`

**Achado:** `harness task add-file` (`cf88680`) chama `compile_contract` de
novo, então `.harness/feature_list.json` fica correto na hora. Mas NÃO chama
`compile_session` — e é o `compile-session` (não o `compile-contract`) que
gera `.claude/settings.json` com `permissions.allow` ENUMERADO
(`Edit(path)`/`Write(path)` por arquivo). Duas camadas de gate coexistem:
(1) `boundary_guard.py` decide dinamicamente contra o `feature_list.json`
atual — correto depois do `task add-file`; (2) o `permissions.allow` do
próprio Claude Code é lista estática, só o `compile-session` a regenera.
**Não confirmado como bug** — usado 3x no dogfood sem prompt/deny observado,
mas sem instrumentação para ter certeza.

**Por que importa:** se o `permissions.allow` enumerado for consultado pelo
Claude Code ANTES do hook `PreToolUse` (isto é, se for um segundo portão, não
só uma lista de "pula prompt"), path adicionado via `task add-file` pode gerar
prompt de aprovação espúrio ao usuário — drift incômodo, não falha de
segurança (o hook ainda decide certo).

**Investigação primeiro (barata, decide o resto):** confirmar via doc oficial
(`https://code.claude.com/docs/en/hooks` — já consultada nesta sessão para o
item 1 do backlog anterior) e/ou teste empírico (compile-session → task
add-file → Edit no path novo, observar se prompta) se `permissions.allow` é
checado independente do hook, ou se o hook sempre dispara e a lista enumerada
é só otimização de UX (pula prompt quando já permitido).

**Correção condicional:**
- Se a investigação confirmar que NÃO há drift funcional (hook sempre
  decide): fechar como doc-only — nota em `README.md`/`TUTORIAL.md`
  explicando a relação entre as duas camadas, sem mudar código.
- Se confirmar drift real (prompt espúrio): `task add-file` chama
  `compile_session` automaticamente depois de `compile_contract`, mesmo
  padrão "sempre recompila" que o comando já tem para o contrato.

**Verify:** se fix de código: teste que `add-file` seguido de leitura do
`settings.json` mostra o novo path no `permissions.allow`. Se doc-only:
nenhum teste novo, só a nota.

**Esforço:** S investigar, +S-M se confirmado — **Risco se não investigar:**
BAIXO-MÉDIO (fricção de UX possível, não segurança — hook cobre o caso pior).

---

## Item 2 (issue #2) — Guia de granularidade de UI em `contract-templates.md`

**Achado:** ao planejar tarefas de componente Angular (T-07/T-08/T-09, Story
3.3) com estado visual condicional (badge de atenção/estouro), `files[]` foi
declarado só com `.ts`/`.html`/`.spec.ts` — faltou o `.scss` em 2 das 3,
descoberto só na implementação, corrigido via `harness task add-file` 2x.
`task add-file` funcionou perfeitamente — a fricção é a skill não lembrar do
arquivo de estilo.

**Por que importa:** fricção pequena mas recorrente em qualquer projeto com
componente de framework front-end (Angular/React/Vue) que tenha estado
visual condicional — é fácil planejar pensando só em lógica+template quando o
critério de aceitação fala de "aparência"/"indicador visual".

**Correção:** nota curta em `skills/plan/references/contract-templates.md`,
análoga à nota já existente "Granularidade de tarefas em linguagens
compiladas": ao planejar tarefa de UI com estado visual condicional
(badge/cor/aviso), listar explicitamente o arquivo de estilo (`.scss`/`.css`)
em `files[]` junto com lógica/template/teste.

**Verify:** revisão de leitura da nota adicionada (é doc, sem lógica —
nenhum teste automatizado aplicável).

**Esforço:** S — **Risco se não corrigir:** BAIXO (contorno via `task
add-file` já existe e funciona bem).

---

## Item 3 (issue #3) — Detecção MSB3027 quase nunca dispara no fluxo real

**Achado:** `detect_file_lock_hint` (`bfdcfe1`, item 7 do backlog anterior)
só dispara dentro de `VerifyFailedError`, isto é, quando `harness verify`
roda o `verify_cmd` e ele FALHA. Fluxo real de implementação é: (1) código,
(2) rodar `verify_cmd` manualmente iterando até passar, (3) só então chamar
`harness verify --mark-passed` para registrar. Nesse fluxo o comando já está
passando quando `harness verify` roda — a detecção nunca tem chance de
disparar. Bateu num MSB3027 real nesta sessão, mas rodando `dotnet ef
migrations add` manualmente para debugar, comando que nem é o `verify_cmd`
da tarefa.

**Por que importa:** a funcionalidade está implementada corretamente para o
caminho que foi desenhada (falha dentro de `harness verify`), mas o cenário
mais comum onde MSB3027 acontece de verdade (iteração ativa de
desenvolvimento, comandos ad-hoc adjacentes ao `verify_cmd`) fica fora do
alcance.

**Decisão de design (resolvida aqui, sem discussão adicional):** fix
DOC-ONLY. Rejeitado expor `detect_file_lock_hint` como função pública
reutilizável para o agente chamar manualmente contra saída de comando
ad-hoc — zero segundo caller concreto hoje, mesmo filtro anti-overengineering
que o veredito Forge aplicou ao backlog do issue #1 (não construir mecanismo
geral para um caso hipotético). O limite real é de alcance, não de
implementação — documentar é a correção proporcional.

**Correção:** nota em `skills/plan/SKILL.md`, Passo 6 (perto da nota MSB3027
já existente da v0.16.1), deixando explícito que a detecção automática só
cobre chamadas via `harness verify`/`compile-contract --dry-run-verify`, não
comandos ad-hoc rodados durante debug — nesse caso o humano/agente reconhece
o padrão MSB3027/EBUSY manualmente.

**Verify:** revisão de leitura da nota (doc-only).

**Esforço:** S — **Risco se não corrigir:** BAIXO (fricção pontual, contorno
manual já é o que acontece hoje).

---

## Item 4 (issue #5) — `harness task add-file`: inferir `--slug` com contrato único

**Achado:** primeira chamada de `harness task add-file T-07 <path> --dir .`
sem `--slug` errou com mensagem correta do argparse
(`the following arguments are required: --slug`), mas no momento só existia
UM contrato ativo em `.harness/work/` (`orcamento-projeto`) — inferível.

**Por que importa:** fricção pequena e evitável no caso comum (a maioria das
sessões trabalha um contrato por vez).

**Correção:** em `cli.py`, se `--slug` não for passado: escanear
`.harness/work/*/feature_list.json` (contratos já compilados); se existir
exatamente 1, usar como default; se 0 ou 2+, erro pedindo `--slug` explícito
(ambiguidade real ou nada compilado ainda) — comportamento atual preservado
nesses dois casos, só o caminho de 1-contrato-só ganha o atalho.

**Verify:** `pytest tests/test_cli.py -q` + testes novos: `.harness/work/`
com 1 contrato + `add-file` sem `--slug` → infere e funciona; com 2+
contratos + sem `--slug` → erro pedindo `--slug` (comportamento atual,
não regride); com 0 contratos compilados → erro (não regride).

**Esforço:** S — **Risco se não corrigir:** BAIXO (ergonomia pura, sem
mudança de comportamento no caso ambíguo).

---

## Rejeitados (avaliados, descartados com motivo)

- **Expor `detect_file_lock_hint` como função pública reutilizável** (opção B
  do issue #3) — zero segundo caller concreto hoje; construir mecanismo geral
  para escopo hipotético ("perseguir todo comando ad-hoc que um agente roda")
  é a mesma classe de overengineering vetada pelo Forge no backlog do issue #1.
- **`task add-file` chamar `compile-session` incondicionalmente sem
  investigar primeiro** (issue #4) — o próprio issue marca "não confirmado
  como bug"; codar um fix para um problema não confirmado é trabalho
  possivelmente desperdiçado. Investigação primeiro decide se há algo para
  corrigir.
