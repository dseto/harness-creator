# Plans: quando o agente depende de você, ele para e diz o que precisa

## [T-01] O agente passa a poder declarar que parou por depender de uma pessoa, nomeando em uma frase o que essa pessoa precisa fazer — e declaração sem motivo é recusada
- files: `src/harness/blocks.py`, `src/harness/cli.py`, `tests/test_blocks.py`, `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`, `tests/e2e/evidence/fase2-outcomes-verification.md`
- verify: `pytest tests/test_blocks.py -q`

## [T-02] Uma tarefa parada esperando a pessoa deixa de ser oferecida como próxima a trabalhar; as demais continuam na mesma ordem
- files: `src/harness/supervisor.py`, `tests/test_supervisor.py`
- verify: `pytest tests/test_supervisor.py -q`
- depends: T-01

## [T-03] O aviso de fim de sessão para de cobrar verificação da tarefa parada e passa a mostrar o que está na mão da pessoa; sem nenhuma tarefa parada, o texto é o de sempre
- files: `src/harness/stop_hook.py`, `tests/test_stop_hook.py`
- verify: `pytest tests/test_stop_hook.py -q`
- depends: T-01

## [T-04] O placar de andamento e o arquivo de progresso mostram a tarefa parada com a ação que cabe à pessoa, distinta de tarefa por fazer
- files: `src/harness/panel.py`, `src/harness/templates.py`, `tests/test_panel.py`
- verify: `pytest tests/test_panel.py -q`
- depends: T-01

## [T-05] A tarefa volta a andar por três caminhos e só por eles: a pessoa libera, o arquivo que estava sendo esperado muda, ou a verificação passa
- files: `src/harness/blocks.py`, `src/harness/verify.py`, `src/harness/cli.py`, `tests/test_blocks.py`
- verify: `pytest tests/test_blocks.py -q`
- depends: T-01

## [T-06] O encerramento da demanda não acontece enquanto houver tarefa parada esperando a pessoa — a pendência aparece nomeada, com a ação esperada
- files: `src/harness/finish.py`, `tests/test_finish.py`
- verify: `pytest tests/test_finish.py -q`
- depends: T-01

## [T-07] O documento de governança lido no início de toda sessão ensina o gesto: ao esbarrar em dependência humana, declarar a parada em vez de repetir a tentativa
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/ARCHITECTURE.md`, `docs/plugin/arquitetura-visual.html`, `AGENTS.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-01
