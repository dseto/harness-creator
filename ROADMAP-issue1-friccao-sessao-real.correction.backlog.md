# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Correção da fricção relatada no issue #1 (sessão real de 5 contratos
# sequenciais em `elegant-heisenberg`, stories 2.6-2.10). 7 pontos de
# fricção relatados; este backlog é o veredito priorizado após análise em 3
# passadas: triagem inicial (Sonnet) → auditoria adversarial independente
# (Forge/GPT-5.5) → arbitragem com verificação de claims no código real
# (Opus). Veredito completo em
# https://github.com/dseto/harness-creator/issues/1#issuecomment-5016735812
#
# Origem: issue #1. Cada claim decisivo confirmado lendo arquivo:linha antes
# de entrar aqui. O achado #1 (bypass de tool de escrita) é MAIS grave que os
# 7 pontos originais — é falha arquitetural do matcher do hook, não caso
# isolado de PowerShell.
#
# Alvo de código principal: `src/harness/boundary_guard.py`,
# `src/harness/compiler.py`, `src/harness/cli.py`, `src/harness/contract.py`.
# Skill: `skills/plan/SKILL.md`.
#
# Validação global ao fechar CADA item: `$env:PYTHONPATH = "src"; python -m
# pytest tests -q` 100% verde, sem regressão de contagem (baseline 421). Itens
# de segurança (1, 2, 3, 6) exigem prova de execução real do hook gerado
# (subprocess com stdin JSON), não só leitura de código — mesmo padrão da
# auditoria v0.16.1.
#
# Ordem: itens 1-3 são o núcleo de segurança (fecham bypass do floor), fazer
# primeiro e juntos onde acoplados. Itens 4-6 são ergonomia. Item 7 é
# opcional.

---

## Item 1 — Bypass de tool de escrita: matcher estreito + fail-open para tool não-reconhecida

**Achado:** o hook `boundary_guard.py` é registrado com matcher
`"Edit|Write|Bash"` (`boundary_guard.py:1103`; `compiler.py:113,116` para os
guards legados). Qualquer tool de escrita FORA desse conjunto nunca invoca o
hook — o Claude Code aplica o allow implícito. O usuário do issue #1 explorou
isso na prática com a tool **PowerShell** (`Set-Content`) para escrever fora
de `files[]`. O mesmo buraco vale para **NotebookEdit** e para qualquer **MCP
filesystem tool** (`mcp__*__write_file`, nome arbitrário). O `else: allow` em
`boundary_guard.py:1014-1015` (tool fora de Edit/Write/Bash → allow) confirma
a postura fail-open, mas hoje é quase inalcançável: o vazamento acontece ANTES,
no matcher — a tool não-casada nem chega ao `main()`.

**Por que importa:** o núcleo duro inteiro (runtime floor de segredos/rede,
superfície do contrato, feature-lock com evidência) é contornável por qualquer
tool de escrita que não se chame Edit/Write/Bash. Sob contrato ativo, o
PowerShell é o único vetor que fura superfície + floor + feature-lock com
conteúdo arbitrário (pode forjar `feature_list.json` com `passes:true` sem
evidência — o que o Bash NÃO consegue, pois cai na superfície). É a falha #1
do plugin: o design assume agente não-confiável, e o enforcement tem um portão
lateral aberto.

**Correção:** DUAS partes, ambas necessárias (nenhuma sozinha resolve):
(a) alargar o matcher do hook além de `Edit|Write|Bash`. **Antes de tratar como
resolvido, VERIFICAR o comportamento real do matcher `PreToolUse` do Claude
Code** — confirmar se `"*"` casa todas as tools, ou se o correto é matcher
vazio/omitido/lista explícita. NÃO herdar a suposição de `session_start.py:212`:
aquele é matcher de `SessionStart` (casa a ORIGEM da sessão — startup/resume/
clear), namespace diferente do `PreToolUse` (casa NOME de tool) — não é
evidência aplicável. (b) no `main()` do hook gerado, rotear explicitamente as
tools de escrita CONHECIDAS e enumeráveis: `Edit`/`Write` → `_evaluate_file`;
`NotebookEdit` → `_evaluate_file` sobre `notebook_path`; `PowerShell` →
`_evaluate_powershell` (Item 2); `Bash` → `_evaluate_bash`. Allowlist pequena e
fixa de tools sabidamente read-only/utilitárias que passam (`Read`, `Glob`,
`Grep`, `Task`, `WebFetch`, `TodoWrite` — `Task` é usado pelo próprio harness,
não pode cair no deny). Para tool DESCONHECIDA: dado o deploy single-user
interno, deny por padrão-de-nome óbvio de escrita (`mcp__*__write*`/`*create*`/
`*edit*`) e allow-logado para o resto — NÃO construir framework de governança
MCP abrangente, NÃO default-deny-tudo (quebraria `Task`/`WebFetch`). Documentar
o risco residual assumido dessa política mínima.

