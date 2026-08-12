---
slug: parei-e-sua-vez
approved_by: Daniel Seto
approved_at: 2026-08-12T01:16:36Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd na mesma tarefa"
  - "Fazer o hook Stop enxergar o bloqueio exigir que o arquivo gerado importe o pacote `harness` — pare e escale: o hook roda fora do venv do projeto, e a decisão D-010 já resolveu essa fronteira uma vez"
  - "O bloqueio precisar ser gravado dentro de `.harness/feature_list.json` para funcionar — pare: aquele arquivo nasce de `compile-contract` e não se edita à mão; bloqueio é estado de sessão, não cláusula de contrato"
  - "Destravar exigir que o agente escreva em `.harness/harness.yaml` ou em qualquer arquivo do plano de controle — pare: é exatamente o bloqueio que esta demanda existe para respeitar"
  - "Alguma tarefa exigir que o bloqueio SUMA de alguma saída (status, progresso, encerramento) para caber — pare: bloqueio invisível é o defeito, não a solução"
---

# Spec: quando o agente depende de você, ele para e diz o que precisa

## Resumo executivo

Numa sessão real, o agente esbarrou num ajuste de configuração que só uma
pessoa pode fazer. Ele entendeu a situação e escreveu na tela exatamente isso:
edite este arquivo nesta linha, rode este comando, me avise. E então continuou
tentando executar a mesma tarefa dezenas de vezes, contra a mesma configuração
errada, porque nada no harness registrava que a tarefa estava parada esperando
uma pessoa.

O motivo é simples: para o harness, uma tarefa só existe em dois estados —
provada ou não provada. "Estou esperando você" e "ainda não implementei" são o
mesmo estado. Por isso tudo que empurra trabalho continuou empurrando: o
supervisor devolvia a tarefa como próxima, o aviso de fim de sessão cobrava a
verificação, e o agente obedecia — tentando de novo o que ele próprio já tinha
explicado que não tinha como funcionar.

Depois desta demanda existe um terceiro estado. O agente declara que parou e o
que precisa de você, em uma frase acionável. Enquanto isso valer, ninguém cobra
aquela tarefa dele: o supervisor pula, o aviso de fim de sessão para de pedir
verificação e passa a mostrar o que está na sua mão, e o encerramento da demanda
não acontece fingindo que está tudo resolvido. Você resolve, e o bloqueio some —
por comando seu, porque o arquivo que ele estava esperando mudou, ou
simplesmente porque a verificação passou.

## Escopo

O defeito, confirmado no código deste repositório:

**Não existe o estado "bloqueada".** Uma feature em `feature_list.json` tem
`passes: true|false` e nada mais (`src/harness/contract.py:781-795`). Grep por
`blocked` em `src/harness/escalation.py` devolve zero. Não há campo, verbo nem
conceito.

Consequência, mecanismo por mecanismo:

- `ready_features` (`src/harness/supervisor.py:43-71`) devolve toda feature com
  `passes != True` cujas dependências passaram — uma tarefa parada esperando
  humano é indistinguível de uma tarefa por fazer, e volta como "próxima".
- `build_feedback` do hook Stop (`src/harness/stop_hook.py:258-273`) cobra
  `harness verify <id>` de toda feature com `passes` false e trabalho não
  commitado — inclusive da que está parada por dependência humana.
- `audit_closure` (`src/harness/finish.py:154`) monta `blockers` a partir de
  evidência ausente, obsoleta e afins. Não tem como saber que a demanda está
  parada esperando uma pessoa.

O agente **sabia** que estava bloqueado — escreveu na tela. Não tinha onde
registrar, então a informação morreu no texto do chat enquanto a máquina inteira
continuou tratando a tarefa como pendente de código.

**O desenho.**

O agente declara o bloqueio por um verbo do CLI, nomeando o que precisa de você
em linguagem acionável — não "erro de configuração", e sim "editar `test_glob`
na linha 27 de `.harness/harness.yaml` e rodar `harness compile-session`". O
registro vai para `.harness/blocks/<contrato>/<id>.json`, seguindo o padrão que
`evidence/`, `attempts/` e `skips-baseline/` já usam: estado de sessão mora em
diretório próprio, nunca dentro de `feature_list.json`, que nasce de
`compile-contract` e não se edita à mão.

Enquanto o bloqueio valer, os quatro mecanismos o respeitam: o supervisor não
devolve a tarefa como próxima; o hook Stop para de cobrar verificação dela e
passa a enunciar o que está na sua mão; `harness status` e o `progress.md`
mostram AGUARDANDO VOCÊ com a ação exata; e `harness finish` não encerra a
demanda com bloqueio pendente.

