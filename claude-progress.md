# Claude Progress

Contrato: `infer-pip-package-manager`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | _detect_package_manager infere pip via manifest Python quando falta lockfile | done |
| T-02 | Rodar suite completa para confirmar ausencia de regressao | done |

## Última atualização

Contrato `harness-kill-switch` CONCLUÍDO — T-01..T-06 verificados
(`harness verify <id> --mark-passed`, `exit_code: 0` cada; evidência em
`.harness/evidence/`), `harness supervise` = `{next: null}`, regressão
total verde (`pytest tests -q` via T-06), ruff limpo. TDD em cada tarefa
(teste falho → implementação → verde).

Entregue: novo módulo `src/harness/killswitch.py`
(`is_disabled`/`disable`/`enable`/`status`/`SENTINEL_RELATIVE_PATH`/
`DISABLED_CHECK_SRC`); CLI `harness disable|enable|status` (`cli.py`);
floor anti-auto-desativação + short-circuit no `boundary_guard`
(`is_floor_disable_sentinel_path`/`is_floor_disable_command`/
`is_floor_bash_disable_redirect`, embutidos via getsource; gitignore do
sentinel em `install_boundary_guard`); no-op nos 4 hooks restantes
(`session_start`/`stop_hook`/`guard_tests`/`guard_test_runner`); CHANGELOG.

Sem UI tocada (Passo 8 N/A — backend/CLI only). Branch
`contract/harness-kill-switch`. NADA COMMITADO — aguardando aprovação
humana explícita (passo 15 do lifecycle) antes do commit + PR (regra:
nunca commit direto na main, só via PR).

NOTA: o `boundary_guard` instalado nesta sessão é o ANTERIOR (não
recompilei mid-sessão) — o kill-switch só fica ativo após
`harness compile-session`. Recompilar troca o hook ativo; deixar a critério
do usuário.
