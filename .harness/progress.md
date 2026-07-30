# Claude Progress

Contrato: `onda-3-um-processo-um-floor`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Rodar um comando de terminal não lança mais dois processos de guarda — o segundo hoje só soma latência sem mudar nenhuma decisão | done |
| T-02 | Ferramentas nativas de acompanhamento de tarefa (TaskCreate e afins) não são mais negadas por engano de nome | done |
| T-03 | A auditoria do projeto detecta sozinha quando o hook de segurança instalado ficou desatualizado em relação ao código-fonte, e avisa disso na sessão seguinte | done |
| T-04 | A checagem de comando de terminal para de repetir os mesmos 6 passos em duas funções, e a divergência entre as duas versões do veto do revisor passa a ser travada por teste em vez de invisível | done |

## Última atualização

<!-- harness:auto -->
- 2026-07-30T13:49:07.626168+00:00 — T-01 verificado (exit_code 0) — .harness/evidence/onda-3-um-processo-um-floor/T-01.json
- 2026-07-30T13:52:41.908071+00:00 — T-02 verificado (exit_code 0) — .harness/evidence/onda-3-um-processo-um-floor/T-02.json
- 2026-07-30T14:03:45.080305+00:00 — T-03 verificado (exit_code 0) — .harness/evidence/onda-3-um-processo-um-floor/T-03.json
- 2026-07-30T14:12:47.714295+00:00 — T-04 verificado (exit_code 0) — .harness/evidence/onda-3-um-processo-um-floor/T-04.json
<!-- /harness:auto -->


_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
