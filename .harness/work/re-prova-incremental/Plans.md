# Plans: re-prova incremental

## [T-01] Ao fechar uma tarefa, o harness sabe dizer quais tarefas já concluídas correm risco de ter sido quebradas por ela — pelo parentesco de arquivos, sem repetir prova
- files: `src/harness/regression.py`, `tests/test_regression.py`
- verify: `pytest tests/test_regression.py -q`

## [T-02] Uma tarefa já dada como pronta que voltou a falhar deixa de constar como pronta, com o registro da falha, em vez de continuar alegando o que não é mais verdade
- files: `src/harness/regression.py`, `tests/test_regression.py`, `src/harness/verify.py`, `tests/test_verify.py`
- verify: `pytest tests/test_regression.py -q`
- depends: T-01

## [T-03] Fechar uma tarefa passa a conferir sozinho as tarefas antigas relacionadas, e a verificação avisa por exit code quando encontrou regressão
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `pytest tests/test_cli.py -q`
- depends: T-02

## [T-04] O ciclo e a documentação do projeto dizem o que fazer quando a verificação acusa regressão numa tarefa antiga
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/ARCHITECTURE.md`, `AGENTS.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-03
