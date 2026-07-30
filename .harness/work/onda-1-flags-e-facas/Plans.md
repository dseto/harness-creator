# Plans: onda-1-flags-e-facas

## [T-01] Hooks de PreToolUse iniciam sem herdar site-packages de outros projetos da máquina, então uma tool call comum roda mais rápido
- files: `src/harness/hook_launcher.py`, `tests/test_hook_launcher.py`
- verify: `python -m pytest tests/test_hook_launcher.py -k flags -q`

## [T-02] O código-fonte de boundary_guard.py explica seu contrato de comportamento em poucas linhas, sem carregar um histórico de decisões que o hook instalado nunca lê
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k docstring -q`

## [T-03] O hook de proteção compila para o mesmo conteúdo toda vez, então dá para detectar se alguém o alterou por fora do processo normal
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k deterministic -q`

## [T-04] O hook legado de proteção de arquivo de teste deixa de ser gerado, já que o boundary_guard cobre a mesma proteção por tarefa desde a Fase 2 — nenhum arquivo novo nasce prometendo um registro que nunca acontece
- files: `src/harness/compiler.py`, `tests/test_compiler.py`, `tests/e2e/test_boundary_flow.py`, `tests/e2e/test_fase2_outcomes.py`, `tests/e2e/evidence/fase2-outcomes-verification.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/GUIDE.md`, `docs/plugin/ARCHITECTURE.md`, `tests/test_docs_enforcement_claims.py`, `tests/test_audit.py`
- verify: `python -m pytest tests/test_compiler.py tests/e2e/test_boundary_flow.py tests/e2e/test_fase2_outcomes.py -q`

## [T-05] Os três comandos de auditoria (audit, audit-runtime, audit-team) compartilham a mesma definição de achado e relatório, então uma correção de formato vale para os três de uma vez
- files: `src/harness/findings.py`, `src/harness/audit.py`, `src/harness/runtime_audit.py`, `src/harness/team_audit.py`, `tests/test_findings.py`
- verify: `python -m pytest tests/test_findings.py tests/test_audit.py tests/test_runtime_audit.py tests/test_team_audit.py -q`

## [T-06] Quando harness verify falha, o agente vê o fim relevante da saída do runner de teste em vez da suíte inteira despejada no contexto
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `python -m pytest tests/test_cli.py -k truncat -q`

## [T-07] Uma regra de permissão específica deixa de sobreviver no arquivo gerado quando uma regra mais ampla do mesmo tipo já cobre o mesmo comando — o arquivo de permissões fica do tamanho do que está de fato em vigor
- files: `src/harness/settings_paths.py`, `tests/test_settings_paths.py`
- verify: `python -m pytest tests/test_settings_paths.py -q`
