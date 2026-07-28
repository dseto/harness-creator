# Claude Progress

Contrato `harness-finish` ENCERRADO por `harness finish`.

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | `harness finish` recusa encerrar a demanda quando o fecho não está íntegro, e diz exatamente o que está pendente | done |
| T-02 | Com o fecho íntegro, `harness finish` limpa os descartáveis do `.harness/` e deixa o resumo de progresso declarando o contrato encerrado | done |
| T-03 | O agente consegue rodar `harness finish` sozinho, sem prompt de permissão, como já faz com os demais subcomandos do harness | done |
| T-04 | Começar o segundo contrato de um repo deixa de travar o agente: o artefato que o próprio harness acabou de gerar não conta mais como sujeira que impede criar a branch | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
