# Plans: O gate de entrega ganha um olho que não implementou

## [T-01] A entrega passa a ter um pacote de julgamento montado por comando, com o que foi prometido e onde olhar, e sem nada do raciocínio de quem implementou
- files: `src/harness/blind.py`, `tests/test_blind.py`
- verify: `pytest tests/test_blind.py -q`

## [T-02] O veredito fica registrado preso ao estado que julgou, um veredito novo nunca apaga o anterior, e veredito de um código que já mudou é reportado como velho
- files: `src/harness/blind.py`, `tests/test_blind.py`
- verify: `pytest tests/test_blind.py -q`
- depends: T-01

## [T-03] Montar o pacote e registrar o veredito são comandos de uma linha, que o próprio hook de proteção não nega
- files: `src/harness/cli.py`, `src/harness/boundary_guard.py`, `tests/test_cli.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_cli.py tests/test_boundary_guard.py -q`
- depends: T-02

## [T-04] A demanda não fecha sem um veredito independente e fresco, e cada motivo de bloqueio diz ao humano o que fazer
- files: `src/harness/finish.py`, `tests/test_finish.py`, `src/harness/reconcile.py`, `tests/test_reconcile.py`, `src/harness/branching.py`, `tests/test_branching.py`
- verify: `pytest tests/test_finish.py -q`
- depends: T-02

## [T-05] O ciclo diz quando despachar o verificador, o que mandar e o que jamais mandar, e a documentação descreve as três camadas de verificação
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/ARCHITECTURE.md`, `AGENTS.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-03, T-04
