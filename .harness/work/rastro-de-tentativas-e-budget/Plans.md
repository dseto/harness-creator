# Plans — rastro-de-tentativas-e-budget

## [T-01] Toda falha de verificação pode deixar registro estruturado consultável, com assinatura que identifica falha repetida
- files: `src/harness/attempts.py`, `tests/test_attempts.py`
- verify: `pytest tests/test_attempts.py -q`

## [T-02] `harness verify` grava a tentativa falha no vermelho e o marcador de sucesso no verde, sem mudar o resultado da verificação
- files: `src/harness/verify.py`, `tests/test_verify_attempts.py`
- verify: `pytest tests/test_verify_attempts.py -q`
- depends: T-01

## [T-03] O contrato aceita stop conditions tipadas que chegam compiladas ao feature_list.json; typo em tipo desconhecido é erro de compilação, não silêncio
- files: `src/harness/contract.py`, `tests/test_contract_stop_conditions.py`
- verify: `pytest tests/test_contract_stop_conditions.py -q`

## [T-04] `harness budget --feature <id>` responde se o agente continua ou para (mesma falha repetida / teto de iterações), com razão legível
- files: `src/harness/budget.py`, `src/harness/cli.py`, `tests/test_budget.py`, `src/harness/boundary_guard.py`
- verify: `pytest tests/test_budget.py -q`
- depends: T-01, T-03

## [T-05] O progress.md mostra o histórico de tentativas da fatia em andamento, gerado do rastro — e o bloco some quando a fatia fica verde
- files: `src/harness/templates.py`, `src/harness/verify.py`, `tests/test_progress_attempts.py`, `src/harness/attempts.py`
- verify: `pytest tests/test_progress_attempts.py -q`
- depends: T-02

## [T-06] O lifecycle manda consultar o disjuntor mecânico (`harness budget`) a cada falha do loop de autocorreção, em vez de prosa solta
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/ARCHITECTURE.md`, `AGENTS.md`, `src/harness/branching.py`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-04
