# Handoff — 2026-07-27 — fechamento do dogfood venv-Windows (ondas 2–5) + consolidação de backlog

Continuação de `HANDOFF-2026-07-26-p0-fronteira-machine-local.md` (mantido no
repo como histórico — não apagar). Esta sessão fechou o backlog inteiro do
dogfood venv-Windows (itens 1–9, ondas 2 a 5), validou tudo contra um alvo real
com venv no Windows, e consolidou a documentação de planejamento do repo.

**Para quem continuar depois desta sessão:** o que resta do dogfood
venv-Windows está em `docs/project/BACKLOG-dogfood-venv-windows.md` (novo,
substitui os três documentos antigos). Leia a Seção 5 deste handoff antes de
mexer em qualquer coisa relacionada a `boundary_guard.py` — há uma regra nova de
projeto que se aplica a qualquer deny futuro.

---

## 1. O que foi feito

### 1.1 Ondas 2–4 do plano v2 — PR #31 (`b0e31c2`), v0.20.0

Itens 3, 4, 6, 7, 8 do backlog original, mais instrumentação de contagem de
ciclos (`harness.metrics`). Resumo técnico completo no corpo do PR #31 e no
`CHANGELOG.md`. Os pontos que mais custam a reconstruir:

- **Item 4** — normalização da forma de invocação (`python -m <bin>`,
  `.venv/{Scripts,bin}/<bin>`, `uv run <bin>` reduzem à mesma forma canônica,
  nos dois lados da comparação). O floor passou a avaliar a forma bruta **e**
  a normalizada — sem isso, o item converteria um furo latente
  (`.venv/Scripts/git.exe push` já atravessava o floor) em alcançável.
  `uv run --with <pacote>` foi definido para **não** normalizar.
- **Item 3** — `extra_allowed_commands` lido em runtime por um parser stdlib
  deliberadamente burro (a constante bakeada foi **removida**, com teste
  estrutural). `compile-session` compara a leitura do pyyaml com a do hook e
  avisa quando divergem.

### 1.2 Dogfood real contra o projeto-alvo do dogfood venv-Windows

Primeiro alvo real com as três condições do relato original: Python, venv,
Windows. A/B entre o guard de `origin/main` (v0.18.0) e o desta sessão, com
payloads `PreToolUse` reais via stdin — 6 decisões mudaram, todas dentro da
classe de equivalência de forma; nenhum floor se mexeu.

O dogfood achou 8 problemas (`docs/project/DOGFOOD-venv-windows-2026-07-27.md`),
**todos corrigidos** nesta sessão, no PR #31:

- **F1** (causa-raiz) — `requirements.txt` não era manifesto reconhecido pelo
  analyzer, mascarando F5 (o check de sombra de venv nunca disparava por falta
  de `test_command` inferido).
- **F2** — `pip` mapeava sempre para `pip install -e .`; agora considera a
  evidência (`requirements.txt` → `pip install -r requirements.txt`). O mapa
  de instalação, que estava **triplicado** em três módulos, virou fonte única
  em `src/harness/install_command.py`.
- **F3** — `preflight` ignorava correção manual do profile (`harness profile
  set`); agora a entrada marcada como correção humana vence a re-inferência.
- **F5** — resolvido pelo F1 (era o mesmo mecanismo mascarado).
- **F6** — a recusa de árvore suja para criar branch de contrato nomeia os
  arquivos sujos e as três saídas possíveis; antes só dizia "commit ou stash".
- **F7** — `test_glob` tinha duas fontes (`harness.yaml` × `repo-profile.json`)
  que podiam divergir; `compile-session` agora reconcilia, com a governança
  vencendo por escrita.
- **F8** (segurança) — os hooks de `harness compile` (`guard_tests`,
  `guard_test_runner`) ainda lançavam `python` nu, sem o `\|\| exit 2` — o
  Item 1/1b tinha corrigido só os três hooks do `compile-session`. Corrigido
  com `hook_command()`, o mesmo ponto único dos outros três.

### 1.3 Onda 5 decidida — postura C — PR #33 (`457a5b4`), v0.21.0

