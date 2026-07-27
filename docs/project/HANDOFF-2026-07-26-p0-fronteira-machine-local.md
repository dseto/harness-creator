# Handoff — 2026-07-26 — P0 da fronteira machine-local + dogfood real

Continuação de `HANDOFF-2026-07-20-v0.17-dogfood-story-3.3.md` (mantido no repo como
histórico — não apagar). Esta sessão produziu o laudo de footprint, implementou o **P0**
inteiro, e validou o resultado num projeto-alvo real do zero, implementando uma demanda
de verdade sob governança.

**Este documento existe para quem for implementar os itens 5–10 (P1/P2)** do backlog do
laudo `AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`. Leia a Seção 3 antes de tocar
em qualquer código: ela corrige premissas do laudo que a execução derrubou, e vários
itens ficam mais simples (ou parcialmente prontos) por causa disso.

---

## 1. O que foi feito

### 1.1 Laudo de footprint (`AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`)

Inventário de 31 artefatos que o harness cria no projeto-alvo, com 6 achados (F1–F6),
política canônica ("especificação, contrato e prova são versionados; saída de compilação
que carrega dado de máquina é machine-local") e backlog de 10 itens. F1 e F2 eram P0.

### 1.2 P0 implementado — commit `41a4f37`, branch `fix/p0-fronteira-machine-local`

Módulo novo `src/harness/settings_paths.py` como **ponto único** de acesso ao settings.
Os cinco escritores (`compiler`, `boundary_guard`, `session_start`, `stop_hook`,
`session_permissions`) passam por `prepare_managed_settings()` / `write_managed_settings()`
e gravam em `.claude/settings.local.json`. As regras de ignore vêm do produto, em arquivos
tool-owned (`.claude/.gitignore` novo, `.harness/.gitignore` estendido para
`compiled-state*.json` e `hooks/`). `harness audit` passa a auditar o arquivo machine-local.

Suíte: **676 passed**, ruff limpo.

### 1.3 Dogfood real — `C:\Projetos\elegant-heisenberg`

Instalação apagada e refeita do zero, depois uma demanda implementada sob governança
(contrato `busca-projetos`, 2 tarefas, TDD red→green, evidência gravada). Dois commits
na branch `contract/busca-projetos`: `b885d64` (reinstalação) e `243dad5` (a feature).

**O que o dogfood provou:** numa instalação do zero, o git rastreia só `harness.yaml`,
`repo-profile.json` e os dois `.gitignore`. Tudo machine-local fica coberto. Nenhum path
absoluto em arquivo versionável. O guard gerado enforça de verdade (testado por payload
direto no hook): ALLOW no arquivo declarado no contrato, DENY fora dele, DENY
incondicional em `.env` e `git push`.

---

## 2. Estado dos repos ao final desta sessão

| Repo | Branch | Commits desta sessão | Push? |
|---|---|---|---|
| `Harness-creator` | `fix/p0-fronteira-machine-local` | `41a4f37` | **não** |
| `elegant-heisenberg` | `contract/busca-projetos` | `b885d64`, `243dad5` | **não** |

As três branches são locais. Nenhum push foi dado — decisão do usuário.

Untracked deliberadamente deixado de fora do commit do P0:
`docs/project/ROADMAP-dogfood-savant-venv.correction.plano-v2.md` (é de outra sessão).

---

## 3. Correções de premissa — LEIA ANTES DE IMPLEMENTAR

Três coisas mudaram em relação ao que o laudo escreveu. Cada uma altera o escopo de
itens do P1/P2.

### 3.1 O produto é pré-produção: não existe base instalada, nunca migre

Decisão do usuário, nesta sessão: **a instalação do harness é sempre feita do zero.** Um
alvo em versão antiga se resolve apagando `.harness/` e `.claude/settings.json` e rodando
`harness compile` de novo — não se escreve código de migração.

Isso já teve efeito retroativo no P0: a migração one-shot que eu tinha implementado
(`migrate_team_settings` + transplante, ~150 linhas) foi **removida**, junto com o finding
`stale_managed_settings` do audit. O item 4 do backlog encolheu para a metade que
continuava necessária (o audit ler o arquivo certo).

**Consequência direta para o item 6:** o laudo pedia "ler o caminho novo com fallback
retrocompatível para o antigo" ao mover `claude-progress.md`/`init.*` para `.harness/`.
**Esse fallback não é mais necessário.** Corte-o do escopo — é código morto no dia em
que nasce.

### 3.2 A migração estava errada, e só o repo real mostrou

Vale registrar porque é o tipo de erro que se repete. A primeira versão da migração
*removia* as entradas gerenciadas do `settings.json` sem transplantá-las. No primeiro
`harness compile` sobre o `elegant-heisenberg` instalado, o `boundary_guard`, o
`session_start` e o `stop_hook` sumiram — só o `compile-session` os recria. Ou seja: um
`harness compile` isolado **desligava o guard principal em silêncio**, exatamente a falha
que o P0 existia para matar.

Nenhum teste unitário pegou isso; a assimetria só aparece num projeto que tem os cinco
hooks instalados. **Lição: para mudança que mexe na superfície de hooks, o teste real num
alvo já instalado não é opcional.**

### 3.3 `.gitignore` não desrastreia arquivo que já está no índice

Óbvio em retrospecto, mas custou uma investigação. No `elegant-heisenberg`,
`git check-ignore` dizia "não ignorado" para `.harness/compiled-state.json` mesmo com a
regra presente; `git check-ignore --no-index` mostrava que a regra **casava**. O que
sobrepunha era o índice — os arquivos vinham trackeados da instalação antiga.

Num projeto virgem isso não acontece (foi o caso testado, e funcionou). Mas **é
exatamente o problema do item 8**, no próprio repo do produto: uma regra nova no
`.gitignore` não tira `init.sh`/`init.ps1`/`claude-progress.md` do índice. Item 8 precisa
de `git rm --cached`, não só de regra.

---

## 4. Backlog restante — âncoras conferidas em 2026-07-26

Os `file:line` do laudo estão **desatualizados** para os arquivos que o P0 tocou. A tabela
abaixo tem as âncoras verificadas depois do commit `41a4f37`.

### Item 5 (P1) — guarda de colisão em `init.sh`/`init.ps1`

| | |
|---|---|
| Âncoras | `src/harness/templates.py:212-218` (escrita incondicional), `:37-39` (constantes) |
| Estado | não iniciado |

`install_templates` grava os dois na raiz **sem checar existência**, a cada
`compile-session`. Instalar o harness num projeto que já tem `init.sh` próprio apaga o
arquivo do usuário na primeira compilação.

**Faça junto com o item 6, não antes.** Se `init.*` sai da raiz para `.harness/`, a
colisão com o `init.sh` do usuário desaparece por construção — sobra apenas a decisão
menor de não sobrescrever um `.harness/init.sh` que o usuário tenha editado à mão.
Implementar o item 5 isolado é escrever uma guarda que o item 6 torna quase irrelevante.

### Item 6 (P1) — `claude-progress.md` → `.harness/progress.md`, `init.*` → `.harness/`

| | |
|---|---|
| Âncoras (escrita) | `templates.py:37-39` (constantes), `:193`, `:212-218`, `:247` |
| Âncoras (leitura) | `session_start.py:112-113`, `runtime_audit.py:37,81`, `verify.py:405-407`, `boundary_guard.py:606-616`, `lifecycle.py:36-46,74-122` |
| Estado | não iniciado |
| Escopo reduzido | **sem fallback retrocompatível** (ver 3.1) |

Ponto de atenção real, não teórico: `boundary_guard.py:606-616`
(`_is_progress_file_path` / `PROGRESS_FILE_NAME`) faz match **exato de raiz**, de
propósito — existe por causa do issue 3 do dogfood do `aegis_rpa_suite`, e a regra é que
um `claude-progress.md` em subdiretório NÃO casa. Ao mover para `.harness/progress.md`
essa regra precisa ser reescrita mantendo a não-recursividade, com teste dedicado. Se
regredir, o lifecycle passa a ser bloqueado pelo próprio guard no passo 12.

Segundo ponto, observado no `elegant-heisenberg`: a restauração de `claude-progress.md`
por contrato divergente (`templates.py:198-208`) só dispara quando o arquivo tem um header
`` Contrato: `slug` `` reconhecível. O arquivo real do projeto usa "Contrato ativo:" e por
isso **nunca foi tocado** — ficou apontando para um contrato encerrado há três demandas.
É comportamento documentado (conteúdo customizado não é sobrescrito), mas na prática
significa que o arquivo envelhece calado. Vale decidir, ao mover, se o parser passa a
reconhecer mais de um formato de header ou se o harness assume que o arquivo é do usuário.

### Item 7 (P1) — política canônica citada, contradição removida

| | |
|---|---|
| Estado | **parcialmente feito** |

Feito no P0: o comentário contraditório de `boundary_guard.py` ("`.harness/` no geral É
versionado") foi reescrito — hoje explica que `work/`, `feature_list.json` e `evidence/`
viajam, mas `hooks/`, `compiled-state*.json` e o sentinel não. Confirmado ausente por
grep.

**Falta:** `AGENTS.md` e `docs/plugin/TUTORIAL.md` citarem a Seção 3 do laudo como
referência canônica, em vez de cada documento reescrever a política com palavras próprias
(que foi a origem da divergência de F4).

### Item 8 (P2) — higiene do próprio repo

| | |
|---|---|
| Âncoras | `.gitignore:4-5` |
| Estado | não iniciado |

`.gitignore` atual do produto:

```
.harness/*
!.harness/harness.yaml
```

Dois problemas. Primeiro, `git ls-files` ainda traz `init.ps1`, `init.sh` e
`claude-progress.md` — saída do `compile-session` rodando em si mesmo, versionada junto do
código-fonte. Segundo, `.harness/*` ignora também o `.harness/.gitignore` que o produto
agora gera, ou seja: o repo do produto ignora justamente o arquivo que carrega as regras.

Realinhar à Seção 3 do laudo: ignorar explicitamente `compiled-state*.json`, `hooks/`,
`harness.disabled` e `scratch/` (ou delegar ao `.harness/.gitignore` gerado, versionando-o)
e **`git rm --cached`** nos três artefatos de raiz. Sem o `rm --cached`, a regra não tem
efeito (ver 3.3).

### Item 9 (P2) — documentação

| | |
|---|---|
| Âncoras | `docs/plugin/TUTORIAL.md` (tabela de artefatos), `README.md:161-173` (árvore) |
| Estado | **parcialmente feito** |

Feito no P0: a tabela do TUTORIAL ganhou coluna "versionar?", passou a marcar o que é
machine-local, e ganhou a seção "Por que metade não vai para o git" com o passo
`harness compile` após clonar. GUIDE, README, ARCHITECTURE e as skills
`init`/`compile`/`audit`/`plan` foram atualizados para o caminho novo.

**Falta:** (a) o inventário completo dos 31 artefatos no TUTORIAL — hoje a tabela cobre 8;
(b) a árvore do `README.md:161-173`, que continua dizendo `skills/ # init, audit, compile`
(existem 6: `init`, `audit`, `compile`, `plan`, `preflight`, `team`), cita "514+ testes"
(são 676) e omite `.harness/`, `AGENTS.md` e `docs/`.

### Item 10 (P2) — `harness doctor` cobre "clone sem compile"

| | |
|---|---|
| Âncoras | `src/harness/doctor.py:94-131` (`run_doctor`), `:61-70` (`_read_compiled_version`) |
| Estado | não iniciado |

Hoje o doctor compara versões (pip × compilado × plugin cache) e devolve
`{"ok": true, "issues": []}`. O trade-off aceito no P0 — clone novo não nasce governado —
está documentado em prosa, mas não é executável.

O check natural: `.harness/harness.yaml` presente **e** `.claude/settings.local.json`
ausente ⇒ issue "repositório clonado sem compilar; rode `harness compile`". Vale cobrir
também o caso do repo movido de lugar (comando de hook com path absoluto que não resolve
mais), que hoje aparece só como drift no `audit`.

---

## 5. Como refazer o teste real (referência de procedimento)

O `elegant-heisenberg` é projeto de teste; pode ser zerado à vontade (tudo recuperável no
git log). Procedimento usado nesta sessão:

```powershell
cd C:\Projetos\elegant-heisenberg
Copy-Item .harness\harness.yaml $env:TEMP\harness.yaml     # a spec e ENTRADA, preserve
Remove-Item -Recurse -Force .harness, .claude\settings.json, .claude\settings.local.json
New-Item -ItemType Directory .harness | Out-Null
Copy-Item $env:TEMP\harness.yaml .harness\harness.yaml
harness analyze --dir .
harness compile --dir .
harness audit --dir .
```

Depois, para o ciclo de contrato: `spec.md` + `Plans.md` em `.harness/work/<slug>/` →
aprovação humana no frontmatter → `harness compile-contract --slug <slug>` →
`harness compile-session` → TDD → `harness verify <id> --mark-passed`.

Quatro armadilhas encontradas, todas custaram tempo:

1. **`compile-session` exige working tree limpa** (`branch_per_contract`). Commite a
   reinstalação do harness antes, senão o comando aborta.
2. **O `boundary_guard` se aposenta da superfície de escrita quando o contrato fecha**
   (todas as features com `passes: true`) — comportamento projetado. Para testar o gate de
   contrato é preciso ter feature pendente; o runtime floor (`.env`, `git push`) continua
   negando incondicionalmente nos dois estados.
3. **`npm run test:ci` da suíte COMPLETA do `elegant-heisenberg` aborta** com erro fatal de
   heap do V8 (`ERR_IPC_CHANNEL_CLOSED`). É pré-existente e alheio ao harness. Use
   `npm --prefix frontend run test:ci -- --include=<spec>` como `verify_cmd`. Merece
   demanda própria naquele projeto.
4. **A sessão do Claude Code roda no repo do plugin, não no alvo** — os hooks do alvo não
   gateiam as tool calls desta sessão. Para provar enforcement, alimente o hook gerado por
   stdin:
   ```powershell
   '{"tool_name":"Edit","cwd":"C:\\Projetos\\elegant-heisenberg","tool_input":{"file_path":"..."}}' | python .harness\hooks\boundary_guard.py
   ```

---

## 6. Próximos passos sugeridos

1. **Push e PR** das três branches locais (decisão do usuário — não foi feito).
2. **Itens 5 + 6 juntos**, numa tarefa só (ver 4.1): o item 5 isolado vira quase nada
   depois do 6. É o maior bloco restante e o único com risco médio.
3. **Item 8 antes do 9**: o repo do produto contradizendo a própria política é o exemplo
   mais visível de F5, e a correção é curta (`.gitignore` + `git rm --cached`).
4. **Item 10** fecha o trade-off do P0 com um check executável em vez de um parágrafo de
   documentação — barato e de alto retorno para quem clona.
5. **Item 7 e 9** são o resíduo de documentação; agrupe numa passada só.
