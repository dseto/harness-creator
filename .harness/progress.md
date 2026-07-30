# Claude Progress

Contrato: `onda-1-flags-e-facas`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Hooks de PreToolUse iniciam sem herdar site-packages de outros projetos da máquina, então uma tool call comum roda mais rápido | done |
| T-02 | O código-fonte de boundary_guard.py explica seu contrato de comportamento em poucas linhas, sem carregar um histórico de decisões que o hook instalado nunca lê | done |
| T-03 | O hook de proteção compila para o mesmo conteúdo toda vez, então dá para detectar se alguém o alterou por fora do processo normal | done |
| T-04 | O hook legado de proteção de arquivo de teste deixa de ser gerado, já que o boundary_guard cobre a mesma proteção por tarefa desde a Fase 2 — nenhum arquivo novo nasce prometendo um registro que nunca acontece | done |
| T-05 | Os três comandos de auditoria (audit, audit-runtime, audit-team) compartilham a mesma definição de achado e relatório, então uma correção de formato vale para os três de uma vez | done |
| T-06 | Quando harness verify falha, o agente vê o fim relevante da saída do runner de teste em vez da suíte inteira despejada no contexto | done |
| T-07 | Uma regra de permissão específica deixa de sobreviver no arquivo gerado quando uma regra mais ampla do mesmo tipo já cobre o mesmo comando — o arquivo de permissões fica do tamanho do que está de fato em vigor | done |

## Última atualização

<!-- harness:auto -->
- 2026-07-30T01:19:34.664057+00:00 — T-05 verificado (exit_code 0) — .harness/evidence/verificacao-honesta/T-05.json
- 2026-07-30T01:42:51.910486+00:00 — T-05 verificado (exit_code 0) — .harness/evidence/verificacao-honesta/T-05.json
- 2026-07-30T11:09:44.427176+00:00 — T-01 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-01.json
- 2026-07-30T11:17:00.657535+00:00 — T-02 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-02.json
- 2026-07-30T11:20:43.620530+00:00 — T-03 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-03.json
- 2026-07-30T11:37:07.630127+00:00 — T-04 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-04.json
- 2026-07-30T11:43:32.864163+00:00 — T-04 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-04.json
- 2026-07-30T11:43:43.368157+00:00 — T-05 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-05.json
- 2026-07-30T11:45:45.905784+00:00 — T-06 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-06.json
- 2026-07-30T11:48:42.472559+00:00 — T-07 verificado (exit_code 0) — .harness/evidence/onda-1-flags-e-facas/T-07.json
<!-- /harness:auto -->


_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
