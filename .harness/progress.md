# Claude Progress

Contrato: `onda-2-contexto-veridico`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | AGENTS.md para de prometer sandbox/container e ferramentas que não existem no Claude Code | done |
| T-02 | O bloco gerado do AGENTS.md para de repetir, em texto fixo, regras que já vivem na parte manual | done |
| T-03 | O hook SessionStart deixa de reinjetar contexto a cada compact, só no início real da sessão | done |
| T-04 | Sessão nascendo com o kill-switch desligado mostra isso na primeira mensagem, sem precisar perguntar | done |
| T-05 | Reverificar a mesma feature não duplica nota no progresso, e trocar de contrato não carrega nota de evidência que não existe mais | done |

## Última atualização

<!-- harness:auto -->
- 2026-07-30T12:28:39.493518+00:00 — T-01 verificado (exit_code 0) — .harness/evidence/onda-2-contexto-veridico/T-01.json
- 2026-07-30T12:29:58.786037+00:00 — T-02 verificado (exit_code 0) — .harness/evidence/onda-2-contexto-veridico/T-02.json
- 2026-07-30T12:33:25.233480+00:00 — T-04 verificado (exit_code 0) — .harness/evidence/onda-2-contexto-veridico/T-04.json
- 2026-07-30T12:37:20.631299+00:00 — T-05 verificado (exit_code 0) — .harness/evidence/onda-2-contexto-veridico/T-05.json
- 2026-07-30T12:41:08.879379+00:00 — T-03 verificado (exit_code 0) — .harness/evidence/onda-2-contexto-veridico/T-03.json
<!-- /harness:auto -->


_(vazio — demanda encerrada; o próximo `compile-session` regenera este arquivo a partir do contrato novo. A prova do que foi entregue está em `.harness/evidence/`.)_
