# Claude Progress

Contrato: `item-8-preflight-read-only`

## Features

| id | desc | status |
| --- | --- | --- |
| T-01 | Rodar o preflight volta a não escrever nada no repositório avaliado, nem perguntar nada a quem roda | done |
| T-02 | Quando o comando de teste ou de lint não resolve, o laudo diz ao usuário exatamente qual comando rodar para corrigir | done |

## Última atualização

<!-- harness:auto -->
- 2026-07-28T16:35:57.593108+00:00 — T-01 verificado (exit_code 0) — .harness/evidence/item-8-preflight-read-only/T-01.json
- 2026-07-28T16:37:19.367983+00:00 — T-02 verificado (exit_code 0) — .harness/evidence/item-8-preflight-read-only/T-02.json
<!-- /harness:auto -->


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
