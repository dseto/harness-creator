# Plans: atritos-do-ciclo

## [T-01] O agente consegue ler o relógio para carimbar a hora da aprovação, mas continua sem poder ajustar o relógio da máquina
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k date -q`

## [T-02] O comando de teste declarado no perfil do projeto pode ser rodado durante a demanda, e não só o teste exato da tarefa em curso
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k profile_test_command -q`
- depends: T-01

## [T-03] Descobrir em que branch a sessão está deixa de ser bloqueado, sem liberar apagar branch
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k show_current -q`
- depends: T-02

## [T-04] A suíte de ponta a ponta passa em qualquer console, sem depender da codificação configurada na máquina
- files: `tests/e2e/test_contract_flow.py`, `src/harness/cli.py`
- verify: `python -m pytest tests/e2e/test_contract_flow.py -q`

## [T-05] Ao barrar um commit na branch protegida, a recusa passa a dizer que chore de doc/versão é decisão do humano e vai no terminal dele, sem sugerir que o agente contorne o PR
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -k chore -q`
- depends: T-03

## [T-06] Depois de encerrar uma demanda, o resumo de progresso do contrato seguinte é regenerado — a sessão nova não herda mais o estado da demanda anterior
- files: `src/harness/finish.py`, `tests/test_finish.py`
- verify: `python -m pytest tests/test_finish.py -k regenera -q`
