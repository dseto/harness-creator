## [T-01] Rodar um comando de terminal não lança mais dois processos de guarda — o segundo hoje só soma latência sem mudar nenhuma decisão
- files: `src/harness/compiler.py`, `src/harness/hook_launcher.py`, `src/harness/killswitch.py`, `tests/test_compiler.py`, `tests/test_hook_launcher.py`, `tests/test_boundary_guard.py`, `tests/test_audit.py`, `tests/test_docs_enforcement_claims.py`, `tests/e2e/test_boundary_flow.py`, `tests/e2e/test_fase2_outcomes.py`, `docs/plugin/GUIDE.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/ARCHITECTURE.md`, `docs/plugin/arquitetura-visual.html`
- verify: `pytest tests/test_compiler.py tests/test_hook_launcher.py tests/test_boundary_guard.py tests/test_audit.py tests/test_docs_enforcement_claims.py -q`

## [T-02] Ferramentas nativas de acompanhamento de tarefa (TaskCreate e afins) não são mais negadas por engano de nome
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_boundary_guard.py -q`

## [T-03] A auditoria do projeto detecta sozinha quando o hook de segurança instalado ficou desatualizado em relação ao código-fonte, e avisa disso na sessão seguinte
- files: `src/harness/audit.py`, `src/harness/session_start.py`, `tests/test_audit.py`, `tests/test_session_start.py`, `src/harness/boundary_guard.py`
- verify: `pytest tests/test_audit.py tests/test_session_start.py -q`

## [T-04] A checagem de comando de terminal para de repetir os mesmos 6 passos em duas funções, e a divergência entre as duas versões do veto do revisor passa a ser travada por teste em vez de invisível
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_boundary_guard.py -q`
