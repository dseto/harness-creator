## [T-01] _detect_package_manager infere pip via manifest Python quando falta lockfile
- files: `src/harness/analyzer.py`, `tests/test_analyzer.py`
- verify: `pytest tests/test_analyzer.py -q`

## [T-02] Rodar suite completa para confirmar ausencia de regressao
- files: `src/harness/analyzer.py`, `tests/test_analyzer.py`
- verify: `pytest -q`
- depends: T-01
