# Claude Progress

Contrato: `re-prova-incremental`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Ao fechar uma tarefa, o harness sabe dizer quais tarefas já concluídas correm risco de ter sido quebradas por ela — pelo parentesco de arquivos, sem repetir prova | done |
| T-02 | Uma tarefa já dada como pronta que voltou a falhar deixa de constar como pronta, com o registro da falha, em vez de continuar alegando o que não é mais verdade | done |
| T-03 | Fechar uma tarefa passa a conferir sozinho as tarefas antigas relacionadas, e a verificação avisa por exit code quando encontrou regressão | done |
| T-04 | O ciclo e a documentação do projeto dizem o que fazer quando a verificação acusa regressão numa tarefa antiga | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
