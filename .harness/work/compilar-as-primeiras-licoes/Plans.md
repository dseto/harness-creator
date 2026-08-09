# Plans: Compilar as três primeiras lições

## [T-01] A re-prova que passa vale como prova: a tarefa re-provada não é mais cobrada de novo à mão, e uma tarefa sem prova nenhuma continua sendo cobrada
- files: `src/harness/regression.py`, `src/harness/verify.py`, `tests/test_regression.py`
- verify: `pytest tests/test_regression.py -q`

## [T-02] A configuração de permissões passa a acompanhar sozinha todo comando do harness que o hook libera, sem ninguém manter uma segunda lista
- files: `src/harness/session_permissions.py`, `tests/test_session_permissions.py`, `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`, `tests/e2e/test_fase2_outcomes.py`, `tests/e2e/evidence/fase2-outcomes-verification.md`
- verify: `pytest tests/test_session_permissions.py -q`

## [T-03] Nenhum número da documentação sobre o tamanho do projeto pode ficar errado sem quebrar a suíte
- files: `tests/test_docs_derived_facts.py`, `README.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/arquitetura-visual.html`
- verify: `pytest tests/test_docs_derived_facts.py -q`
