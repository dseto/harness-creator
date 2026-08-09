# Plans: Health check de abertura

## [T-01] A sessão passa a saber quais ferramentas exigidas pelo contrato não respondem, sem precisar rodar nenhum comando do contrato para descobrir
- files: `src/harness/health.py`, `tests/test_health.py`, `src/harness/cli.py`, `tests/test_cli.py`, `src/harness/boundary_guard.py`, `README.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/arquitetura-visual.html`, `docs/plugin/ARCHITECTURE.md`, `tests/e2e/evidence/fase2-outcomes-verification.md`
- verify: `pytest tests/test_health.py -q`

## [T-02] Um laudo só responde pelas três formas de o harness estar desprotegido em silêncio — ferramenta ausente, governança desalinhada e proteção desligada — e diz que a resposta é parar, não consertar
- files: `src/harness/health.py`, `tests/test_health.py`, `src/harness/doctor.py`, `tests/test_doctor.py`
- verify: `pytest tests/test_health.py -q`

## [T-03] A abertura da sessão entrega o veredito de ambiente sozinha, antes de qualquer coisa que dependa dele, sem ninguém precisar lembrar de pedir
- files: `src/harness/session_start.py`, `tests/test_session_start.py`, `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `AGENTS.md`
- verify: `pytest tests/test_session_start.py -q`
