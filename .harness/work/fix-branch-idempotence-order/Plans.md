## [T-01] Inverter ordem: checar branch-ja-correta antes do guard de dirty-tree
- files: `src/harness/branching.py`, `tests/test_branching.py`
- verify: `pytest tests/test_branching.py -q`

## [T-02] Rodar suite completa para confirmar ausencia de regressao
- files: `src/harness/branching.py`
- verify: `pytest -q`
- depends: T-01
