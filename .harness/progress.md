# Claude Progress

Contrato: `falha-transiente-e-escalada`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | O rastro de tentativas sabe distinguir falha transiente de falha estrutural, e o disjuntor conta só as estruturais | done |
| T-02 | `verify_cmd` com sinal transiente tenta de novo sozinho até 3× com pausa, sem gastar orçamento de correção; sinal não-transiente nunca tenta de novo | done |
| T-03 | Falha transiente que insiste 3× vira veredito próprio do disjuntor — parada de ambiente, não padrão repetido nem teto de iterações | done |
| T-04 | Todo veredito de parada do disjuntor vem com o bloco de escalada nas seis partes que o §8 exige, pronto para copiar ao humano | done |
| T-05 | O passo 10 do lifecycle documenta o retry transiente e manda usar o bloco de escalada gerado em vez de escrever a mensagem à mão | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
