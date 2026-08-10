# Claude Progress

Contrato: `placar-de-andamento`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | `harness status --brief` mostra o placar do chat montado por código: progresso X/N, tarefas com estado, tarefa atual com tentativa n/teto, última prova com o erro, métrica quando houver e próximo passo — markdown+unicode, sem ANSI; `harness status` sem flag continua com o JSON de hoje byte-idêntico | done |
| T-02 | `harness status --panel` mostra o mesmo placar colorido no terminal (cor só em TTY; em pipe sai texto puro) e `--watch N` re-renderiza sozinho no intervalo pedido | done |
| T-03 | A barra do Claude Code passa a mostrar sempre demanda, progresso, tarefa, tentativa, último veredito e o custo da sessão quando o CLI o fornecer — `compile-session` instala a statusline e recompilar não duplica nem deixa entrada órfã | done |
| T-04 | O lifecycle manda colar `harness status --brief` na abertura de cada iteração, na transição de fatia e em parada — e proíbe redigir o placar de cabeça | done |
| T-05 | Escalada, fecho e disjuntor falam resultado para o humano no stderr — inclusive o `harness finish`, que hoje não fala nada — e o JSON do stdout dos três continua byte-idêntico | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