O bloqueio some por três caminhos: comando explícito seu; mudança no arquivo que
ele declarou estar esperando (quando houver um); ou verificação verde — se
passou, o que estava travando deixou de travar, e insistir num registro morto é
outra forma de mentira de estado.

**O que impede o agente de abusar disso.** Bloquear é a saída fácil para fugir
de trabalho difícil, e um agente que aprende a usá-la trocaria implementação por
desculpa. Três freios, todos no contrato: o motivo é obrigatório e não pode ser
vazio; o bloqueio aparece em toda saída que conta a verdade sobre o andamento,
então ele nunca é silencioso; e bloqueio nunca conta como tarefa provada nem
deixa a demanda ser encerrada. Fugir do trabalho, aqui, significa deixar na sua
tela uma frase dizendo exatamente do que ele fugiu.

## Critérios de aceitação

- O agente registra um bloqueio nomeando o que precisa do humano, e o registro
  fica em `.harness/blocks/<contrato>/<id>.json` com o motivo íntegro; motivo
  vazio ou só espaço é recusado, e tarefa inexistente no contrato ativo também.
  Prova: `pytest tests/test_blocks.py -q`
- Uma feature bloqueada não é devolvida como próxima pelo supervisor, e as
  demais continuam sendo devolvidas na mesma ordem de antes. Prova:
  `pytest tests/test_supervisor.py -q`
- O hook Stop para de cobrar `harness verify` de uma feature bloqueada e passa a
  enunciar o que está na mão do humano; features não bloqueadas continuam com o
  texto de hoje; sem nenhum bloqueio, a saída é byte-idêntica à atual. Prova:
  `pytest tests/test_stop_hook.py -q`
- O arquivo de hook GERADO (não uma cópia da lógica) produz esse texto quando
  executado por subprocess com um bloqueio no disco, e não importa o pacote
  `harness`. Prova: `pytest tests/test_stop_hook.py -q`
- `harness status` e o `progress.md` mostram a tarefa bloqueada com a ação que
  cabe ao humano, distinguindo-a visualmente de tarefa por fazer. Prova:
  `pytest tests/test_panel.py -q`
- O bloqueio some por comando explícito, por mudança no arquivo declarado como
  esperado, e por verificação verde — e some por exatamente esses três, nunca
  sozinho. Prova: `pytest tests/test_blocks.py -q`
- `harness finish` não encerra a demanda enquanto houver bloqueio pendente: ele
  aparece em `blockers` nomeando a tarefa e a ação esperada. Prova:
  `pytest tests/test_finish.py -q`
- O AGENTS.md gerado ensina o gesto: ao esbarrar em dependência humana, declarar
  o bloqueio em vez de repetir a tentativa. Prova:
  `pytest tests/test_lifecycle.py -q`

## Não-objetivos

- **Detectar o bloqueio sozinho.** O harness não vai adivinhar, a partir da
  saída de um comando, que a causa é humana — quem declara é o agente, que já
  sabe (na sessão real ele escreveu isso na tela antes de continuar tentando).
  Inferência automática aqui erraria nos dois sentidos: travaria trabalho por
  bug de implementação e deixaria passar dependência humana silenciosa.
- **Bloquear a sessão ou negar comando.** O hook Stop continua devolvendo
  `additionalContext` e nunca `decision: "block"`; o `boundary_guard` não ganha
  regra nova. Um bloqueio declarado é informação de estado, não barreira de
  runtime.
- **O disjuntor de loop de implementação.** Consultar `harness budget` dentro do
  `harness verify` para interromper repetição da mesma falha é problema vizinho,
  real e fora daqui. Fica parado em `.harness/work/disjuntor-enxerga-o-loop/`,
  junto da assinatura de falha, do curinga em `verify_cmd`, do runner não
  reconhecido e do gesto do scratch — todos sem aprovação.
- **Prazo, expiração ou destrave automático por tempo.** Bloqueio que expira
  sozinho volta a empurrar trabalho contra a mesma parede — é o defeito de novo,
  com atraso.
- **Deixar o agente aplicar a mudança que ele pediu.** O que o bloqueio nomeia
  continua sendo do humano; nada aqui abre escrita no plano de controle.

## Unknowns

- Nenhum. O profile deste repositório saiu sem `unknowns[]`
  (`.harness/repo-profile.json`): python, pip, `pytest`, `tests/**/*.py`,
  `ruff check .` — todos com evidência em `pyproject.toml`/`tests/conftest.py`.