**Verify:** `pytest tests/test_boundary_guard.py -q` verde + testes novos:
(1) `NotebookEdit` em path fora da superfície → deny; (2) tool de escrita
fantasma (`mcp__x__write`) → deny; (3) Read/Glob/Grep → allow (não regride);
(4) `Task`/`WebFetch` (utilitária conhecida) → allow — regressão que o
default-deny ingênuo causaria. Prova de execução: gerar o hook e rodar via
subprocess com stdin JSON simulando `NotebookEdit` num `.env` → deny.

**Esforço:** M-L — **Risco se não corrigir:** ALTO (núcleo de segurança
contornável, já explorado na prática).

---

## Item 2 — Avaliador de PowerShell (floor-first), não reuso do avaliador de Bash

**Achado:** parte (b) do Item 1 exige avaliar comandos PowerShell, mas
`_evaluate_bash` (`boundary_guard.py:952`) não serve: nega qualquer comando
com backtick ou `$(` (`_evaluate_bash:963`) — e no PowerShell o backtick é o
caractere de ESCAPE e `$(...)` é subexpressão legítima e onipresente;
`_split_shell_segments` casa `&&`/`||` que o PowerShell 5.1 nem suporta.
Roteá-lo por `_evaluate_bash` daria falso-deny em PS válido e ainda deixaria o
floor de segredo cego (o floor de segredo hoje só existe no caminho Edit/Write
— ver Item 3).

