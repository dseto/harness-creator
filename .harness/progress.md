# Claude Progress

Contrato: `skips-nunca-silenciosos`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | A saída de qualquer runner de teste passa a ser lida: quantos testes pularam, por quê quando o motivo aparece, e se nenhum teste chegou a ser coletado | done |
| T-02 | Toda execução de `harness verify` diz quantos testes pularam, verde ou vermelho, sem precisar de flag — e quando os motivos não estão visíveis na saída, diz isso e ensina como revelá-los | done |
| T-03 | Um comando explícito roda a suíte, mostra ao humano tudo o que pulou e grava essa lista como o conjunto conhecido; a verificação normal nunca escreve essa lista sozinha | done |
| T-04 | Um teste que começa a pular do nada derruba a verificação e nomeia o que pulou; o que já era conhecido passa sem atrito, e o que deixou de pular só informa | done |
| T-05 | Teste pulado por falta de variável de ambiente, credencial ou ferramenta para o trabalho já na primeira vez, nomeando o que falta — e o dono do repositório libera os pulos legítimos uma única vez no arquivo de configuração | done |
| T-06 | A prova gravada em disco passa a registrar o que pulou, para que quem abrir a evidência semanas depois veja a mesma coisa que quem rodou viu | done |
| T-07 | O arquivo de configuração do harness passa a nascer com todas as opções que ele aceita, cada uma com seu valor padrão e uma linha explicando — nenhuma opção fica descobrível só lendo o código | done |
| T-08 | A documentação continua batendo com o código depois do módulo e do subcomando novos: as contagens que ela declara conferem | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
