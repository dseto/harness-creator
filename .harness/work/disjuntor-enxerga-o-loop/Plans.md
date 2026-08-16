# Plans: o loop caro para de ser invisível

## [T-01] O rastro de tentativas passa a anotar o erro, não o primeiro aviso que a ferramenta imprimiu — duas falhas com o mesmo aviso e erros diferentes deixam de ter a mesma assinatura
- files: `src/harness/attempts.py`, `tests/test_attempts.py`
- verify: `pytest tests/test_attempts.py -q`

## [T-02] O aviso de fim de sessão diz quantas vezes a tarefa já falhou e há quantas é a mesma falha, e aponta o comando que dá o veredito, antes de mandar tentar de novo
- files: `src/harness/stop_hook.py`, `tests/test_stop_hook.py`
- verify: `pytest tests/test_stop_hook.py -q`
- depends: T-01

## [T-03] Um comando de teste comprovadamente quebrado — caminho com curinga passado solto ao programa — não vira contrato aprovado: a compilação para e nomeia a tarefa, o comando e o argumento
- files: `src/harness/contract.py`, `tests/test_contract.py`
- verify: `pytest tests/test_contract.py -q`

## [T-04] O harness reconhece "nenhum arquivo de teste encontrado" também no runner de teste que originou o loop, em vez de tratar a execução como saída comum
- files: `src/harness/skips.py`, `tests/test_skips.py`
- verify: `pytest tests/test_skips.py -q`

## [T-05] Quando o agente esbarra no bloqueio de governança, ele passa a deixar o ajuste pronto num arquivo para o humano aplicar, em vez de só descrever a edição em texto — e o bloqueio continua igual
- files: `src/harness/boundary_guard.py`, `src/harness/lifecycle.py`, `tests/test_boundary_guard.py`, `tests/test_lifecycle.py`
- verify: `pytest tests/test_boundary_guard.py tests/test_lifecycle.py -q`
