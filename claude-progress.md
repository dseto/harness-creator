# Claude Progress

Contrato: `extra-allowed-commands`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Schema: `GovernanceConfig.extra_allowed_commands` | done |
| T-02 | `boundary_guard.py`: loader + parametrização do hook gerado + wiring em `_evaluate_bash`/`_evaluate_powershell` | done |
| T-03 | `session_permissions.py`: wiring de `extra_allowed_commands` na enumeração de `.claude/settings.json` | done |
| T-04 | Docs e versão 0.17.6 — gate de regressão total | done |
| T-05 | E2E real (gate final da demanda): dogfood do cenário `entebate`, evidência commitada | done |

## Última atualização

Contrato `extra-allowed-commands` concluído — T-01..T-05 verificados (evidência em
`.harness/evidence/T-0{1..5}.json`, `exit_code: 0` cada) e integrado em
`ddc37f6` (feat: governance.extra_allowed_commands no harness.yaml, v0.17.6).
