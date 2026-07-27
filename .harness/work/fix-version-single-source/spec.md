---
slug: fix-version-single-source
approved_by: Daniel Seto
approved_at: 2026-07-23T15:05:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste (pytest)"
---

# Spec: versao com fonte unica + guard test contra drift

## Resumo executivo

**Problema hoje:** o número de versão do produto (ex. "0.17.6") está
escrito à mão em 4 arquivos diferentes. Toda vez que alguém lança uma
versão nova, precisa lembrar de atualizar os 4 — e já esqueceu 2 uma vez.
Resultado: partes do sistema "acham" que estão numa versão e outras
partes acham outra, causando confusão sobre o que realmente foi entregue.

**O que vamos entregar:** o número de versão passa a existir em 1 lugar
só. Os outros 3 lugares continuam existindo (não dá pra eliminar por
limitação técnica de onde cada um vive), mas ganham uma checagem
automática que barra qualquer entrega se ficarem desalinhados — não
depende mais de ninguém lembrar manualmente.

**Como saber que funcionou:** depois de pronto, se alguém mudar a versão
em só um dos arquivos e esquecer os outros, os testes automáticos falham
na hora, avisando antes que o erro chegue em produção.

## Escopo
A versao do pacote existe em 4 arquivos editados manualmente sem
enforcement: `pyproject.toml`, `src/harness/__init__.py`,
`.claude-plugin/marketplace.json`, `.claude-plugin/plugin.json`. Commit
ddc37f6 atualizou so 2 de 4, deixando os outros desatualizados — causou
compilacoes marcadas com versao errada. Fix: colapsar `pyproject.toml`
em `__init__.py` via `dynamic version` do hatchling (`[tool.hatch.version]
path = "src/harness/__init__.py"`), reduzindo fontes manuais Python-side
de 2 para 1. Adicionar guard test que compara `marketplace.json` e
`plugin.json` contra `harness.__version__` e falha se divergir.

## Criterios de aceitacao
- `pyproject.toml` usa `dynamic = ["version"]` e nao tem mais `version =`
  fixo em `[project]`. Prova:
  `python -c "import tomllib; d=tomllib.load(open('pyproject.toml','rb')); assert 'version' not in d['project']"`
- Guard test novo falha se `marketplace.json` ou `plugin.json` divergirem
  de `harness.__version__`. Prova: `pytest tests/test_version_sync.py -q`
- A fiacao `[tool.hatch.version].path` aponta pro arquivo certo
  (`src/harness/__init__.py`) e o valor de `__version__` nesse arquivo bate
  com `harness.__version__` importado em runtime (checagem sem depender de
  `pip`/`hatchling` em runtime — ambos indisponiveis pro boundary_guard
  deste projeto; gap registrado separadamente). Prova:
  `python -c "import tomllib, pathlib, harness; d = tomllib.load(open('pyproject.toml', 'rb')); path = d['tool']['hatch']['version']['path']; assert path == 'src/harness/__init__.py'; lines = pathlib.Path(path).read_text().splitlines(); value = next(l.split('=', 1)[1].strip().strip('\"') for l in lines if l.strip().startswith('__version__')); assert value == harness.__version__, (value, harness.__version__)"`
- Suite completa permanece verde. Prova: `pytest -q`

## Nao-objetivos
- Nao mexe no conteudo de `marketplace.json`/`plugin.json` alem do guard
  test — continuam arquivos editados manualmente.
- Nao adiciona pipeline de CI/GitHub Actions — guard fica local via
  `pytest`.

## Unknowns
(nenhum)