**Por que importa:** no Windows (plataforma do issue #1) o PowerShell é o
shell primário. Governá-lo mal (ou não governá-lo) é deixar o vetor principal
de escrita da plataforma sem enforcement.

**Correção:** `_evaluate_powershell` dedicado. Ordem: floor tool-agnóstico
PRIMEIRO (escrita em path de segredo via `Set-Content`/`Out-File`/
`Add-Content`/`>`/`[IO.File]::WriteAllText` → deny; rede/publicação
`Invoke-WebRequest`/`Invoke-RestMethod`/`curl`/`git push` → deny), depois
superfície do contrato. Reusar as funções de floor JÁ importáveis e stdlib-only
(`is_floor_secret_path`, `is_floor_bash_command`) via o mesmo
`inspect.getsource()` que o Item 3 da auditoria v0.16.1 (`4d682d7`)
estabeleceu — não digitar terceira cópia.

**Verify:** testes novos: `Set-Content .env` → deny; `Out-File` em segredo →
deny; `Set-Content docs/x.md` (com Item 4 aplicado) → allow; PS legítimo com
`$(...)`/backtick que NÃO escreve segredo → não é falso-deny. Prova de
execução do hook gerado.

**Esforço:** M — **Risco se não corrigir:** ALTO (é o pedaço que fecha de
fato o vetor primário do Windows; Item 1 sem Item 2 só troca fail-open por
falso-deny em PS).

---

## Item 3 — Paridade do floor de segredo no caminho Bash

**Achado:** o floor de SEGREDO só é checado no caminho Edit/Write —
`is_floor_secret_path` (`boundary_guard.py:153`) é chamada em `_evaluate_file`
(`:914`), NUNCA em `_evaluate_bash` (`:952`). `is_floor_bash_command`
(`:146`, sequências em `FLOOR_BASH_SEQUENCES:126-134`) só cobre
git push/curl/wget/npm publish/pip upload/twine upload/gh release — não olha o
ALVO de redirecionamento. Logo `Bash('echo LEAK > config/.env')`, `tee`,
`printf >` escrevem segredo sem bater no floor; sem contrato ativo,
`_evaluate_bash` retorna `allow` na linha 961.

**Por que importa:** o docstring do módulo (`boundary_guard.py:14-20`) promete
que segredos "NUNCA viram allow, com ou sem contrato ativo" — a promessa é
FALSA no caminho Bash sem contrato. É uma garantia central do plugin
documentada e não cumprida.

**Correção:** em `_evaluate_bash`, antes do `return allow` sem-contrato
(`:960-961`), detectar redirecionamento (`>`/`>>`/`tee`) cujo alvo casa
`is_floor_secret_path` → deny. Escopo RESTRITO a redirecionamento/`tee` — NÃO
perseguir todo interpretador (`python -c open(...)`, `node -e`) — é corrida
armamentista de custo desproporcional; a redireção cobre o caso comum e
observável. Documentar o limite explicitamente. Corrigir também a redação do
docstring se o escopo do floor mudar.

**Verify:** testes: `echo x > .env` (sem contrato) → deny; `cat .env` (leitura,
sem contrato) → allow; `echo x > src/app.py` → não é bloqueado pelo floor de
segredo. Prova de execução do hook gerado.

**Esforço:** M — **Risco se não corrigir:** MÉDIO-ALTO (promessa de segurança
documentada e falsa, mas o vetor Bash sob contrato ativo já cai na superfície;
o buraco é sem-contrato).

---

## Item 4 — Superfície de docs via `docs/**` dedicado (NÃO `*.md` na raiz)

**Achado:** toda escrita fora de `files[]` do contrato ativo é negada,
inclusive `docs/*.md`, `README.md`. Fim de cada feature exige atualizar docs
que não cabem logicamente no `files[]` de uma task de código — foi o que
motivou o bypass do Item 1. A proposta original do issue (allowlist `*.md` na
raiz sem aprovação) é PERIGOSA: `AGENTS.md` é gerado na raiz (`compiler.py:370`,
`lifecycle.py:157`) e é o documento de governança lido como passo 1 de toda
sessão (`lifecycle.py:35,67`). Allowlist `*.md`-raiz daria ao agente escrita
livre sobre a própria governança → reescrita das regras que o governam +
prompt-injection persistida (texto reinjetado no contexto na próxima sessão) +
staging de exfiltração.

**Por que importa:** dar um caminho SANCIONADO para docs elimina o motivo do
bypass (Item 1) e preserva o log/auditoria que a escrita via shell não tem.
Mas fazer isso sem excluir a governança abriria um buraco pior que o que fecha.

**Correção:** allowlist fixa restrita a `docs/**` (análoga à exceção já
existente `WORK_DIR_PREFIX` = `.harness/work/**`, `boundary_guard.py:565,
920-924`), sem `verify_cmd` (prosa não quebra teste) e sem gate de aprovação —
MAS excluindo explicitamente `AGENTS.md`, `CLAUDE.md`, `Plans.md`, `spec.md` e
`.harness/harness.yaml` de qualquer allowlist automática (permanecem sob a
proteção atual). NÃO usar `*.md` na raiz.

**Verify:** testes: `Write docs/ARQUITETURA.md` → allow; `Write AGENTS.md` →
deny (governança protegida); `Write README.md` na raiz → deny (não é `docs/**`);
`Write docs/subdir/x.md` → allow. Prova de execução do hook gerado.

**Esforço:** S — **Risco se não corrigir:** BAIXO-MÉDIO (fricção real, mas o
risco maior é fazer ERRADO — abrir a governança).

---

## Item 5 — `harness task add-file <task-id> <path>`

**Achado:** adicionar um campo obrigatório a um DTO quebra a compilação de
2-4 specs/testes pré-existentes que instanciavam o DTO. Cada vez, o ciclo é:
editar `Plans.md` à mão (adicionar o path ao `files[]` da task), rodar
`compile-contract` completo (recompila tudo), só então poder editar os
arquivos quebrados. Aconteceu ≥4x na sessão do issue #1 (stories 2.7/2.9/2.10).

**Por que importa:** é fricção no fluxo CORE `plan → work`, não numa borda
distante — recorrente e previsível (scope creep pequeno é a norma, não a
exceção). Cada ocorrência custa uma edição manual de markdown + recompilação
integral.

**Correção:** subcomando `harness task add-file <task-id> <path>` que faz
append no `files[]` daquela task específica no `Plans.md` (respeitando o
formato que `contract.py` parseia) e recompila. Se recompilação incremental
for complexa, aceitar recompilação completa nesta primeira versão — o ganho é
não editar o markdown na mão. Não pode auto-aprovar contrato (mantém o gate de
`approved_by`/`approved_at`).

**Verify:** `pytest tests/test_contract.py tests/test_cli.py -q` verde + teste:
`add-file T-01 novo/path.ts` adiciona ao `files[]` de T-01 e só de T-01, no
`Plans.md`; contrato recompila com o novo arquivo na superfície.

**Esforço:** M — **Risco se não corrigir:** BAIXO (funciona hoje, é ergonomia
— mas alta frequência no fluxo core).

---

## Item 6 — Raiz do repo fixada no `compiled-state-session.json` (deriva de cwd)

**Achado:** o `cwd` do Bash tool sofre deriva silenciosa (fica preso em
`frontend/` sem `cd` explícito), gerando falso-positivo de "arquivo fora da
superfície" que na verdade é path relativo resolvido errado (≥3x na sessão do
issue #1). `_resolve_path` (`boundary_guard.py:591-596`) tira o prefixo `cwd`
do path e confia no `cwd` reportado pela tool call. A proposta original do
issue (`git rev-parse --show-toplevel` por chamada) regride o design: o
docstring do módulo (`:3-8`) diz que o boundary_guard existe para NÃO pagar N
subprocessos por tool call — `git rev-parse` a cada Edit/Write/Bash reintroduz
exatamente isso, além de footguns (submódulo/worktree/repo-em-repo/sem-git).

**Por que importa:** falso-deny por deriva de path faz o agente perder rodadas
de diagnóstico e erode a confiança no enforcement (a barreira "grita" onde não
deveria). Predominantemente fricção — prioridade MÉDIA, não segurança crítica.

**Pré-condição de investigação (barata, ANTES de codar):** confirmar
empiricamente O QUE de fato deriva no runtime — o campo `cwd` do payload
`PreToolUse`, ou apenas o `file_path` relativo com `cwd` estável. Isso decide o
mecanismo e o escopo: (a) se deriva só o `file_path` (cwd estável na raiz), o
sintoma é falso-deny na superfície e ancorar `_resolve_path` resolve; (b) se
deriva o próprio `cwd` do payload, então `_load_json` (`boundary_guard.py:654-663`,
usa o mesmo `cwd` que `_resolve_path`) também não acha `.harness/feature_list.json`
→ retorna `None` → `_evaluate_file`/`_evaluate_bash` retornam `allow` sem
contrato (`:928`/`:961`) ANTES da superfície — sintoma FAIL-OPEN, não falso-deny.
No caso (b), qualquer âncora de raiz introduzida tem que ser usada por
`_resolve_path` **E** `_load_json` na mesma chamada, senão a ancoragem fica
meia-feita. (Item 6 e este cenário fail-open são mutuamente exclusivos sobre o
mecanismo — a investigação desempata.)

**Correção:** gravar a raiz do repo UMA vez, no momento da compilação
(`compile-session`), em `.harness/compiled-state-session.json`. **Nota factual:
o hook standalone NÃO lê esse arquivo em runtime hoje** — `SESSION_STATE_FILE`
(`boundary_guard.py:109`) só é usada em `install_boundary_guard` (`:1081`, tempo
de instalação); `main()` (`:995-1029`) só embute `FEATURE_LIST_PATH`/
`PROFILE_PATH`/`EVIDENCE_DIR_NAME`/`TEAM_MANIFEST`/`REVIEW_DIR`/`WORK_DIR_PREFIX`
(`:557-565`). Implementar exige ADICIONAR ao script gerado uma leitura nova da
raiz (embutida via `inspect.getsource`, padrão do commit `4d682d7`) + uma
chamada em `main()` antes de `_resolve_path`/`_load_json`. `_resolve_path`
(e `_load_json`, se o caso (b) se confirmar) ancoram nesse valor fixo em vez do
`cwd` da tool call. Zero subprocess por call, sem footgun de
submódulo/worktree (ao contrário do `git rev-parse` da proposta original).

**Verify:** testes: path resolvido de um `cwd` derivado (`frontend/`) ancora
corretamente na raiz gravada e casa a superfície esperada; ausência da chave
no state → fallback ao comportamento atual (não quebra repos sem
`compile-session` recente).

**Esforço:** M+ (inclui a faixa de leitura nova no script gerado) — **Risco se
não corrigir:** MÉDIO (fricção recorrente; potencial fail-open se a
investigação confirmar o caso (b)).

---

## Item 7 — Detecção-only de MSB3027/MSB3021 (sem auto-kill) — OPCIONAL

**Achado:** `dotnet build`/`dotnet test` como `verify_cmd` falha com
`MSB3027`/`MSB3021` (`.exe` em uso) quando um `dotnet run` de dev ficou
rodando (~6x na sessão do issue #1). Hoje só existe a nota adicionada em
v0.16.1 (`skills/plan/SKILL.md`, commit `f1faf1b`) avisando o humano — não há
detecção automática.

**Por que importa:** fricção real e frequente, MAS é borda-da-borda do
objetivo do plugin (governança ≠ ergonomia de MSBuild .NET). A metade
"detectar e sinalizar" é barata e sem risco; a metade "auto-kill" é arriscada
(matar processo errado) e foi REJEITADA (ver abaixo).

**Correção:** quando um `verify_cmd` sai com erro casando o padrão
`MSB3027`/`MSB3021`/`EBUSY`/`Text File Busy`, emitir mensagem acionável
apontando a causa provável (processo do próprio projeto-alvo rodando) e o PID
se extraível da saída do MSBuild — SEM matar nada. Apenas sinalização.

**Verify:** teste: saída simulada de MSBuild com `MSB3027` produz a mensagem
acionável; saída normal de falha de teste não dispara a mensagem (sem
falso-positivo).

**Esforço:** S — **Risco se não corrigir:** BAIXO (fricção, contorno manual
trivial existe; fazer só se sobrar orçamento).

---

## Rejeitados (avaliados nas 3 passadas, descartados com motivo)

- **Exceção de `git push` doc-only** (item 6 do issue) — o próprio relator
  reconhece baixa prioridade; o floor de `git push` é inegociável por design.
  É, aliás, o que hoje contém o vetor de exfiltração via docs (Item 4).
- **`harness db migrate --dev` para EF Core/Oracle** (item 5 do issue) —
  domínio-específico demais para um compilador de governança genérico. Não é
  núcleo nem borda do plugin.
- **Allowlist `*.md` na raiz sem aprovação** (proposta original do item 1) —
  abriria `AGENTS.md` a reescrita de governança e prompt-injection persistida.
  Substituída pelo Item 4 (`docs/**` com exclusões).
- **`git rev-parse --show-toplevel` por chamada do hook** (proposta original
  do item 7) — subprocess no hot path, contra o design de latência do módulo.
  Substituído pelo Item 6 (raiz fixa no state).
- **Auto-kill de processo travando build** (metade do item 4 do issue) —
  risco de matar processo errado > benefício; fora do núcleo de governança.
- **Histórico append-only de `feature_list.json`** (item 2 do issue) — valor
  marginal em uso single-user interno; não corta fricção do fluxo core como o
  Item 5.
- **Limpeza dos docs corrompidos por encoding** (`Set-Content` sem
  `-Encoding utf8`, achado incidental) — housekeeping do repo consumidor
  (`elegant-heisenberg`), não trabalho neste plugin. Documentar na skill que
  qualquer escrita fora do Edit/Write (agora bloqueada pelos Itens 1-2)
  corrompia encoding no Windows.
