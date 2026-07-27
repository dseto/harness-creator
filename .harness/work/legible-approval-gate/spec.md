---
slug: legible-approval-gate
approved_by: Daniel Seto
approved_at: 2026-07-23T15:40:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste (pytest)"
---

# Spec: gate de aprovacao legivel (descricao funcional + link file:line)

## Resumo executivo

**Problema hoje:** quando uma tarefa termina e o harness pede pra voce
aprovar o commit, ele mostra so um codigo (`T-01`) e um comando tecnico
cru. Impossivel entender o que foi feito sem abrir os arquivos na mao —
ja foi classificado como "pessimo, nao da pra entender" num teste real.

**O que vamos entregar:** o texto que guia esse pedido de aprovacao passa
a EXIGIR, por escrito, uma descricao em linguagem simples do que mudou +
um link direto pro teste que prova. E o comando `harness verify` passa a
devolver, junto com o resultado, a descricao da tarefa e os arquivos
envolvidos — material pronto pra montar esse pedido sem caca ao tesouro.

**Como saber que funcionou:** o texto de instrucao do passo de aprovacao
(lido por toda sessao futura) menciona explicitamente a exigencia, e o
`harness verify` devolve mais contexto que so o comando cru.

## Escopo
O gate de aprovacao humana (passo 15 do Agent Session Lifecycle,
`render_lifecycle_detail()`/`render_lifecycle_block()` em
`src/harness/lifecycle.py`) hoje diz apenas "mensagem clara do que foi
feito" — vago, e na pratica agentes despejam so T-ID + JSON cru do
`verify_cmd`. Fix: tornar o texto explicito, exigindo descricao funcional
em linguagem natural + link `file:line` do teste, por feature. Alem
disso, `run_verify()` (`src/harness/verify.py`) grava evidencia
(`.harness/evidence/<id>.json`) sem `desc`/`files` da feature — enriquecer
isso da ao agente o material pronto (nome dos arquivos tocados, descricao
da tarefa) sem precisar reler `feature_list.json` a parte.

## Criterios de aceitacao
- Texto renderizado por `render_lifecycle_detail()` e
  `render_lifecycle_block()` menciona explicitamente a exigencia de
  descricao funcional + link file:line no passo 15. Prova:
  `pytest tests/test_lifecycle.py -q`
- Evidencia gravada por `run_verify()` inclui `desc` e `files` da feature
  (nao so `feature_id`/`verify_cmd`/`exit_code`/`files_hash`). Prova:
  `pytest tests/test_verify.py -q`
- Suite completa permanece verde. Prova: `pytest -q`

## Nao-objetivos
- Skill `plan` passo 5 (aprovacao do CONTRATO, antes de compilar) ja exige
  link markdown pro `spec.md`/`Plans.md` desde a PR #10 — nao mexe la.
- Nao adiciona enforcement automatico/bloqueante do formato de aprovacao
  (o gate continua textual/de convencao, nao ha como o harness validar
  programaticamente o texto que o agente escreve na conversa).

## Unknowns
(nenhum)
