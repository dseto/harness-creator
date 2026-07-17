---
name: preflight
description: Avalia um repositório CRU antes da instalação do harness e emite um laudo de prontidão PASS/WARNING/FAIL em 4 categorias (Git, Manifestos, Verificação/TDD, Qualidade Estática), cada check não-PASS com um Actionable Fix concreto e um veredito global READY/READY_WITH_WARNINGS/NOT_READY.
when_to_use: Quando o usuário pergunta se um repo está pronto para o harness ("esse repo está pronto?", "avaliar prontidão", "rodar preflight", "checar pré-requisitos") ou ANTES de qualquer /harness-creator:plan num repositório ainda não avaliado — é o portão de entrada do ciclo Plan→Work→Review.
argument-hint: "[caminho do repo-alvo, opcional]"
disable-model-invocation: false
---

# Preflight — laudo de prontidão de repositório cru

Você vai avaliar o repositório-alvo (argumento `$0`, ou o diretório atual se
vazio) e apresentar ao usuário um laudo de prontidão para o harness. O
preflight é READ-ONLY: ele NÃO escreve um byte no repo avaliado. É o portão
que roda ANTES de `analyze`/`plan` e diz se o repo cru tem o mínimo para o
ciclo Plan→Work→Review funcionar.

## Pré-requisito (só se os comandos abaixo falharem)

Não rode uma checagem de import à parte. Se `harness.cli` der
`ModuleNotFoundError`, ISSO que indica falta de `PYTHONPATH`; só então rode
com `$env:PYTHONPATH = "${CLAUDE_PLUGIN_ROOT}\src"` (PowerShell) e repita o
comando.

## Passo 1 — Rodar o preflight

```
python -m harness.cli preflight --dir <alvo>
```

A saída é um JSON no formato
`{verdict, target, categories: [{id, title, status, checks: [{code, status, message, fix, evidence}]}]}`
impresso no stdout. Exit codes:

- `0` — veredito `READY` **ou** `READY_WITH_WARNINGS` (o repo pode seguir).
- `1` — veredito `NOT_READY` (há pelo menos um FAIL bloqueante).
- `2` — erro de uso: alvo inexistente ou não é um diretório (mensagem em
  stderr, sem JSON no stdout).

## Passo 2 — Apresentar o laudo

Comece com UMA linha de veredito geral no topo (ex.:
`Veredito: NOT_READY` / `READY_WITH_WARNINGS` / `READY`).

Depois monte uma tabela por categoria, marcando o `status` agregado de cada
uma como `[PASS]`, `[WARNING]` ou `[FAIL]`. Para cada check que NÃO seja PASS,
mostre a `message` do JSON e, logo abaixo, o **Actionable Fix** (o campo `fix`
do JSON) — literalmente o que o CLI retornou, nunca um fix inventado por você.
Checks PASS podem ser resumidos (não precisam de linha por linha).

As 4 categorias, na ordem do laudo:

1. `git` — Controle de Versão (Git)
2. `manifest` — Manifestos de Projeto Estruturados
3. `tests` — Ferramentas de Verificação/TDD
4. `lint` — Qualidade Estática/Linting

## Passo 3 — Roteamento pelo veredito

- **`READY` ou `READY_WITH_WARNINGS`**: parabenize brevemente. Se houver
  WARNINGs, aponte que são não-bloqueantes mas valem atenção. Sugira o próximo
  passo do fluxo: `/harness-creator:plan`.
- **`NOT_READY`**: há FAIL(s) bloqueante(s). Ofereça aplicar os fixes,
  categoria a categoria. REGRA DURA: a skill NUNCA aplica um fix sozinha. Peça
  confirmação explícita do usuário para CADA fix, um a um — nunca em lote,
  nunca "aplico todos?". Depois de aplicar os fixes que o usuário aprovou,
  RE-RODE `python -m harness.cli preflight --dir <alvo>` (volte ao Passo 1)
  para confirmar que o veredito melhorou.

## Regras

- Nunca invente um fix fora do que o JSON retornou no campo `fix`; apresente
  exatamente o Actionable Fix do laudo.
- Nunca aplique um fix sem confirmação explícita do usuário, e nunca em lote —
  um fix por vez, cada um com seu próprio "sim".
- O preflight é read-only: rodar o CLI não altera o repo. Só o Passo 3 (com
  aprovação) escreve algo, e apenas o fix aprovado.
- Se o exit code for `2` (erro de uso — alvo inexistente ou não-diretório),
  reporte a mensagem de erro (stderr) ao usuário e NÃO prossiga para os
  Passos 2 e 3.
