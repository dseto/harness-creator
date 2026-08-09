# Plans: Reconciliação na abertura da sessão

## [T-01] A sessão pode conferir, antes de começar, se o que está anotado como pronto ainda é verdade no código — sem confundir tarefa pendente com divergência
- files: `src/harness/reconcile.py`, `tests/test_reconcile.py`, `src/harness/finish.py`
- verify: `pytest tests/test_reconcile.py -q`

## [T-02] `harness reconcile` responde por linha de comando se o estado declarado bate com o real, com exit code utilizável por quem automatiza
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `pytest tests/test_cli.py -q`
- depends: T-01

## [T-03] O comando que o ciclo manda rodar na abertura não é negado pelo próprio hook de proteção
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_boundary_guard.py -q`
- depends: T-02

## [T-04] A sessão nasce já avisada das divergências, sem precisar que alguém lembre de rodar o comando — e nunca perde o contexto por causa dessa checagem
- files: `src/harness/session_start.py`, `tests/test_session_start.py`, `src/harness/reconcile.py`
- verify: `pytest tests/test_session_start.py -q`
- depends: T-01

## [T-05] O passo 5 do ciclo passa a mandar reconciliar com um comando, em vez de pedir uma olhada no histórico, e a documentação do projeto reflete o verbo novo
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/ARCHITECTURE.md`, `tests/e2e/test_fase2_outcomes.py`, `AGENTS.md`, `tests/e2e/evidence/fase2-outcomes-verification.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-02, T-04
