---
slug: compilar-as-primeiras-licoes
approved_by: Daniel Seto
approved_at: 2026-08-09T15:25:38Z
stop_conditions:
  - type: consecutive_verify_failures
    n: 3
  - type: same_failure_signature
    n: 2
  - "Se o recarimbo da re-prova precisar CRIAR evidência onde não havia nenhuma: parar. Tarefa marcada à mão sem prova é o que o bloqueador `evidence_missing` existe para pegar, e fabricar o arquivo apagaria justamente essa detecção."
  - "Se travar um número da documentação exigir mudar o que o número SIGNIFICA (ex.: contar de um jeito no teste e de outro na prosa): parar e tirar o número do texto. Número travado contra a fonte errada é pior que número sem trava — ele passa a mentir com aval de teste."
---

# Spec: Compilar as três primeiras lições

## Resumo executivo

O harness passou a anotar as fricções que aparecem enquanto ele é usado, e a
primeira leva já está lá esperando. Três delas cobram trabalho manual todo
ciclo: uma obriga a repetir à mão uma verificação que a máquina acabou de
fazer, e as outras duas deixam a documentação e a configuração afirmarem
números e listas que ninguém confere — que foi exatamente o que o verificador
independente pegou errado no ciclo passado.

Esta demanda fecha as três. Depois dela, a re-prova que passa vale como prova,
e nenhum número ou lista escrita à mão sobrevive a estar errada: quem confere
passa a ser um teste, não a memória de quem escreveu.

## Escopo

Primeira volta do **loop de segunda ordem** (§5.3 do
[design de loop engineering](docs/reference/loop-engineering-design.md)): o
agente anota a lição, o humano compila. Três itens de `.harness/lessons.md`,
aprovados para virar mudança:

**1. Re-prova verde não recarimba a evidência.** Ao fechar uma fatia, a
re-prova incremental (incremento 3) roda o `verify_cmd` das fatias acopladas.
Quando passa, ela não regrava a evidência daquelas fatias — o `files_hash`
continua o antigo, o `finish` acusa `evidence_stale` e cobra um
`harness verify <id>` manual que executa **exatamente o mesmo comando que
acabou de rodar verde**. Aconteceu em três incrementos seguidos.

**2. A superfície de permissions não deriva do guard.** O
`session_permissions._HARNESS_SUBCOMMANDS` é uma cópia à mão da lista do
`boundary_guard`, e ficou para trás em oito verbos (`blind`, `finish`,
`budget`, `reconcile`, `decide`, `lesson`, `task`, `pr-draft`) — com o
comentário ainda afirmando que espelha. O efeito não é `deny` (o hook libera),
é prompt de permissão em comandos que o próprio lifecycle manda rodar, e um
`settings.local.json` que descreve mal a superfície.

**3. Nenhum número da documentação tem trava.** `README.md` afirma "25
subcomandos", "38 módulos" e "1177 casos". Errei a contagem de casos duas vezes
na mesma demanda, e o único que pegou foi o verificador cego — nada além de
leitura pegava.

Duas decisões de desenho que o escopo carrega:

- **Recarimbar só onde já havia evidência.** A re-prova verde regrava a
  evidência existente; ela nunca CRIA uma. Fatia com `passes: true` e sem
  arquivo de prova é marcação à mão, e `evidence_missing` existe para pegar
  isso — fabricar o arquivo destruiria a detecção. Recarimbo é atualização de
  prova válida, não emissão de prova nova.
- **Fonte única, não segunda lista.** O `session_permissions` passa a importar
  a lista do `boundary_guard` em vez de copiá-la. Um teste comparando duas
  listas escritas à mão detecta a divergência; importar impede que ela exista.

O tema é um só: **nenhum fato à mão sem fonte derivável**. O mecanismo já
existe neste repo — o teste que deriva os verbos do parser do argparse
(incremento 2) já acusou verbo esquecido três vezes, sozinho.

## Critérios de aceitação

- Re-prova verde regrava a evidência das tarefas re-provadas com o hash e o
  timestamp do estado que acabou de ser provado, e nunca cria evidência onde
  não havia — prova: `pytest tests/test_regression.py -q`
- A superfície de permissions do `settings.local.json` cobre todo subcomando
  que o `boundary_guard` libera, sem lista paralela — prova:
  `pytest tests/test_session_permissions.py -q`
- Todo número da documentação sobre o tamanho do projeto é conferido contra a
  fonte real (parser, diretório, coleta do pytest) — prova:
  `pytest tests/test_docs_derived_facts.py -q`

## Não-objetivos

- **Lição 2 (`git switch` no guard).** A causa declarada precisa de
  `/harness-creator:assess` antes de virar contrato: já houve lição neste repo
  cuja causa escrita estava errada. Fica em `lessons.md`.
- **Lição 4 (veredito invalidado pelas próprias observações).** Doeu uma vez.
  Esperar a segunda ocorrência antes de construir `--since-verdict`.
- **Mudar o que a re-prova SELECIONA.** A interseção por `files[]` continua
  como está; muda só o que acontece depois do verde.
- **Novo comando de CLI.** As três correções acontecem dentro do que já existe.

## Unknowns

- (nenhum — `harness analyze` fechou o profile sem `unknowns[]`)
