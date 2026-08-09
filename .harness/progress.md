# Claude Progress

Contrato: `rastro-de-tentativas-e-budget`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Toda falha de verificação pode deixar registro estruturado consultável, com assinatura que identifica falha repetida | done |
| T-02 | `harness verify` grava a tentativa falha no vermelho e o marcador de sucesso no verde, sem mudar o resultado da verificação | done |
| T-03 | O contrato aceita stop conditions tipadas que chegam compiladas ao feature_list.json; typo em tipo desconhecido é erro de compilação, não silêncio | done |
| T-04 | `harness budget --feature <id>` responde se o agente continua ou para (mesma falha repetida / teto de iterações), com razão legível | done |
| T-05 | O progress.md mostra o histórico de tentativas da fatia em andamento, gerado do rastro — e o bloco some quando a fatia fica verde | done |
| T-06 | O lifecycle manda consultar o disjuntor mecânico (`harness budget`) a cada falha do loop de autocorreção, em vez de prosa solta | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
