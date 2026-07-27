## [T-01] boundary_guard libera "pip install -e ." quando package_manager=pip
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_boundary_guard.py -q`

## [T-02] session_permissions gera Bash(pip install -e .) no allow[] quando package_manager=pip
- files: `src/harness/session_permissions.py`, `tests/test_session_permissions.py`
- verify: `pytest tests/test_session_permissions.py -q`

## [T-03] templates gera "pip install -e ." em init.sh/init.ps1 quando package_manager=pip
- files: `src/harness/templates.py`, `tests/test_templates.py`
- verify: `pytest tests/test_templates.py -q`

## [T-04] Rodar suite completa para confirmar ausencia de regressao
- files: `src/harness/boundary_guard.py`, `src/harness/session_permissions.py`, `src/harness/templates.py`
- verify: `pytest -q`
- depends: T-01, T-02, T-03
