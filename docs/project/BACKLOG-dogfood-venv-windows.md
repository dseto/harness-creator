# Backlog consolidado — dogfood venv-Windows (repo Python com venv, no Windows, atrás de proxy corporativo)

**Substitui três documentos**, que saíram de versionamento em 2026-07-27 (ver
`docs/project/HANDOFF-2026-07-27-fechamento-dogfood-venv-windows.md`):
`ROADMAP-dogfood-venv-windows.correction.backlog.md` (conteúdo original dos
itens 1–9, com evidência e `file:line`), `…correction.parecer-MAR.md` (parecer
do comitê MAR) e `…correction.plano-v2.md` (repriorização e estado de entrega).
O conteúdo histórico dos três não foi perdido — está fora do controle de
versão, em `_descarte/docs-project/`, para quem precisar consultar o raciocínio
completo por trás de cada decisão.

Este documento é a fonte única daqui em diante: estado atual + o que
genuinamente resta.

---

## Estado — TODOS os itens do backlog original estão entregues ou decididos

| # | Item | Estado | Onde |
|---|---|---|---|
| 0 | Rota de auto-ampliação de superfície de comando (`add-file` + floor de `.harness/**`) | ✅ entregue | PR #28 |
| 1 | Hooks invocam `python` do PATH — guard falha aberto | ✅ entregue (+1b: sufixo `\|\| exit 2`) | PR #27, #28 |
| 2 | Preflight não verifica se `test_command` resolve no shell | ✅ entregue (por resolução, não execução) | PR #27 |
| 3 | `extra_allowed_commands` bakeado — mudar exige recompilar | ✅ entregue (lido em runtime + cross-check de gramática) | PR #31 |
| 4 | Match por prefixo trava a forma de invocação, não o binário | ✅ entregue (normalização + floor sobre a forma normalizada) | PR #31 |
| 5 | Mensagens de deny não apontam o escape que existe | ✅ entregue | PR #28 |
| 6 | Sem forma suportada de corrigir `repo-profile.json` | ✅ entregue (`harness profile set`) | PR #31 |
| 7 | PowerShell sem os escapes read-only/cd que o Bash tem | ✅ entregue | PR #31 |
| 8 | `settings.json` emite `Bash(<verify_cmd>)` sem forma prefixada | ✅ entregue (+ lint/typecheck/build/install) | PR #31 |
| 9 | `harness allow-command <cmd>` — ampliar superfície de comando | ✅ **decidido: postura C, sem CLI nova** | PR #33 |
| B1–B3 | Achados da auditoria MAR pós-onda-1 (case-sensitivity do floor, teste de desfecho do `\|\| exit 2`, sombra de venv no preflight) | ✅ entregues | PR #28 |
| F1–F8 | Achados do dogfood real em `miojo-simulator-3.0` (`DOGFOOD-miojo-simulator-2026-07-27.md`) | ✅ entregues | PR #31 |

**Suíte: 879 testes verdes, `ruff check src tests` limpo, v0.21.0.**

A decisão do Item 9 (postura C) foi tomada **antes** do gate de medição que o
plano previa, porque os itens 3, 4 e 6 já tinham atacado a maior parte da
demanda por três lados independentes (formas equivalentes de invocação,
runtime-read do YAML, e correção de ambiente fora do YAML). A condição que o
dono do repo anexou à decisão — o escape de comando tem que ser trivial — foi
entregue junto: a razão de deny agora devolve o bloco YAML pronto para colar,
com o comando já preenchido na forma canônica (ver `command_escape_hint()` /
`suggested_allowlist_entry()` em `src/harness/boundary_guard.py`).

---

## O que resta — dois itens, nenhum bloqueante

### 1. (BAIXO, opcional) Contar deny por superfície de comando

`harness.metrics` conta `disable`/`enable`/`compile-session`, que é o
workaround **antigo** do Item 9 (desligar o harness para editar o YAML). Depois
do Item 3, ninguém precisa mais desligar o harness para isso — então o contador
atual vai ler zero mesmo que a demanda residual por comandos novos continue
existindo. Ele mede "o kill-switch parou de ser usado", não "não há fricção".

Se um dia for preciso medir a demanda real por comando novo (por exemplo, para
reabrir a discussão B vs C com dado), o número certo é **deny por superfície de
comando**, contado dentro do próprio `boundary_guard` — é a janela certa,
porque acontece com o harness **ligado**. Não implementado; não há decisão
pendente que dependa disso hoje.

**Esforço:** S. **Prioridade:** baixa — só vale a pena se a decisão da postura C
precisar ser revisitada.

### 2. (BAIXO, opcional) Validar em sessão real dentro de `miojo-simulator-3.0`

O dogfood contra `C:\Projetos\miojo-simulator-3.0` validou o guard por payload
direto (`PreToolUse` via stdin), não por uma sessão real do Claude Code
trabalhando o contrato até o fim. Isso não bloqueia nada — a decisão da postura
C não dependia desse número —, mas é a validação mais forte que falta fazer se
alguém quiser reconfirmar o comportamento em condição de uso real.

Bloqueio conhecido, registrado no handoff: a árvore do alvo está suja (os dois
arquivos modificados são os `files[]` do próprio contrato
`frontend-progress-bar`) e o `frontend/app.js` atual não contém mais
`data.progress` — o commit `c4ba99d` daquele repo reescreveu o arquivo por
cima. O T-01 falharia de verdade até alguém decidir o que fazer com esse
conflito (retomar a feature, ou recomeçar o contrato).

**Esforço:** depende de decidir o destino do trabalho pendente naquele repo.
**Prioridade:** baixa — nenhuma decisão do harness-creator espera por isto.

---

## Onde está o raciocínio completo

Para qualquer decisão acima que precise de reconstrução (por que o floor
avalia a forma bruta E normalizada, por que `uv run --with` não normaliza, por
que a granularidade da entrada sugerida é binário+subcomando, etc.), o texto
integral — com `file:line`, evidência de execução e o parecer do comitê MAR —
está preservado fora do controle de versão, em
`_descarte/docs-project/ROADMAP-dogfood-venv-windows.correction.{backlog,plano-v2,parecer-MAR}.md`.
