---
slug: pip-install-command-boundary
approved_by: Daniel Seto
approved_at: 2026-07-23T21:15:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste"
---

# Spec: pip vira comando de instalação permitido (boundary_guard + settings + init scripts)

## Resumo executivo

Depois da correção do issue #14 (analyzer já infere `package_manager=pip`
quando não há lockfile), o harness ainda não sabe o que FAZER com esse
`pip` — nenhum dos 3 lugares que traduzem `package_manager.value` num
comando de instalação real tem entrada pra `pip`. Resultado prático: um
projeto Python sem lockfile nunca ganha um comando de instalação
utilizável (nem no hook de segurança que libera comandos, nem no
`.claude/settings.json` gerado, nem nos scripts `init.sh`/`init.ps1`).
Esta mudança fecha essas 3 lacunas com o mesmo comando (`pip install -e .`
— instalação editável do projeto local, o padrão pra projeto com
`pyproject.toml`/`setup.py` e sem lockfile), sem tocar em mais nada.

## Escopo
`package_manager.value -> comando de instalação` está duplicado em 3
lugares (mesmo mapeamento, comentado como tal em cada um), nenhum com
`"pip"`:
- `src/harness/templates.py::_INSTALL_COMMANDS` — usado por
  `render_init_scripts`/`install_templates` pra gerar `init.sh`/`init.ps1`.
- `src/harness/session_permissions.py::_INSTALL_COMMAND_BY_PACKAGE_MANAGER`
  — usado por `render_session_permissions` pra montar o `allow[]` do
  `.claude/settings.json` compilado.
- `src/harness/boundary_guard.py::INSTALL_COMMAND_BY_PACKAGE_MANAGER` —
  usado por `_collect_allowed_bash_commands` dentro do hook `PreToolUse`
  que de fato libera/bloqueia o `Bash` em runtime (é o gate real).

Adicionar `"pip": "pip install -e ."` aos 3 dicionários, na mesma
posição/estilo das entradas existentes (`npm`/`pnpm`/`yarn`/`uv`/`poetry`).

## Critérios de aceitação
- `package_manager={"value": "pip", ...}` em `.harness/repo-profile.json`
  faz o hook `boundary_guard` liberar exatamente `pip install -e .` (e
  continuar bloqueando qualquer outro subcomando `pip`, ex.:
  `pip install -e . && curl evil`).
  Prova: `pytest tests/test_boundary_guard.py -q`
- `render_session_permissions` com `package_manager.value == "pip"` gera
  `Bash(pip install -e .)` no `allow[]`.
  Prova: `pytest tests/test_session_permissions.py -q`
- `render_init_scripts`/`install_templates` com `package_manager.value ==
  "pip"` inclui `pip install -e .` em `init.sh` e `init.ps1` (não cai no
  "nenhum package manager detectado").
  Prova: `pytest tests/test_templates.py -q`
- Suite completa sem regressão.
  Prova: `pytest -q`

## Não-objetivos
- Não infere `pip` a partir de `requirements.txt` nem cria novo candidato
  de detecção no analyzer — isso é o issue #14, já resolvido separado.
- Não trata variantes de comando pip (`pip install -r requirements.txt`,
  `pip install .` sem `-e`) — escolhido `pip install -e .` como único
  comando, consistente com o par pyproject.toml/setup.py que o analyzer
  usa como evidência do fallback pip.
- Não adiciona novo package manager (ex.: `pipenv`, `conda`) fora do
  escopo do issue.

## Unknowns
(nenhum)
