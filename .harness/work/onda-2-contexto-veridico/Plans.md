## [T-01] AGENTS.md para de prometer sandbox/container e ferramentas que não existem no Claude Code
- files: `AGENTS.md`, `tests/test_docs_enforcement_claims.py`
- verify: `pytest tests/test_docs_enforcement_claims.py -q`

## [T-02] O bloco gerado do AGENTS.md para de repetir, em texto fixo, regras que já vivem na parte manual
- files: `src/harness/compiler.py`, `tests/test_compiler.py`
- verify: `pytest tests/test_compiler.py -q`

## [T-03] O hook SessionStart deixa de reinjetar contexto a cada compact, só no início real da sessão
- files: `src/harness/session_start.py`, `tests/test_session_start.py`, `tests/e2e/test_fase2_outcomes.py`
- verify: `pytest tests/test_session_start.py -q`

## [T-04] Sessão nascendo com o kill-switch desligado mostra isso na primeira mensagem, sem precisar perguntar
- files: `src/harness/session_start.py`, `tests/test_session_start.py`
- verify: `pytest tests/test_session_start.py -q`
- depends: T-03

## [T-05] Reverificar a mesma feature não duplica nota no progresso, e trocar de contrato não carrega nota de evidência que não existe mais
- files: `src/harness/templates.py`, `tests/test_templates.py`, `src/harness/verify.py`
- verify: `pytest tests/test_templates.py -q`
