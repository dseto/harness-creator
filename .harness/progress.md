# Claude Progress

Contrato: `reconciliacao-de-abertura`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | A sessão pode conferir, antes de começar, se o que está anotado como pronto ainda é verdade no código — sem confundir tarefa pendente com divergência | done |
| T-02 | `harness reconcile` responde por linha de comando se o estado declarado bate com o real, com exit code utilizável por quem automatiza | done |
| T-03 | O comando que o ciclo manda rodar na abertura não é negado pelo próprio hook de proteção | done |
| T-04 | A sessão nasce já avisada das divergências, sem precisar que alguém lembre de rodar o comando — e nunca perde o contexto por causa dessa checagem | done |
| T-05 | O passo 5 do ciclo passa a mandar reconciliar com um comando, em vez de pedir uma olhada no histórico, e a documentação do projeto reflete o verbo novo | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
