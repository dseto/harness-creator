## [T-01] Passo 15 exige descricao funcional + link file:line por escrito
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`
- verify: `pytest tests/test_lifecycle.py -q`

## [T-02] Enriquecer evidencia de harness verify com desc e files da feature
- files: `src/harness/verify.py`, `tests/test_verify.py`
- verify: `pytest tests/test_verify.py -q`

## [T-03] Rodar suite completa para confirmar ausencia de regressao
- files: `src/harness/lifecycle.py`, `src/harness/verify.py`, `tests/e2e/test_fase3_outcomes.py`
- verify: `pytest -q`
- depends: T-01, T-02
