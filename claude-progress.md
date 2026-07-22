# Claude Progress

Contrato: `hook-reasons-progress-sync`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | US-1 — razão concreta nos hooks TDD gerados (guard_test_runner + guard_tests) | done |
| T-02 | US-2 — templates.update_progress_status: reescreve a coluna de status de uma linha | done |
| T-03 | US-2 — wiring: run_verify sincroniza o claude-progress.md ao provar a feature | done |
| T-04 | Regressão total + nota no CHANGELOG | done |

## Última atualização

Contrato `hook-reasons-progress-sync` concluído — T-01..T-04 verificados
(evidência em `.harness/evidence/`, `exit_code: 0` cada), regressão total
verde (`pytest tests -q`) e `ruff check .` limpo. US-2 se auto-provou: o
`harness verify T-03` sincronizou a própria linha para `done`.
