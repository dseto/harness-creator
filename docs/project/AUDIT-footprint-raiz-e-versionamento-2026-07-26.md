# Auditoria — footprint na raiz e política de versionamento — 2026-07-26

Demanda: analisar (a) se os arquivos que o harness-creator cria na raiz do projeto-alvo
precisam mesmo nascer lá e (b) quais precisam entrar no controle de versão.

Escopo desta rodada: **somente o laudo**. Nenhuma mudança de código, config ou
documentação existente. As Seções 4 e 5 são plano e backlog, não execução.

Método: leitura do código-fonte (`src/harness/`, `skills/`) para levantar todo caminho de
escrita no projeto-alvo, cruzada com o estado real de dois repositórios que já rodaram o
harness — o próprio `Harness-creator` (dogfood) e `C:\Projetos\aegis_rpa_suite`
(projeto-alvo de terceiro). As duas evidências de vazamento da Seção 2 vêm de `git ls-files`
real, não de leitura estática.

---

## 1. Inventário — o que o harness cria no projeto-alvo

31 artefatos. "Raiz?" só se aplica a artefatos de nível raiz; `—` = mora em subdiretório.

| # | Caminho | Criado por | Natureza | Regenerado por | Raiz? | Versionar? |
|---|---------|------------|----------|----------------|-------|------------|
| 1 | `.harness/` | implícito no `mkdir` de todo escritor (`compiler.py:358`, `contract.py:574`, `analyzer.py:544`) | container | qualquer comando | — | n/a |
| 2 | `.harness/harness.yaml` | Claude via `skills/init/SKILL.md:38-53` (Write) | **autorado** (entrevista) | nunca — é a *entrada* de `compile` (`compiler.py:311-316`) | — | **SIM** |
| 3 | `.harness/hooks/` | `compiler.py:334-335`, `boundary_guard.py:2300-2301` | container | compile / compile-session | — | não |
| 4 | `.harness/hooks/guard_tests.py` | `compiler.py:105,337-339` | gerado | `harness compile` (sempre sobrescreve) | — | não |
| 5 | `.harness/hooks/guard_test_runner.py` | `compiler.py:107-110,337-339` | gerado | `harness compile`, só se `enforce_tdd`; senão `unlink` (`:343-345`) | — | não |
| 6 | `.harness/hooks/boundary_guard.py` | `boundary_guard.py:2302-2308` | gerado | `harness compile-session` (`cli.py:350`) | — | não |
| 7 | `.harness/hooks/session_start.py` | `session_start.py:196-197` | gerado | `harness compile-session` (`cli.py:353`) | — | não |
| 8 | `.harness/hooks/stop_hook.py` | `stop_hook.py:308-309` | gerado | `harness compile-session` (`cli.py:354`) | — | não |
| 9 | `.harness/compiled-state.json` | `compiler.py:356-366` | **estado de máquina** | `harness compile` | — | **NÃO — F2** |
| 10 | `.harness/compiled-state-session.json` | `boundary_guard.py:2383-2386`, `session_start.py:232-235`, `stop_hook.py:344-347`, `session_permissions.py:283-286` | **estado de máquina** | `harness compile-session` | — | **NÃO — F2** |
| 11 | `.harness/.gitignore` | `boundary_guard.py:2326-2335` | gerado, append-only idempotente | `compile-session` | — | **SIM** (é a própria regra; sem versionar, o ignore não viaja) |
| 12 | `.harness/scratch/` | `boundary_guard.py:2315-2316` | container efêmero | `compile-session` | — | não |
| 13 | `.harness/scratch/.gitignore` | `boundary_guard.py:2317-2319` (`"*\n!.gitignore\n"`, não sobrescreve existente) | gerado | — | — | **SIM** (auto-ignora o resto da pasta) |
| 14 | `.harness/repo-profile.json` | `analyzer.py:541-548` (`REPO_PROFILE_PATH`, `analyzer.py:35`) | gerado, determinístico dos manifestos | `harness analyze` (`cli.py:193-196`) | — | **SIM** |
| 15 | `.harness/work/` | Claude via skill `plan` (`WORK_DIR`, `contract.py:140`) | container | — | — | n/a |
| 16 | `.harness/work/<slug>/spec.md` | Claude via `skills/plan/SKILL.md:54-64` | **autorado** (contrato) | nunca | — | **SIM** |
| 17 | `.harness/work/<slug>/Plans.md` | Claude via skill `plan`; edição cirúrgica por `contract.py:420-422` | autorado + patch de máquina | nunca | — | **SIM** |
| 18 | `.harness/feature_list.json` | `contract.py:574-577`; mutado por `verify.py:446-448` | gerado do contrato | `harness compile-contract` (`cli.py:218`) | — | **SIM** |
| 19 | `.harness/evidence/<id>.json` | `verify.py:398-402` (`EVIDENCE_DIR`, `verify.py:58`) | **prova de execução** | `harness verify` | — | **SIM** |
| 20 | `.harness/review/<id>.json` | `review.py:103-108` (`REVIEW_DIR`, `review.py:53`) | estado da máquina de review | `harness review` | — | **SIM** |
| 21 | `.harness/LIFECYCLE.md` | `lifecycle.py:191-193` (`LIFECYCLE_DETAIL_PATH`, `:25`) | gerado, determinístico | `compile-session` (`cli.py:351`) | — | **SIM** (`AGENTS.md` versionado aponta pra ele) |
| 22 | `.harness/TEAM.md` | `teams.py:537-539` (`TEAM_DETAIL_PATH`, `:390`) | gerado, determinístico | `harness team generate` | — | **SIM** |
| 23 | `.harness/team/manifest.json` | `teams.py:557-566` (`TEAM_MANIFEST_PATH`, `:391`) | gerado, sempre sobrescreve | `harness team generate` | — | **SIM** |
| 24 | `.harness/harness.disabled` | `killswitch.py:47-57` (`SENTINEL_RELATIVE_PATH`, `:35`) | sentinela de máquina | `harness disable`/`enable` | — | **NÃO** (já ignorado por #11) |
| 25 | `.claude/settings.json` | `compiler.py:369-406`, `boundary_guard.py:2339-2372`, `session_start.py:205-227`, `stop_hook.py:317-338`, `session_permissions.py:265-278` | merge gerenciado em arquivo possivelmente autorado | `compile` (fatias gerenciadas) + `compile-session` | — | **NÃO — F1** |
| 26 | **`AGENTS.md`** | `compiler.py:409-424`, `lifecycle.py:175-189`, `teams.py:521-535` | **híbrido**: 3 blocos gerenciados + prosa humana | `compile` (só o bloco `harness:begin/end`) | **SIM — justificada** | **SIM** |
| 27 | `.claude/agents/<role>.md` | `teams.py:313-329` (delimitadores `:229-230`) | bloco gerenciado | `harness team generate` | — | **SIM** |
| 28 | `.claude/skills/<role>/SKILL.md` | `teams.py:354-371` (delimitadores `:232-233`) | bloco gerenciado | `harness team generate` | — | **SIM** |
| 29 | **`claude-progress.md`** | `templates.py:193-208` | runtime-mutável: esqueleto gerado 1×, depois escrito pelo agente | `compile-session` (só se ausente ou contrato divergente) | **NÃO — F3** | SIM (após mover) |
| 30 | **`init.sh`** | `templates.py:212-214` | gerado, determinístico do `repo-profile.json` | `compile-session` — **sempre sobrescreve** | **NÃO — F3** | SIM (após mover) |
| 31 | **`init.ps1`** | `templates.py:216-218` | idem | idem | **NÃO — F3** | SIM (após mover) |

Estado não-arquivo também criado: branch git `contract/<slug>` (`branching.py:46-82`, gated por
`governance.branch_per_contract`, `config.py:34`).

### Leituras que a tabela obriga

- **Só 2 dos 5 artefatos de raiz têm justificativa.** `AGENTS.md` é convenção externa (todo
  agente lê da raiz) e `.claude/` é exigência do Claude Code. `claude-progress.md`, `init.sh`
  e `init.ps1` não são lidos por nada fora do próprio harness — a raiz é escolha arbitrária,
  não requisito.
- **`AGENTS.md` tem três donos independentes.** `compiler.py:43-44`
  (`harness:begin/end`), `lifecycle.py:22-23` (`harness:lifecycle:begin/end`) e
  `teams.py:387-388` (`harness:team:begin/end`) escrevem blocos com delimitadores próprios no
  mesmo arquivo. Se ausente, cada um dos três cria o arquivo com o mesmo cabeçalho
  (`compiler.py:422`, `lifecycle.py:188`, `teams.py:534`).
- **`harness compile` regenera apenas 5 coisas** (`compiler.py:309-330`): os dois
  `guard_*.py`, as fatias gerenciadas de `.claude/settings.json`, o bloco de `AGENTS.md` e o
  `compiled-state.json`. Todo o resto pertence a `compile-session`, `compile-contract`,
  `analyze`, `verify`, `review`, `team generate` ou `disable`. Nenhum documento atual diz isso —
  a tabela de `docs/plugin/TUTORIAL.md:61-69` sugere que `compile` produz tudo.
- **Negativas verificadas** (nenhuma ocorrência em `src/` ou `skills/`): o tool nunca cria nem
  edita `CLAUDE.md` (só lê — `analyzer.py:83`), nunca escreve `.claude/settings.local.json`, e
  **nunca toca no `.gitignore` da raiz do alvo**. Este último é decisão explícita de design
  (`boundary_guard.py:119-121`). `preflight.py:311-328` só *checa* a presença do `.gitignore` e
  emite um texto de fix; não escreve.
- **Nenhum lock nem cache** é criado no alvo. `feature_list.json` é gravado sem lock
  (`verify.py:419-421`).

---

## 2. Achados

### F1 — P0 — `.claude/settings.json` é machine-local mas não é tratado como tal

O comando de hook gravado no `settings.json` carrega o caminho absoluto do repositório:

```
python "C:\Projetos\aegis_rpa_suite\.harness\hooks\boundary_guard.py"
```

Escrito por `compiler.py:369-406` e `boundary_guard.py:2339-2372`. O path absoluto é decisão
deliberada e defensável (`docs/project/PLAN.md:180-182`: cmd.exe não expande `$VAR`; repo
movido vira drift que o `harness audit` acusa). **O defeito não é o path absoluto — é a
consequência não assumida**: o arquivo virou machine-local e ninguém marcou isso em lugar nenhum.

Evidência de que já quebrou na prática — em `C:\Projetos\aegis_rpa_suite`:

```
$ git ls-files .claude/settings.json
.claude/settings.json
```

O arquivo está **commitado**, com o path absoluto acima. Consequência: um clone em qualquer
outro caminho ou OS carrega um `PreToolUse` que não resolve — **o repositório parece governado e
os guards não rodam**. É falha silenciosa: o modo de falha visível seria o hook recusar; o modo
real é o hook não existir.

Agravante: o mesmo arquivo commitado (63 entradas em `permissions.allow`) concede

```
Edit(C:/Projetos/TestePortalSegura/tests/cenario_principal/code/bot_producao.py)
Write(C:/Projetos/TestePortalSegura/tests/cenario_principal/code/bot_producao.py)
```

— superfície de **outro projeto**, de outra máquina, gravada no histórico do `aegis_rpa_suite`.
Sob a promessa de `docs/plugin/TUTORIAL.md:88-90` ("blast radius auditável… `git diff` mostra
exatamente o que foi autorizado"), isso é o oposto: o diff autoriza um raio que não existe no
repositório que o carrega.

### F2 — P0 — `compiled-state*.json` são estado de máquina sem regra de ignore

`.harness/compiled-state.json` (`compiler.py:356-366`) registra `managed_hook_commands` com path
absoluto. `.harness/compiled-state-session.json` (`boundary_guard.py:2383-2386` e mais 3
escritores) registra `repo_root` absoluto e `managed_session_permissions` — a superfície de
uma sessão específica.

No `aegis_rpa_suite`, `git ls-files .harness/compiled-state-session.json` retorna o arquivo:
**commitado**, com os mesmos paths de `C:/Projetos/TestePortalSegura/`.

Nenhum dos dois é coberto por qualquer regra de ignore que o tool escreva. O único
`.harness/.gitignore` gerado (`boundary_guard.py:2326-2335`) contém uma linha só:
`harness.disabled`.

### F3 — P1 — `init.sh`/`init.ps1` poluem a raiz e sobrescrevem sem aviso

`templates.py:212-218` grava os dois na raiz **incondicionalmente**, a cada `compile-session`
— sem checar existência, sem marcador de bloco gerenciado, sem backup. A docstring assume isso
como propriedade desejável (`templates.py:182-183`: "determinísticos: sempre (re)gravados").

`init.sh` é um dos nomes de arquivo de raiz mais comuns que existe. Instalar o harness num
projeto que já tem `init.sh` próprio **apaga o arquivo do usuário na primeira compilação**.
Não há caminho de recuperação além do git — e se o projeto não versiona ainda, não há nem isso.

`claude-progress.md` é menos grave (só é escrito se ausente ou se o contrato divergiu —
`templates.py:193-208`), mas ocupa a raiz sem necessidade: quem o lê é
`session_start.py:106`, `runtime_audit.py:37,81`, `verify.py:405-407` e o próprio guard
(`boundary_guard.py:604-616`, que faz match **exato** de raiz de propósito). Nenhum consumidor
externo.

### F4 — P1 — política de versionamento contraditória e sem ADR

Não existe ADR no repositório. A regra vive em duas fontes que se contradizem:

- `src/harness/boundary_guard.py:2321-2325`: "`.harness/` no geral **É versionado** (work/,
  feature_list.json viajam pra branch), então o ignore precisa ser explícito por arquivo."
- `.gitignore:4-5` do próprio produto: `.harness/*` + `!.harness/harness.yaml` — ou seja,
  **nada** de `.harness/` é versionado além do yaml.

A única declaração explícita da intenção está numa mensagem de commit (`40808be`, 2026-07-22):
"versiona só `.harness/harness.yaml`; hooks e `settings.json` (paths absolutos, machine-local)
permanecem ignorados, regenerados por compile". Mensagem de commit não é contrato: nada
propaga essa regra para o projeto-alvo, e o comentário em código diz o contrário.

Resultado observável: **cada projeto-alvo decide sozinho**, e decide errado. No
`aegis_rpa_suite` foi commitado tudo, inclusive F1 e F2.

### F5 — P2 — o próprio repo do produto versiona seus artefatos gerados

`git ls-files` no `Harness-creator` traz `init.ps1`, `init.sh` e `claude-progress.md`
misturados ao código-fonte do produto. São saída do `compile-session` rodando em si mesmo,
não fonte. Efeito colateral do `.gitignore:4` cobrir só `.harness/*`: os três artefatos de
raiz ficaram de fora da regra.

Segundo efeito do mesmo `.gitignore:4`: ele ignora também `.harness/.gitignore` — isto é, no
modelo de correção tool-owned (D3), o produto estaria ignorando justamente o arquivo que
carrega as regras.

### F6 — P2 — documentação descreve 7 dos 31 artefatos, sem coluna de versionamento

`docs/plugin/TUTORIAL.md:61-69` lista 7 artefatos e chama `.claude/settings.json` de saída
normal ("Permissions compiladas que o Claude Code aplica sozinho"), sem dizer que é
machine-local. Só `.harness/harness.yaml` recebe a marca "versionável" — por omissão, o leitor
conclui que o resto também é.

`README.md:161-173` está defasado: a árvore cita `skills/ # init, audit, compile` (existem 6:
`init`, `audit`, `compile`, `plan`, `preflight`, `team`) e omite `.harness/`, `AGENTS.md` e
`docs/`.

---

## 3. Política canônica

Regra única, que resolve F4:

> **Especificação, contrato e prova são versionados. Saída de compilação que carrega dado de
> máquina é machine-local e regenerada por `compile`.**

**Critério de decisão** (aplicável a artefato futuro, em ordem):

1. Contém path absoluto, timestamp de execução, ou identidade de máquina/sessão → **local**.
2. É entrada humana, contrato aprovado ou prova de execução → **versionado**.
3. É derivada pura de arquivo versionado → **local se drift tiver consequência de
   governança; versionado se for conveniência**. (Hook em drift = brecha de segurança
   silenciosa → local. `init.sh` em drift = comando de instalação velho → versionado, porque é
   útil antes do primeiro `compile`.)

**Classificação resultante:**

| Versionado | Machine-local (ignorado) |
|---|---|
| `.harness/harness.yaml` | `.harness/compiled-state.json` |
| `.harness/work/**` (`spec.md`, `Plans.md`) | `.harness/compiled-state-session.json` |
| `.harness/feature_list.json` | `.harness/hooks/**` |
| `.harness/evidence/**` | `.harness/harness.disabled` *(já)* |
| `.harness/review/**` | `.harness/scratch/**` *(já)* |
| `.harness/repo-profile.json` | `.claude/settings.local.json` |
| `.harness/LIFECYCLE.md`, `.harness/TEAM.md`, `.harness/team/manifest.json` | |
| `.harness/.gitignore`, `.harness/scratch/.gitignore` | |
| `.claude/agents/*.md`, `.claude/skills/*/SKILL.md` | |
| `AGENTS.md` | |
| `.harness/progress.md`, `.harness/init.sh`, `.harness/init.ps1` *(após D2)* | |

**Trade-off assumido em `hooks/**` local**: um clone novo não nasce governado — precisa de
`harness compile`. Isso já é verdade hoje de qualquer jeito, porque o `settings.json`
(D1: `settings.local.json`) carrega path absoluto e nunca sobrevive a um clone. Versionar os
hooks só criaria uma segunda fonte de verdade capaz de divergir de `harness.yaml` sem que
ninguém perceba. O passo "rodar `harness compile` após clonar" precisa virar documentação
explícita e check do `harness doctor`.

---

## 4. Plano de correção (não executado nesta rodada)

### D1 — todo output gerenciado passa a ser escrito em `.claude/settings.local.json`

- `src/harness/session_start.py:47`, `src/harness/stop_hook.py:71`,
  `src/harness/session_permissions.py:81` — trocar a constante `SETTINGS_FILE` de
  `.claude/settings.json` para `.claude/settings.local.json` — outcome: as três instalações de
  hook de sessão param de gravar path absoluto em arquivo versionável.
- `src/harness/compiler.py:370` e `src/harness/boundary_guard.py:2339` — substituir o literal
  inline `target_dir / ".claude" / "settings.json"` por uma constante compartilhada única (não
  existe hoje; esses dois são os únicos escritores sem constante) — outcome: o destino do merge
  passa a ter uma fonte de verdade só, e a troca do D1 não pode ficar pela metade.
- `src/harness/compiler.py:369-406` — adicionar migração one-shot: ao compilar, remover de
  `settings.json` as entradas gerenciadas antigas usando `compiled-state.json`/
  `compiled-state-session.json` como registro, antes de escrever em `settings.local.json` —
  outcome: projeto já instalado não fica com hook duplicado (um morto no `settings.json`
  commitado, um vivo no local).
- `src/harness/audit.py:106` — passar a ler os dois arquivos ao detectar drift, e emitir
  finding se ainda houver entrada gerenciada no `settings.json` — outcome: `harness audit`
  denuncia repositório em estado pré-migração em vez de dar verde falso.
- `docs/plugin/TUTORIAL.md` + `README.md` — documentar que clone novo exige `harness compile`
  antes da primeira sessão, e que `harness doctor` cobre isso — outcome: o trade-off da Seção 3
  vira instrução, não surpresa.

**Trade-off aceito e explícito**: permissions deixam de viajar no clone. A auditabilidade do
raio de impacto continua garantida pelos artefatos versionados (`harness.yaml`, `work/**`,
`feature_list.json`), que são a fonte, não a compilação.

### D2 — `claude-progress.md` e `init.*` saem da raiz

- `src/harness/templates.py:37-39` — `CLAUDE_PROGRESS_FILE` → `.harness/progress.md`,
  `INIT_SH_FILE` → `.harness/init.sh`, `INIT_PS1_FILE` → `.harness/init.ps1` — outcome: a raiz
  do projeto-alvo passa a receber apenas `AGENTS.md`.
- `src/harness/templates.py:212-218` — adicionar guarda de colisão: não sobrescrever `init.*`
  pré-existente que não seja gerenciado pelo harness (marcador em cabeçalho ou registro em
  `compiled-state-session.json`) — outcome: fecha F3; projeto com `init.sh` próprio não perde o
  arquivo.
- `src/harness/session_start.py:106`, `src/harness/runtime_audit.py:37,81`,
  `src/harness/verify.py:405-407`, `src/harness/templates.py:227-272` — ler o caminho novo com
  fallback retrocompatível para o antigo na raiz — outcome: projeto já instalado continua
  funcionando sem migração manual.
- `src/harness/boundary_guard.py:604-616` — `_is_progress_file_path` passa a casar
  `.harness/progress.md`, mantendo o match exato (não-recursivo) e o fallback do caminho antigo;
  a regra existe por causa do issue 3 do dogfood `aegis_rpa_suite` e não pode regredir —
  outcome: o guard continua permitindo a escrita que o próprio lifecycle exige.
- `src/harness/lifecycle.py:36-46,74-122` — atualizar os passos 2, 3 e 12 do texto do
  lifecycle para os caminhos novos — outcome: `AGENTS.md` e `.harness/LIFECYCLE.md` param de
  apontar para arquivos que não existem mais.
- `tests/` — teste dedicado para a guarda de colisão de `init.*` e para o fallback de leitura
  do caminho antigo — outcome: a migração é reversível com prova, não com confiança.

### D3 — regras de ignore em arquivos tool-owned

- `src/harness/boundary_guard.py:2326-2335` — estender o gerador de `.harness/.gitignore`
  (hoje escreve só `harness.disabled`) para incluir `compiled-state.json`,
  `compiled-state-session.json` e `hooks/`, mantendo o padrão idempotente e não-destrutivo
  (só adiciona linha ausente, preserva o resto) — outcome: fecha F2 sem tocar no `.gitignore`
  da raiz do usuário.
- `src/harness/boundary_guard.py` (novo, mesmo padrão de `:2317-2319`) — criar
  `.claude/.gitignore` com `settings.local.json` — outcome: fecha F1; o arquivo com path
  absoluto nasce ignorado, sem depender do gitignore global da máquina do usuário (que hoje é
  o único motivo de o dogfood parecer limpo).
- Decisão preservada: o `.gitignore` da raiz do alvo continua intocado
  (`boundary_guard.py:119-121`).

### D4 — higiene do próprio repositório (F5)

- `.gitignore:4-5` — realinhar à Seção 3: em vez de `.harness/*` + exceção única, ignorar
  explicitamente `compiled-state*.json`, `hooks/`, `harness.disabled`, `scratch/` (ou delegar
  ao `.harness/.gitignore` gerado, versionando-o) — outcome: o produto passa a demonstrar a
  própria política em vez de contradizê-la.
- `init.ps1`, `init.sh`, `claude-progress.md` (raiz) — `git rm --cached` e ignorar — outcome:
  o repositório do produto para de versionar a saída do `compile-session` rodando em si mesmo.

### D5 — documentação (F6)

- `docs/plugin/TUTORIAL.md:61-69` — substituir a tabela de 7 linhas pelo inventário da Seção 1,
  com coluna "versionar?" e a marcação explícita de machine-local — outcome: o usuário deixa de
  concluir por omissão que tudo é versionável.
- `README.md:161-173` — atualizar a árvore (6 skills, `.harness/`, `AGENTS.md`, `docs/`) —
  outcome: a estrutura documentada volta a corresponder ao repositório.
- Este laudo passa a ser a referência canônica de política; a Seção 3 deve ser citada de
  `AGENTS.md` e do `TUTORIAL.md` em vez de reescrita.

---

## 5. Backlog priorizado

**Status (2026-07-27): backlog inteiro entregue — P0, P1 e P2.** O P0 (itens
1–4) foi implementado em 2026-07-26: a fronteira vive em
`src/harness/settings_paths.py` (destino único + `.gitignore` tool-owned), com
cobertura em `tests/test_settings_paths.py` e testes de integração em
`test_compiler.py`, `test_boundary_guard.py` e `test_audit.py`. Os itens 5–10
saíram em 2026-07-27, na sequência recomendada pelo handoff
`HANDOFF-2026-07-26-p0-fronteira-machine-local.md`: 5+6 numa tarefa só, depois
8, 10 e o resíduo de doc (7 e 9).

**Delta do inventário:** a Seção 1 fotografa 31 artefatos no dia do laudo. O
P0 acrescentou o 32º (`.claude/.gitignore`), e o item 6 mudou o caminho de
três (`claude-progress.md` → `.harness/progress.md`, `init.sh`/`init.ps1` →
`.harness/`). A tabela abaixo registra isso; o inventário vigente, com os 32
caminhos atuais, está em `docs/plugin/TUTORIAL.md`.

**Correção de premissa (mesma data, decisão do usuário):** o produto é
**pré-produção** e a instalação é sempre feita do zero — não existe base
instalada. Isso invalidou a metade "migração" do item 1 e o item 4 inteiro,
que só existiam para o alvo já instalado. O `.claude/settings.json` deixou
simplesmente de ser lido e escrito pelo harness; alvo em versão antiga se
resolve apagando `.harness/` e `.claude/settings.json` e recompilando.

| # | Item | Arquivo | Prio | Esforço | Risco | Outcome |
|---|------|---------|------|---------|-------|---------|
| 1 ✅ | Output gerenciado migra para `settings.local.json` + constante única (migração one-shot **descartada** — sem base instalada) | `session_start.py:47`, `stop_hook.py:71`, `session_permissions.py:81`, `compiler.py:370`, `boundary_guard.py:2339` | **P0** | M | médio | Path absoluto de máquina para de nascer em arquivo versionável; clone deixa de carregar hook morto que finge governança. |
| 2 ✅ | `.claude/.gitignore` com `settings.local.json` | `settings_paths.py` (chamado por `compiler.py` e `boundary_guard.py`) | **P0** | S | baixo | Arquivo machine-local nasce ignorado sem depender do gitignore global do usuário. |
| 3 ✅ | `.harness/.gitignore` cobre `compiled-state*.json` e `hooks/` | `settings_paths.py::ensure_machine_local_gitignores` | **P0** | S | baixo | Fecha F2; estado de sessão de uma máquina para de entrar no histórico do alvo. |
| 4 ~ | `harness audit` denuncia entrada gerenciada residual em `settings.json` — **descartado**; sobrou só a metade necessária: o audit passa a ler o `settings.local.json` (senão acusa `missing_settings` em projeto correto) | `audit.py` | **P0** | S | baixo | Premissa (base instalada em estado pré-migração) não existe. |
| 5 ✅ | Guarda de colisão em `init.*` — resolvida por `MANAGED_MARKER` (2ª linha de todo script gerado); `init.*` sem o marcador é preservado e reportado por `manual_init_scripts`/CLI | `templates.py` | **P1** | S | baixo | Projeto com `init.sh` próprio deixa de perder o arquivo — e, com o item 6, a colisão na raiz nem chega a existir. |
| 6 ✅ | `claude-progress.md` → `.harness/progress.md` e `init.*` → `.harness/` — **sem fallback retrocompatível** (produto pré-produção, ver correção de premissa acima) | `templates.py`, `session_start.py`, `boundary_guard.py`, `runtime_audit.py`, `verify.py`, `lifecycle.py`, `cli.py` | **P1** | M | médio | Raiz do projeto-alvo passa a receber só `AGENTS.md`. `_is_progress_file_path` continua match EXATO (não-recursivo), agora sobre `.harness/progress.md`, com teste dedicado. |
| 7 ✅ | Política canônica citada em `AGENTS.md` (seção "O que entra no git"), `TUTORIAL.md` e `GUIDE.md`; comentário contraditório removido no P0 | `AGENTS.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/GUIDE.md` | **P1** | S | baixo | Fecha F4: os documentos apontam para a Seção 3 em vez de reescrevê-la. |
| 8 ✅ | `.gitignore` do produto realinhado (deixou de ignorar `.harness/*` — e com ele o próprio `.harness/.gitignore`); `init.*` removidos com `git rm --cached`, `claude-progress.md` movido para `.harness/progress.md`; `work/**`, `evidence/**`, `feature_list.json`, `repo-profile.json`, `LIFECYCLE.md` passam a ser versionados | `.gitignore`, `.harness/`, `.claude/.gitignore` | **P2** | S | baixo | O produto passa a demonstrar a própria política; `git check-ignore` confirma `compiled-state*`, `hooks/`, `harness.disabled` e `settings.local.json` ignorados por regra do PRODUTO, não do gitignore global da máquina. |
| 9 ✅ | Inventário dos 32 artefatos + coluna "versionar?" no TUTORIAL; árvore do README atualizada (6 skills, 685 testes, `.harness/` e `docs/`) | `docs/plugin/TUTORIAL.md`, `README.md` | **P2** | M | baixo | Documentação cobre 32 artefatos em vez de 8, marca o que é machine-local e diz que `compile` regenera só 5 coisas. |
| 10 ✅ | `harness doctor` cobre "clone sem compile" (`harness.yaml` presente + `settings.local.json` ausente) e "repo movido de lugar" (comando de hook apontando para script inexistente) | `doctor.py`, `tests/test_doctor.py` | **P2** | M | baixo | O trade-off de não versionar hooks vira check executável, não instrução perdida em doc. |

---

## 6. Reprodução das evidências

Todos os comandos abaixo são leitura. PowerShell 5.1.

```powershell
# F1 e F2 — vazamento no projeto-alvo real
git -C C:\Projetos\aegis_rpa_suite ls-files .claude/settings.json .harness/compiled-state-session.json
Select-String -Path C:\Projetos\aegis_rpa_suite\.claude\settings.json -Pattern 'C:[\\/]'
```

```powershell
# F4 — a contradição, lado a lado (-Encoding UTF8 obrigatório: PS 5.1 assume ANSI e corrompe acento)
Get-Content C:\Projetos\Harness-creator\.gitignore | Select-Object -First 5
Get-Content C:\Projetos\Harness-creator\src\harness\boundary_guard.py -Encoding UTF8 | Select-Object -Skip 2320 -First 5
```

```powershell
# F5 — artefatos gerados versionados no próprio produto
git -C C:\Projetos\Harness-creator ls-files | Select-String -Pattern '^(init\.|claude-progress)'
```

Baseline da suíte no momento deste laudo (nenhum código foi alterado):
`$env:PYTHONPATH = "src"; python -m pytest tests -q` — **666 passed** em 86s.
