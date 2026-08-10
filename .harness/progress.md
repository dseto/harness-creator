# Claude Progress

Contrato: `convergencia-opt-in`

_Demanda ENCERRADA por `harness finish`._

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Tarefa do contrato aceita bullets opcionais `metric`/`target`; sem eles o `feature_list.json` sai idêntico ao de hoje, e `target` sem `metric` é erro de compilação; `metric_cmd` de cada feature entra no `allow` compilado no mesmo padrão de `verify_cmd` | done |
| T-02 | Com `metric_cmd`, cada `harness verify` mede e grava a trajetória (valor, timestamp, commit, árvore suja) no rastro da tarefa; saída não-numérica é falha de ambiente, nunca valor | done |
| T-03 | Disjuntor ganha os vereditos de trajetória: `stop_worsening` (2 piores que o melhor, nomeando o melhor estado) e `stop_plateau` (3 sem superar o melhor, oscilação inclusa); `target` atingido informa `target_met` sem mudar veredito nem `passes`; vereditos de falha repetida prevalecem | done |
| T-04 | Bloco de escalada de tarefa com métrica inclui a trajetória: série recente, melhor valor e onde ocorreu | done |
| T-05 | Passos 9 e 10 do lifecycle documentam a métrica opt-in, a regra de decisão (meio-pronto mensurável E iteração pode piorar o artefato) e a regra de ouro: métrica guia, `verify_cmd` decide | done |

## Última atualização

_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
