---
slug: reconciliacao-de-abertura
approved_by: Daniel Seto
approved_at: 2026-08-09T05:12:00Z
stop_conditions:
  - type: consecutive_verify_failures
    n: 3
  - type: same_failure_signature
    n: 2
  - "Divergência entre o que este contrato precisa e o que `audit_closure` já entrega: parar e replanejar em vez de duplicar a regra em dois módulos."
---

# Spec: Reconciliação na abertura da sessão (`harness reconcile`)

## Resumo executivo

Hoje o harness só confere se o que está anotado como "pronto" continua sendo
verdade no momento de FECHAR uma demanda. Uma sessão que começa depois de outra
ter deixado o repositório fora do lugar — prova antiga que não vale mais para o
código atual, tarefa marcada como pronta sem prova nenhuma, sobra não commitada,
resumo de progresso falando de outra demanda — começa acreditando na anotação e
descobre o problema horas depois, ou não descobre.

Esta demanda passa a fazer essa mesma conferência no INÍCIO, com um comando
próprio (`harness reconcile`) e com o resultado injetado automaticamente na
abertura da sessão. O agente nasce sabendo se o estado declarado bate com o
estado real, e o passo do ciclo que hoje diz "dê uma olhada no histórico do git"
passa a ter um comando que responde sim ou não.

## Escopo

Incremento 2 do design de loop engineering
(`docs/reference/loop-engineering-design.md`), §7.4 — reconciliação de estado
declarado × estado real na abertura da sessão.

O julgamento já existe e é bom: `harness.finish.audit_closure` compara, só
lendo, (a) o `files_hash` da evidência contra o conteúdo atual dos `files[]`,
(b) o `passes: true` declarado contra a existência da prova, e (c) a working
tree contra os `files[]` do contrato. O que falta não é a regra — é ela ser
consultável no momento em que ainda dá para agir. Duplicar a regra num segundo
módulo é justamente como ela se torna inconsistente, então o trabalho é
**reusar** `audit_closure` e traduzir a saída para a pergunta da abertura.

Traduzir é necessário porque as duas perguntas não são a mesma:

1. **`feature_not_passed` não é divergência na abertura.** Tarefa pendente é o
   estado normal de quem está começando; no fecho é bloqueador. Se entrasse na
   saída da abertura, toda sessão abriria com "divergência" e o sinal morreria
   de tanto ser ruído.
2. **Existe uma divergência que só aparece na abertura:** o `.harness/progress.md`
   descrever um contrato diferente do `.harness/feature_list.json`. É o modo de
   falha documentado em `finish.render_closed_progress` (v0.25.0: o SessionStart
   injetou "nenhuma feature pendente" numa sessão com seis tarefas a fazer). O
   `finish` não o detecta porque reescreve o arquivo logo em seguida; na abertura
   ele é exatamente a mentira que envenena a sessão inteira.

Com o relatório pronto, três consumidores:

- **`harness reconcile --dir <alvo>`** — imprime o JSON e usa o exit code como
  veredito (0 = estado íntegro, 2 = divergência, 1 = erro de execução), a mesma
  convenção que `harness budget` já usa.
- **Hook `SessionStart`** — o contexto injetado ganha uma seção com as
  divergências. Como o hook é stdlib-only e roda com `-S`, ele delega a um
  interpretador novo (`python -m harness.reconcile`), o mesmo caminho que
  `_auto_update` já usa para `harness.autoupdate`. Qualquer falha vira ausência
  de seção: perder o contexto da sessão anterior é dano maior do que não ter o
  aviso.
- **Passo 5 do lifecycle** — deixa de ser "checar `git log`" (prosa que o agente
  cumpre olhando e concluindo o que quiser) e passa a ser "rode
  `harness reconcile`; com divergência, resolva antes de escolher fatia".

E, como o incremento 1 ensinou na prática: o verbo novo entra em
`_HARNESS_SUBCOMMANDS` do `boundary_guard` no MESMO contrato. Um verbo que a CLI
aceita e o hook nega é um passo do lifecycle que manda rodar comando barrado.

## Critérios de aceitação

- `harness.reconcile.reconcile(dir)` devolve `{"contract", "divergences", "features"}`
  reusando `audit_closure`, com `feature_not_passed` filtrado e
  `progress_contract_mismatch` acrescentado; cada divergência tem `kind` e
  `problem` legível. Prova: `pytest tests/test_reconcile.py -q`
- Repositório íntegro devolve `divergences: []`; evidência stale, prova ausente,
  kill-switch ativo, sobra tracked e progress de outro contrato aparecem cada um
  com seu `kind`. Prova: `pytest tests/test_reconcile.py -q`
- `harness reconcile --dir <alvo>` imprime o relatório em JSON e sai com 0 sem
  divergência, 2 com divergência e 1 em erro. Prova: `pytest tests/test_cli.py -q`
- `reconcile` está em `_HARNESS_SUBCOMMANDS` do `boundary_guard` gerado — o
  comando que o passo 5 manda rodar não é negado pelo próprio hook. Prova:
  `pytest tests/test_boundary_guard.py -q`
- O contexto do `SessionStart` traz a seção de divergências quando há alguma,
  não traz nada quando não há, e degrada em silêncio (sem seção, sessão intacta)
  quando a checagem falha. Prova: `pytest tests/test_session_start.py -q`
- O passo 5 do lifecycle — resumo e detalhe — nomeia `harness reconcile` e diz o
  que fazer com divergência, em vez de mandar "checar `git log`". Prova:
  `pytest tests/test_lifecycle.py -q`
- `README.md` e `docs/plugin/ARCHITECTURE.md` refletem o verbo novo e o módulo
  novo. Prova: `pytest tests/test_docs_enforcement_claims.py -q`

## Não-objetivos

- **Não corrige nada.** `reconcile` é só leitura, como `audit_closure`: não roda
  `git restore`, não re-verifica, não reescreve `progress.md`. Reconciliação que
  conserta sozinha apaga o rastro necessário para entender o que divergiu.
- **Não roda `verify_cmd`.** Re-provar o que já está verde é o incremento 3
  (§6, re-prova incremental). Aqui a checagem é barata, de hash e arquivo, para
  poder rodar em toda abertura de sessão sem custo perceptível.
- **Não bloqueia a sessão.** `SessionStart` não bloqueia nada por design do
  Claude Code; o exit 2 do comando é veredito para quem consulta, e quem obedece
  é o passo 5 do lifecycle. Enforcement por hook fica para a Fase 6, como
  decisão de ativação — não de reescrita.
- **Não substitui `harness finish`.** O fecho continua sendo dele, com o conjunto
  completo de bloqueadores (incluindo `feature_not_passed`) e a varredura.
- **Não consulta a rede.** Nada de `git fetch`/comparação com `origin`: o floor
  não libera rede não planejada, e divergência com o remoto é outra pergunta.
- **Não muda `audit_closure`.** Se a regra precisar mudar, muda lá e os dois
  lados herdam; este contrato não abre uma segunda implementação da mesma regra.

## Unknowns

- Nenhum. O `repo-profile.json` desta rodada saiu com `unknowns: []`
  (python / pytest / `tests/**/*.py` / `ruff check .`, todos com evidência em
  `pyproject.toml`).
