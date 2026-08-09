# Claude Progress

Contrato: `verificador-cego-do-gate`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | A entrega passa a ter um pacote de julgamento montado por comando, com o que foi prometido e onde olhar, e sem nada do raciocínio de quem implementou | done |
| T-02 | O veredito fica registrado preso ao estado que julgou, um veredito novo nunca apaga o anterior, e veredito de um código que já mudou é reportado como velho | done |
| T-03 | Montar o pacote e registrar o veredito são comandos de uma linha, que o próprio hook de proteção não nega | done |
| T-04 | A demanda não fecha sem um veredito independente e fresco, e cada motivo de bloqueio diz ao humano o que fazer | done |
| T-05 | O ciclo diz quando despachar o verificador, o que mandar e o que jamais mandar, e a documentação descreve as três camadas de verificação | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
