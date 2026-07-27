---
slug: infer-pip-package-manager
approved_by: Daniel Seto
approved_at: 2026-07-23T21:00:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste (`pytest tests/test_analyzer.py -q`)"
---

# Spec: analyzer infere package_manager=pip quando não há lockfile

## Resumo executivo

Hoje, quando o `harness analyze` roda num projeto Python sem `uv.lock`/
`poetry.lock` (ex.: um projeto que usa só `pip install -r requirements.txt`
ou `pip install -e .`), o campo `package_manager` fica `unknown` no
profile — mesmo existindo `pyproject.toml`/`setup.py` na raiz, prova
suficiente de que o projeto é Python e usa `pip` por padrão (não existe
"linguagem Python sem package manager"). Isso força o usuário a confirmar
manualmente, na entrevista da skill `plan`, algo que já dava para deduzir
sozinho. Esta mudança ensina o analyzer a inferir `pip` como fallback só
quando um manifest Python existe e nenhum lockfile de outro gerenciador
foi encontrado — sem inventar nada quando não há nem manifest Python.

## Escopo
Em `src/harness/analyzer.py`, `_detect_package_manager` hoje só olha
lockfiles (`_LOCKFILE_MANAGERS`: npm/pnpm/yarn/uv/poetry) e retorna `None`
se nenhum bater — isso joga `package_manager: nenhum lockfile detectado`
em `unknowns[]` mesmo com `pyproject.toml`/`setup.py` presente. Corrigir
para: se nenhum lockfile bateu MAS existe manifest Python
(`pyproject.toml` ou `setup.py`, mesma lógica de `_PYTHON_MANIFESTS` já
usada por `_detect_languages`), retornar `Finding("pip", <path do
manifest>, <confidence menor que 1.0, ex. 0.6>)` em vez de `None`. Sem
manifest Python e sem lockfile, comportamento atual (`None` -> unknown)
não muda.

## Critérios de aceitação
- Projeto com `pyproject.toml` e sem nenhum lockfile -> `package_manager.value == "pip"`,
  `package_manager.evidence` aponta pro manifest Python encontrado, e
  `"package_manager"` não aparece em `unknowns[]`.
  Prova: `pytest tests/test_analyzer.py -q`
- Projeto com `pyproject.toml` E `uv.lock` continua detectando `uv` (lockfile
  sempre vence o fallback pip — prioridade não muda).
  Prova: `pytest tests/test_analyzer.py -q`
- Projeto sem nenhum manifest reconhecido (nem Python nem outro) continua
  com `package_manager is None` e o unknown de hoje.
  Prova: `pytest tests/test_analyzer.py -q`
- Suite completa sem regressão.
  Prova: `pytest -q`

## Não-objetivos
- Não mexe em `boundary_guard.py`/`INSTALL_COMMAND_BY_PACKAGE_MANAGER`
  (gap de execução do `pip`, é o issue #18 — separado).
- Não adiciona detecção de `requirements.txt` como lockfile-like nem novo
  gerenciador — só o fallback pip via manifest Python já citado no issue.
- Não muda a ordem de prioridade entre lockfiles existentes.

## Unknowns
(nenhum — profile já rodado, ver `.harness/repo-profile.json`; confidence
do fallback pip definida em 0.6 por decisão de escopo, não é um unknown
do profile)
