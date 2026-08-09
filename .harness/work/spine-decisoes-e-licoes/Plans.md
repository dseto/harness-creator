# Plans: spine — decisões e lições

## [T-01] O projeto passa a ter onde guardar a razão de uma escolha e a fricção observada, com numeração e data automáticas, e nada do que já foi registrado pode ser alterado por um registro novo
- files: `src/harness/spine.py`, `tests/test_spine.py`
- verify: `pytest tests/test_spine.py -q`

## [T-02] Registrar uma decisão ou uma lição é um comando de uma linha, que o próprio hook de proteção não nega
- files: `src/harness/cli.py`, `tests/test_cli.py`, `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_cli.py tests/test_boundary_guard.py -q`
- depends: T-01

## [T-03] Os dois registros nascem junto com a sessão compilada, e recompilar nunca apaga o que já foi anotado
- files: `src/harness/templates.py`, `tests/test_templates.py`
- verify: `pytest tests/test_templates.py -q`
- depends: T-01

## [T-04] A sessão nova já começa sabendo das decisões recentes do projeto, sem ninguém precisar procurá-las
- files: `src/harness/session_start.py`, `tests/test_session_start.py`, `src/harness/spine.py`
- verify: `pytest tests/test_session_start.py -q`
- depends: T-01

## [T-05] Ao encerrar a demanda, o humano recebe a lista de fricções anotadas durante ela
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `pytest tests/test_cli.py -q`
- depends: T-02

## [T-06] O ciclo diz quando registrar uma decisão e quando registrar uma lição, e a documentação do projeto descreve os três registros da spine
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/ARCHITECTURE.md`, `AGENTS.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-02, T-04, T-05