**Não haverá `harness allow-command`.** Liberar um comando novo e permanente é
editar `governance.extra_allowed_commands` do `.harness/harness.yaml`, no
terminal do usuário. Decisão do dono do repo, tomada **antes** do gate de
medição (que o plano v2 previa) — os itens 3, 4 e 6 já tinham reduzido a
demanda por comando novo a quase nada.

A condição anexada à decisão — o escape tem que ser trivial — motivou o
critério de projeto que passa a valer para qualquer deny futuro (ver Seção 5).
Entregue: a razão de deny devolve o bloco YAML pronto para colar
(`command_escape_hint()`/`suggested_allowlist_entry()` em `boundary_guard.py`),
`harness doctor` passa a acusar allowlist ilegível pelo parser mínimo do hook,
e o `init` deixa a chave comentada no `harness.yaml` gerado.

### 1.4 Remoção do nome do projeto-alvo — PR #32 (`efb7f09`)

Decisão do usuário: nenhuma referência ao nome do projeto que originou o
dogfood (o repo real com venv/Windows/proxy corporativo) deveria continuar no
repo. Rótulo canônico adotado: **"dogfood venv-Windows"**. 56 ocorrências
trocadas em 28 arquivos, três documentos renomeados
(`ROADMAP-dogfood-venv-windows.correction.*`). **Limite registrado e aceito
pelo usuário:** dez commits já publicados na `main` (e dois nomes de branch de
merge) continuam citando o nome — reescrever exigiria `filter-repo` +
force-push numa branch protegida, e o usuário decidiu não fazer isso.

### 1.5 Consolidação da documentação de planejamento (esta sessão, ao final)

Com o backlog do dogfood venv-Windows inteiro fechado, os três documentos que o
descreviam (`ROADMAP-dogfood-venv-windows.correction.{backlog,parecer-MAR,plano-v2}.md`)
foram substituídos por um único `BACKLOG-dogfood-venv-windows.md`, com o estado
atual e os dois itens residuais (nenhum bloqueante — ver o próprio arquivo).

