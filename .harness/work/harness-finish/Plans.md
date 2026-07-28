# Plans: harness-finish

## [T-01] `harness finish` recusa encerrar a demanda quando o fecho não está íntegro, e diz exatamente o que está pendente
- files: `src/harness/finish.py`, `src/harness/cli.py`, `tests/test_finish.py`
- verify: `python -m pytest tests/test_finish.py -k audit -q`

## [T-02] Com o fecho íntegro, `harness finish` limpa os descartáveis do `.harness/` e deixa o resumo de progresso declarando o contrato encerrado
- files: `src/harness/finish.py`, `tests/test_finish.py`, `src/harness/cli.py`
- verify: `python -m pytest tests/test_finish.py -k sweep -q`
- depends: T-01

## [T-03] O agente consegue rodar `harness finish` sozinho, sem prompt de permissão, como já faz com os demais subcomandos do harness
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k finish -q`
- depends: T-01

## [T-04] Começar o segundo contrato de um repo deixa de travar o agente: o artefato que o próprio harness acabou de gerar não conta mais como sujeira que impede criar a branch
- files: `src/harness/branching.py`, `tests/test_branching.py`
- verify: `python -m pytest tests/test_branching.py -k managed -q`
