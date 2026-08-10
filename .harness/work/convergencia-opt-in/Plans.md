## [T-01] Tarefa do contrato aceita bullets opcionais `metric`/`target`; sem eles o `feature_list.json` sai idêntico ao de hoje, e `target` sem `metric` é erro de compilação; `metric_cmd` de cada feature entra no `allow` compilado no mesmo padrão de `verify_cmd`
- files: `src/harness/contract.py`, `src/harness/session_permissions.py`, `tests/test_contract.py`, `tests/test_session_permissions.py`
- verify: `pytest tests/test_contract.py tests/test_session_permissions.py -q`

## [T-02] Com `metric_cmd`, cada `harness verify` mede e grava a trajetória (valor, timestamp, commit, árvore suja) no rastro da tarefa; saída não-numérica é falha de ambiente, nunca valor
- files: `src/harness/convergence.py`, `src/harness/verify.py`, `tests/test_convergence.py`, `tests/test_verify.py`
- verify: `pytest tests/test_convergence.py -q`
- depends: T-01

## [T-03] Disjuntor ganha os vereditos de trajetória: `stop_worsening` (2 piores que o melhor, nomeando o melhor estado) e `stop_plateau` (3 sem superar o melhor, oscilação inclusa); `target` atingido informa `target_met` sem mudar veredito nem `passes`; vereditos de falha repetida prevalecem
- files: `src/harness/budget.py`, `src/harness/convergence.py`, `tests/test_budget.py`
- verify: `pytest tests/test_budget.py -q`
- depends: T-02

## [T-04] Bloco de escalada de tarefa com métrica inclui a trajetória: série recente, melhor valor e onde ocorreu
- files: `src/harness/escalation.py`, `tests/test_escalation.py`
- verify: `pytest tests/test_escalation.py -q`
- depends: T-03

## [T-05] Passos 9 e 10 do lifecycle documentam a métrica opt-in, a regra de decisão (meio-pronto mensurável E iteração pode piorar o artefato) e a regra de ouro: métrica guia, `verify_cmd` decide
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/arquitetura-visual.html`, `AGENTS.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-04