Junto, outros dez documentos de planejamento **já encerrados** (backlogs de
Fase 1–4, do dogfood `elegant-heisenberg`, do dogfood de fricção 2026-07-18, e
dos issues #1 e #2–5) saíram do controle de versão — ver Seção 4. Ficaram:
`ROADMAP.md` (referenciado como base pelo `docs/roadmap-autonomous.md`, que
continua sendo o backlog vigente das Fases 5–7), `PLAN.md` (citado por
`file:line` em código de produção — `src/harness/doctor.py`,
`src/harness/settings_paths.py`, `tests/test_doctor.py` —, não é descartável),
os laudos `AUDIT-*.md`, o `BACKLOG-testes-isentos-2026-07-27.md` (ainda aberto,
9 itens) e os três `HANDOFF-*.md` anteriores.

---

## 2. Estado dos repos ao final desta sessão

| Repo | Branch | O que aconteceu | Push/merge? |
|---|---|---|---|
| `Harness-creator` | `main` | PRs #31, #32, #33 mergeados pelo usuário | sim |
| `Harness-creator` | (esta sessão) | consolidação de docs (este handoff + backlog novo + descarte) | branch nova, PR a abrir |
| projeto-alvo do dogfood venv-Windows | `main` | harness instalado e armado (decisão do usuário), árvore com 2 arquivos modificados (`frontend/app.js`, `frontend/styles.css`) | não tocado nesta sessão |

`main` do `Harness-creator` está em `457a5b4`, v0.21.0, 879 testes verdes,
`ruff` limpo.

---

## 3. O critério de projeto que esta sessão fixou

O usuário deu, ao decidir a postura C, o enquadramento que passa a valer para
qualquer regra nova do produto:

> um dos objetivos do harness é reduzir ao máximo a fricção, pois a ideia é
> deixar o Claude executando de forma autônoma por horas sem human in the
> loop, mas de forma segura. O harness deve barrar o mínimo.

Isso está registrado como memória de feedback
(`harness-deve-barrar-o-minimo`, no sistema de memória do agente). Antes de
propor qualquer deny/gate/aprovação nova: (1) isso trava a FORMA de fazer algo
já aprovado, ou compra governança de verdade? Se só a forma, não deveria
existir (foi o próprio Item 4). (2) quem for barrado resolve em segundos, com
instrução literal na mensagem, ou vai ter que descobrir? Se vai ter que
descobrir, a mensagem está incompleta.

---

## 4. Arquivos movidos para fora do controle de versão

Pasta `_descarte/`, na raiz do repo, listada no `.gitignore` (ver
`ROADMAP-dogfood-venv-windows.correction.backlog.md` e os outros conteúdos
dela para reconstruir raciocínio histórico se precisar — nada foi apagado, só
saiu do índice do git). Todos são backlogs de fases/dogfoods já **fechados**;
nenhum tem citação `file:line` a partir de código de produção (verificado por
grep antes da remoção — só citações narrativas em outros documentos
históricos, que ficam com um link para um arquivo que não está mais no repo,
mas isso não quebra nada executável):

- `ROADMAP-dogfood-elegant-heisenberg.correction.backlog.md`
- `ROADMAP-dogfood-friction.correction.backlog.md`
- `ROADMAP-dogfood-venv-windows.correction.backlog.md`
- `ROADMAP-dogfood-venv-windows.correction.parecer-MAR.md`
- `ROADMAP-dogfood-venv-windows.correction.plano-v2.md`
- `ROADMAP-fase1.backlog.md`
- `ROADMAP-fase1.correction.backlog.md`
- `ROADMAP-fase1.outcomes-report.md`
- `ROADMAP-fase2.backlog.md`
- `ROADMAP-fase3.backlog.md`
- `ROADMAP-fase4.backlog.md`
- `ROADMAP-issue1-friccao-sessao-real.correction.backlog.md`
- `ROADMAP-issues2-5-dogfood-story3.3.correction.backlog.md`

**Deliberadamente NÃO movidos**, com a razão de cada um:

- `PLAN.md` — citado por `file:line` (`:180-182`) em `doctor.py`,
  `settings_paths.py` e `tests/test_doctor.py` como a justificativa do path
  absoluto no comando de hook. Descartar quebraria a rastreabilidade de uma
  decisão de design ainda em vigor.
- `ROADMAP.md` — base declarada de `docs/roadmap-autonomous.md`, que é o
  backlog vigente das Fases 5–7 (fora de `docs/project/`, não tocado nesta
  sessão).
- `AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`,
  `AUDIT-harness-creator-2026-07-19.md` — laudos, não planos; são a fonte
  canônica de política citada por código e por outros docs.
- `BACKLOG-testes-isentos-2026-07-27.md` — ainda **aberto**, 9 itens
  pendentes, decisão explícita do usuário de deixá-los em aberto.
- `DOGFOOD-venv-windows-2026-07-27.md` — evidência recente (esta sessão),
  todos os 8 achados já corrigidos e registrados nele.
- Os três `HANDOFF-*.md` anteriores — texto de cada um pede explicitamente
  para não apagar ("mantido no repo como histórico").

---

## 5. Próximos passos sugeridos

1. **Abrir o PR** desta sessão (branch de consolidação de docs) — commit
   único, só documentação e `.gitignore`, sem mudança de comportamento.
2. **Nenhum item do dogfood venv-Windows está bloqueando nada.** Os dois
   resíduos (contagem de deny por comando; validação em sessão real no
   projeto-alvo) estão em `BACKLOG-dogfood-venv-windows.md`, ambos
   opcionais e de baixa prioridade.
3. Se for retomar o projeto-alvo do dogfood venv-Windows: decidir primeiro o
   destino do trabalho pendente (`frontend/app.js` sem `data.progress` — o commit
   `c4ba99d` daquele repo reescreveu o arquivo por cima da feature) antes de
   tentar `compile-session` de novo lá.
4. Backlog geral do produto que segue de pé, fora do escopo desta sessão:
   `BACKLOG-testes-isentos-2026-07-27.md` (9 itens) e as Fases 5–7 de
   `docs/roadmap-autonomous.md`.
