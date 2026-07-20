# BACKLOG DE EXECUÇÃO - CLAUDE CODE

> 🏁 DEMANDA FECHADA — 2026-07-16

> Decompõe a Fase 3 do ROADMAP ("Auto-verificação e Correção em Loop",
> `ROADMAP.md` linhas ~208-247) em tarefas atômicas para subagentes frios.
> Mapa de dependências completo ao final do arquivo.
>
> ✅ Revisado por reflect (plan-critic, Sonnet) + llm-as-judge (Fable,
> independente) em 2026-07-16. Achados 1-6 e 8 confirmados; único ajuste
> real: centralizar "feature em progresso" + `files_hash` em funções
> públicas importáveis (`verify.compute_files_hash`,
> `stop_hook.is_feature_in_progress`/`needs_verification`) em vez de
> duplicar com aviso em docstring entre `stop_hook.py` e
> `runtime_audit.py` — segue o precedente já estabelecido por
> `boundary_guard.py` (duplicação só onde é impossível importar: dentro da
> string do script standalone). Também: versão importável do feature-lock
> em SUBAGENTE 03 virou obrigatória, e SUBAGENTE 04 ganhou fallback
> explícito caso o WebFetch da doc oficial falhe.

---

### [SUBAGENTE 01] - `harness verify <feature-id>` + evidência
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Criar o comando `harness verify <feature-id>` que roda o
  `verify_cmd` de UMA feature do `.harness/feature_list.json` e, só em caso de
  sucesso (exit code 0), grava `.harness/evidence/<id>.json` — a prova
  executável que o passo 11 do lifecycle ("registrar a prova") e a Fase 3
  inteira dependem. Isto NÃO inclui nenhuma lógica de bloqueio/gate sobre
  `feature_list.json` (isso é o SUBAGENTE 03) nem lógica de ordenação por
  `depends[]` (fora de escopo — `contract.py` já documenta que nenhuma
  ordenação é implementada; `verify` roda a feature pedida, ponto, mesmo que
  suas dependências não estejam concluídas).
  **Decisões de formato (fixar exatamente assim — outras tarefas dependem
  disto):**
  - Caminho da evidência: `.harness/evidence/<feature_id>.json`.
  - Schema exato do arquivo de evidência:
    ```json
    {
      "feature_id": "T-01",
      "verify_cmd": "pytest tests/test_x.py -q",
      "recorded_at": "2026-07-16T12:00:00+00:00",
      "exit_code": 0,
      "files_hash": "sha256:<hex>"
    }
    ```
  - `files_hash`: SHA-256 (prefixo `"sha256:"` + hexdigest) do conteúdo atual
    dos arquivos em `files[]` da feature — calcule concatenando, em ordem
    ordenada (`sorted(files)`), para cada caminho: o próprio caminho relativo
    + `"\n"` + os bytes do arquivo (lidos de `target_dir`) + `"\n"`; se um
    caminho não existir em disco, use o literal `b"<missing>\n"` no lugar do
    conteúdo (nunca lance exceção por arquivo ausente). Serve para a Fase 3
    detectar depois (SUBAGENTE 03/05/06) se os arquivos mudaram desde a
    verificação.
  - `recorded_at`: `datetime.now(timezone.utc).isoformat()`.
  - Execução do `verify_cmd`: `subprocess.run(verify_cmd, shell=True,
    cwd=target_dir, capture_output=True, text=True, timeout=600)` (constante
    `DEFAULT_VERIFY_TIMEOUT_SECONDS = 600`, cross-platform via `shell=True` —
    o ambiente de destino inclui Windows).
  - CLI: `harness verify <feature_id> --dir <alvo>`. Sucesso (exit 0 do
    `verify_cmd`): grava evidência, imprime o JSON da evidência em stdout,
    `sys.exit(0)`. Falha do `verify_cmd` (exit != 0): NÃO grava evidência,
    imprime stdout/stderr capturados em stderr, `sys.exit()` com o MESMO
    código de saída do `verify_cmd` (nunca hardcode 1 — o loop de
    autocorreção do agente precisa do código real). Feature id inexistente
    em `feature_list.json` ou `feature_list.json` ausente: mensagem
    `f"erro: {...}"` em stderr, `sys.exit(1)` (mesmo padrão de
    `compile-contract`).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/contract.py` (schema de `feature_list.json`),
    `src/harness/cli.py` (padrão de subcomandos existentes — `compile-contract`
    é o mais próximo em forma), `tests/test_cli.py` (padrão de teste de CLI
    via `monkeypatch.setattr(sys, "argv", ...)` + `pytest.raises(SystemExit)`)
  - Modificar: `src/harness/verify.py` (novo arquivo), `src/harness/cli.py`
    (adicionar subparser `verify`), `tests/test_verify.py` (novo arquivo),
    `tests/test_cli.py` (adicionar testes do subcomando `verify`)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `src/harness/verify.py` com uma função
  > `run_verify(target_dir: Path, feature_id: str) -> Path` que lê
  > `.harness/feature_list.json`, localiza a feature por `id`, roda o
  > `verify_cmd` dela via subprocess (shell=True, cwd=target_dir,
  > capture_output, timeout=600s) e, SE E SOMENTE SE o exit code for 0, grava
  > `.harness/evidence/<feature_id>.json` com o schema EXATO especificado no
  > objetivo desta tarefa (campos `feature_id`, `verify_cmd`, `recorded_at`,
  > `exit_code`, `files_hash`, sendo `files_hash` o sha256 dos arquivos
  > declarados em `files[]` da feature, calculado exatamente como descrito).
  > Se o exit code for != 0, NÃO grave evidência e levante uma exceção
  > própria (ex. `VerifyFailedError`) carregando stdout/stderr/exit_code. Se
  > a feature não existir, levante `VerifyError` citando o id.
  > **IMPORTANTE (revisão plan-critic + judge):** exponha o algoritmo de hash
  > como função pública de módulo, `compute_files_hash(files: list[str],
  > target_dir: Path) -> str` (não deixe a lógica só inline dentro de
  > `run_verify`) — SUBAGENTE 04 e SUBAGENTE 05 vão IMPORTAR essa função
  > (não reimplementar) para recalcular o hash e detectar evidência
  > desatualizada. Depois,
  > registre o subcomando `harness verify <feature_id> --dir <alvo>` em
  > `src/harness/cli.py` seguindo o padrão dos subcomandos já existentes
  > (`compile-contract`, `compile-session`): sucesso imprime o JSON da
  > evidência gravada e sai com 0; falha do verify_cmd imprime
  > stdout/stderr em stderr e sai com o exit code REAL do verify_cmd (não
  > hardcode); feature/contrato ausente imprime `erro: ...` em stderr e sai
  > com 1. Escreva `tests/test_verify.py` cobrindo: sucesso grava evidência
  > com schema correto; falha do verify_cmd não grava evidência e propaga o
  > exit code; feature id inexistente levanta erro nomeando o id;
  > `files_hash` muda quando o conteúdo de um arquivo em `files[]` muda;
  > `compute_files_hash` é determinístico pra mesma entrada e não lança
  > exceção para arquivo ausente. Adicione a `tests/test_cli.py` os testes do subcomando `verify` (sucesso
  > exit 0, falha do verify_cmd propaga exit code, feature inexistente exit
  > 1) seguindo o padrão de `monkeypatch.setattr(sys, "argv", ...)` já usado
  > nesse arquivo para `compile-contract`/`compile-session`. NÃO implemente
  > nenhuma lógica de bloqueio sobre edições em `feature_list.json` (isso é
  > outra tarefa), NÃO implemente ordenação por `depends[]`, NÃO renomeie
  > nem refatore nada em `contract.py` ou `cli.py` além de adicionar o novo
  > subparser."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_verify.py -q`
  - [ ] `python -m pytest tests/test_cli.py -q`
  - [ ] `ruff check src/harness/verify.py`

---

### [SUBAGENTE 02] - Stop conditions do `spec.md` como disjuntor explícito
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Expor um acessor explícito para `stop_conditions` do
  frontmatter de `spec.md` (o parser em `contract.py::parse_spec` já retorna
  o campo como parte do dict — confirmado por
  `tests/test_contract.py::test_parse_spec_returns_stop_conditions_when_present`
  — falta só um acessor dedicado e a citação explícita no detalhe do
  lifecycle, passo 10, de que é ESSA fonte que funciona como disjuntor do
  loop de autocorreção). Não reimplemente parsing de frontmatter já
  existente; não mude o formato de `spec.md`.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/contract.py`, `src/harness/lifecycle.py`,
    `tests/test_contract.py`, `tests/test_lifecycle.py`, `skills/plan/SKILL.md`
    (só leitura — confirma que o template já grava `stop_conditions:` no
    frontmatter; NÃO precisa editar a skill)
  - Modificar: `src/harness/contract.py` (nova função
    `get_stop_conditions`), `src/harness/lifecycle.py`
    (`render_lifecycle_detail`, parágrafo do passo 10), `tests/test_contract.py`,
    `tests/test_lifecycle.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é adicionar em `src/harness/contract.py` a função
  > `get_stop_conditions(spec_path: Path) -> list[str]`: chama `parse_spec`,
  > lê a chave `stop_conditions` do dict retornado (`data.get('stop_conditions')
  > or []`), converte cada item para `str` e devolve a lista (lista vazia se
  > a chave não existir ou for `None`). Depois, edite
  > `render_lifecycle_detail()` em `src/harness/lifecycle.py`: SÓ o parágrafo
  > do passo 10 (o que já fala de 'stop conditions (N falhas consecutivas ou
  > sinal de impossibilidade)') — amplie o texto (sem apagar o que já existe)
  > para citar EXPLICITAMENTE que a fonte das stop conditions é o campo
  > `stop_conditions:` do frontmatter do `spec.md` ativo
  > (`.harness/work/<slug>/spec.md`), acessível via
  > `harness.contract.get_stop_conditions`, e que satisfazer QUALQUER uma
  > delas interrompe o loop de autocorreção, registra o estado em
  > `claude-progress.md` e devolve ao humano com diagnóstico. NÃO toque nos
  > outros 15 parágrafos do detalhe nem no bloco compacto
  > `render_lifecycle_block()` além do necessário para não quebrar os testes
  > existentes — leia `tests/test_lifecycle.py` ANTES de editar para garantir
  > que nenhuma string testada (ex. `'{n}. **'` por passo) deixe de casar.
  > Adicione um teste em `tests/test_contract.py` para
  > `get_stop_conditions` (frontmatter com lista -> lista igual; frontmatter
  > sem a chave -> lista vazia) e um teste em `tests/test_lifecycle.py`
  > confirmando que o passo 10 do detalhe menciona `stop_conditions` e
  > `spec.md`. NÃO refatore `parse_spec` nem mude o schema/format de
  > `spec.md`/`Plans.md`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_contract.py -q`
  - [ ] `python -m pytest tests/test_lifecycle.py -q`

---

### [SUBAGENTE 03] - Feature-lock no `boundary_guard.py`
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Estender o dispatcher único (`boundary_guard.py`, Fase 2)
  para reconhecer edições ao PRÓPRIO `.harness/feature_list.json` como uma
  categoria especial: uma edição que faz alguma feature transicionar de
  `passes` não-`true` (ausente, `false`) para `true` só é permitida (`allow`)
  se EXISTIR `.harness/evidence/<id>.json` (schema do SUBAGENTE 01) válido e
  com `recorded_at` mais novo que o timestamp do último commit git
  (`git log -1 --format=%cI`, mesmo padrão de subprocess já usado em
  `session_start.py::_read_git_log`); caso contrário, `deny` citando o(s)
  id(s) sem evidência fresca e instruindo "rode harness verify <id>
  primeiro". Edições a `feature_list.json` que NÃO transicionam nenhuma
  feature para `passes: true` (mudar `desc`, `depends`, reverter
  `true`->`false`, etc.) mantêm o comportamento ATUAL (deny — o arquivo
  continua fora da superfície `files[]` de qualquer tarefa, isso não muda).
  **Depende do SUBAGENTE 01** (schema/caminho de `.harness/evidence/<id>.json`
  já precisam existir e estar fixados).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/boundary_guard.py` (inteiro — `render_boundary_guard`,
    `main()`, `_evaluate_file`), `src/harness/verify.py` (schema de evidência
    fixado pelo SUBAGENTE 01), `src/harness/session_start.py`
    (`_read_git_log`, para replicar o mesmo padrão de subprocess `git log`),
    `tests/test_boundary_guard.py`
  - Modificar: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é estender `src/harness/boundary_guard.py` para
  > tratar edições (`Edit`/`Write`) ao caminho `.harness/feature_list.json`
  > como caso especial, ANTES da checagem genérica de superfície
  > (`_evaluate_file`/`allowed_files`). Primeiro confirme os nomes EXATOS dos
  > campos de `tool_input` para `Edit` (tipicamente `file_path`,
  > `old_string`, `new_string`) e `Write` (tipicamente `file_path`,
  > `content`) — não assuma sem checar a documentação oficial de hooks do
  > Claude Code ou payloads reais já testados no repo. Implemente: (1) ler o
  > conteúdo ATUAL de `feature_list.json` do disco (via `cwd`); (2) calcular
  > o conteúdo PROPOSTO — para `Write`, é `tool_input['content']` direto;
  > para `Edit`, é o texto atual com `old_string` substituído por
  > `new_string` UMA vez (`text.replace(old_string, new_string, 1)`,
  > simulando fielmente como a ferramenta Edit real aplica a mudança); (3)
  > fazer `json.loads` dos dois e comparar, por `id`, quais features
  > transicionam de `passes` != `true` para `passes: true`; (4) para CADA
  > uma dessas, checar se `.harness/evidence/<id>.json` existe, é JSON
  > válido com `feature_id == id`, e se `recorded_at` (parseável como
  > ISO8601) é mais novo que o timestamp do último commit git obtido via
  > `subprocess.run(['git','log','-1','--format=%cI'], cwd=cwd,
  > capture_output=True, text=True, timeout=10)` (mesmo padrão de
  > `session_start.py::_read_git_log`); se o `git log` falhar (sem commits,
  > não é repo git), trate como 'sem timestamp de referência' e exija apenas
  > que a evidência exista e seja válida (sem comparação de data); (5) se
  > TODAS as transições tiverem evidência fresca válida, retorne `allow` com
  > razão citando os ids confirmados; se QUALQUER uma não tiver, retorne
  > `deny` citando o(s) id(s) problemáticos e a instrução 'rode harness
  > verify <id> antes de marcar passes:true'; (6) se não houver NENHUMA
  > transição para `passes:true` nesta edição, delegue ao comportamento
  > ATUAL do `_evaluate_file` (hoje já resulta em deny, porque
  > `feature_list.json` nunca está em `files[]` de nenhuma tarefa — não
  > mude isso). Implemente tanto no script standalone gerado por
  > `render_boundary_guard()` (stdlib apenas, sem import de `harness.*` —
  > mesma restrição do resto do arquivo) QUANTO — OBRIGATÓRIO, não opcional,
  > porque `_evaluate_file` só existe hoje dentro da string do script e não é
  > testável via pytest direto sem isso — uma versão importável equivalente
  > no módulo `boundary_guard.py` (documente explicitamente, no
  > mesmo estilo do docstring já existente sobre o runtime floor, que as
  > duas cópias têm que ficar sincronizadas se uma mudar). Adicione testes
  > em `tests/test_boundary_guard.py`: deny quando não há evidência; deny
  > quando evidência existe mas é mais antiga que o último commit; allow
  > quando evidência é mais nova que o último commit; comportamento
  > inalterado (deny) para edição de `feature_list.json` que não toca
  > `passes:true`. NÃO toque no runtime floor nem na proteção de teste já
  > existentes, NÃO renomeie funções existentes."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_boundary_guard.py -q`
  - [ ] `python -m pytest tests/e2e/test_boundary_flow.py -q`

---

### [SUBAGENTE 04] - Hook `Stop`
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Criar o hook `Stop` (evento NOVO, distinto de
  `PreToolUse`/`SessionStart` já existentes): ao encerrar a sessão, verifica
  se há alguma feature "em progresso" — definição fixada nesta tarefa:
  `passes` é `false` E existe trabalho não commitado tocando algum caminho
  de `files[]` da feature (via `git diff --name-only HEAD -- <files...>`,
  mesmo padrão de subprocess de `session_start.py::_read_git_log`) — cuja
  verificação nunca rodou (`.harness/evidence/<id>.json` ausente) ou está
  desatualizada (`files_hash` do evidence não bate com o hash recalculado
  dos arquivos atuais, mesmo algoritmo do SUBAGENTE 01). Se sim, o hook
  devolve feedback ao AGENTE (não bloqueia o processo do Claude Code em si)
  instruindo a rodar `harness verify <id>` antes de encerrar. **ANTES DE
  ESCREVER QUALQUER CÓDIGO**, confirme via busca na documentação oficial
  (`https://code.claude.com/docs/en/hooks`, seção `Stop`) o schema EXATO de
  entrada/saída do hook `Stop` — NÃO assuma a partir do padrão de
  `PreToolUse` (`hookSpecificOutput.permissionDecision`) nem do de
  `SessionStart` (`hookSpecificOutput.additionalContext`); documente no
  docstring do módulo, no MESMO padrão de cautela que `session_start.py` já
  usa (cita a URL exata consultada). **Depende do SUBAGENTE 01** (schema de
  evidência) — pode rodar em paralelo ao SUBAGENTE 03 (arquivos disjuntos).
  **AJUSTE PÓS-REVISÃO (plan-critic + judge):** `stop_hook.py` (módulo normal
  do pacote, SEM a restrição standalone que só se aplica ao script gerado
  por `render_stop_hook()`) deve expor `is_feature_in_progress(feature: dict,
  target_dir: Path) -> bool` como função pública de módulo — importa
  `verify.compute_files_hash` (SUBAGENTE 01) em vez de reimplementar o hash.
  Isso vira a fonte única que o SUBAGENTE 05 (`runtime_audit.py`) IMPORTA em
  vez de duplicar — mesmo precedente que `boundary_guard.py` já estabelece
  para `is_floor_bash_command`/`is_floor_secret_path` (duplicação só onde é
  IMPOSSÍVEL importar, isto é, dentro da string do script standalone; a
  decisão em si vive numa função real do módulo).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/session_start.py` (padrão de hook standalone +
    docstring de cautela sobre schema real), `src/harness/verify.py` (schema
    de evidência e algoritmo de `files_hash`), `src/harness/cli.py`
    (subcomando `compile-session`, onde os hooks de sessão são instalados
    em sequência), `tests/test_session_start.py` (padrão de teste via
    subprocess), `tests/test_cli.py`
  - Modificar: `src/harness/stop_hook.py` (novo arquivo), `src/harness/cli.py`
    (chamar `install_stop_hook` dentro do handler de `compile-session`),
    `tests/test_stop_hook.py` (novo arquivo), `tests/test_cli.py` (atualizar
    `test_compile_session_subcommand_success` para o novo artefato, se
    aplicável)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `src/harness/stop_hook.py`, espelhando a
  > estrutura de `src/harness/session_start.py` (funções
  > `render_stop_hook() -> str` que devolve o script standalone stdlib-only,
  > e `install_stop_hook(target_dir: Path) -> Path` que grava o script em
  > `.harness/hooks/stop_hook.py` e registra em `hooks.Stop` de
  > `.claude/settings.json`, com merge não-destrutivo via
  > `.harness/compiled-state-session.json`, chave própria
  > `stop_hook_command`, preservando as chaves irmãs). SE o `WebFetch` da doc
  > oficial falhar/for negado no seu ambiente, NÃO trave a tarefa: assuma o
  > schema mais provável por analogia — `hookSpecificOutput` com um campo de
  > mensagem textual pro agente, análogo a `additionalContext` do
  > `SessionStart` — e documente explicitamente no docstring que a consulta
  > falhou e qual suposição foi assumida (não é bloqueante, é best-effort).
  > ANTES de escrever qualquer lógica, pesquise (WebFetch) a documentação
  > oficial em https://code.claude.com/docs/en/hooks, seção Stop, para
  > confirmar o schema real de entrada (stdin JSON) e saída esperado desse
  > hook — não adivinhe a partir de PreToolUse/SessionStart. Documente no
  > topo do módulo, citando a URL, exatamente como `session_start.py` já faz.
  > Implemente, como função PÚBLICA de módulo (não só dentro da string do
  > script gerado): `is_feature_in_progress(feature: dict, target_dir: Path)
  > -> bool` — `passes` é `false` E `git diff --name-only HEAD -- <files da
  > feature>` (subprocess, mesmo padrão de robustez de `_read_git_log`: falha
  > do git = trata como 'sem mudança', nunca propaga exceção) não-vazio.
  > Implemente também `needs_verification(feature: dict, target_dir: Path) ->
  > bool`: chama `is_feature_in_progress`, e se `True`, checa se
  > `.harness/evidence/<id>.json` existe e se seu `files_hash` bate com
  > `verify.compute_files_hash(feature['files'], target_dir)` (IMPORTE de
  > `harness.verify`, não reimplemente o hash). Essas duas funções são a
  > fonte única que o SUBAGENTE 05 vai importar depois — só o SCRIPT
  > STANDALONE gerado por `render_stop_hook()` (que roda via subprocess fora
  > do pacote) precisa de uma cópia inline stdlib-only da MESMA lógica; se
  > `needs_verification` indicar que há feature pendente de verificação,
  > monte a mensagem de feedback (conforme o schema real do hook Stop que você confirmou) instruindo o
  > agente a rodar `harness verify <id>` antes de encerrar a sessão. Sem
  > nenhuma feature nessa condição, o hook não interfere (schema de
  > 'sem ação' conforme a documentação real). Registre a chamada de
  > `install_stop_hook` dentro do handler `compile-session` de
  > `src/harness/cli.py`, na mesma sequência de `install_session_start`, e
  > inclua o novo artefato na saída JSON impressa (ex. chave
  > `stop_hook`). Escreva `tests/test_stop_hook.py` cobrindo: sem feature em
  > progresso -> hook não sinaliza nada; feature em progresso sem evidência
  > -> hook sinaliza; feature em progresso com evidência atualizada -> hook
  > não sinaliza; `install_stop_hook` idempotente e preserva chaves
  > irmãs (mesmo padrão de `test_session_start.py`); teste dedicado de
  > `is_feature_in_progress`/`needs_verification` como funções importáveis
  > (chamadas diretas, sem subprocess) cobrindo os mesmos cenários. Atualize
  > `tests/test_cli.py::test_compile_session_subcommand_success` se a saída
  > JSON ganhar uma chave nova. NÃO toque em `session_start.py` nem
  > `boundary_guard.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_stop_hook.py -q`
  - [ ] `python -m pytest tests/test_cli.py -q`

---

### [SUBAGENTE 05] - Segunda máquina de audit (runtime: schema + frescor + invariantes)
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Criar `src/harness/runtime_audit.py`, mecanismo de
  auditoria DISTINTO de `src/harness/audit.py` (que continua fazendo diff
  byte-exato dos artefatos COMPILADOS/determinísticos — settings/hooks/
  AGENTS.md). Este novo mecanismo audita os artefatos RUNTIME-MUTÁVEIS:
  `claude-progress.md`, `.harness/feature_list.json`, `.harness/evidence/*.json`
  — schema + frescor + invariantes, nunca diff byte-exato (esses arquivos
  mudam a cada sessão, byte-exato não faz sentido aqui). Invariantes
  mínimos: (a) no máximo 1 feature "em progresso" ao mesmo tempo — usa
  `stop_hook.is_feature_in_progress` (SUBAGENTE 04, IMPORTADA, não
  reimplementada); (b) todo `passes: true` em `feature_list.json` tem um
  `.harness/evidence/<id>.json` correspondente, existente, com JSON válido
  e schema correto (campos `feature_id`/`verify_cmd`/`recorded_at`/
  `exit_code`/`files_hash` presentes, `exit_code == 0`). **Depende dos
  SUBAGENTES 01 e 04** (schema de evidência + `is_feature_in_progress` já
  precisam existir como funções importáveis — este bloco IMPORTA, nunca
  reimplementa, seguindo o precedente de `boundary_guard.py`:
  `is_floor_bash_command`/`is_floor_secret_path` só duplicam dentro da
  string do script standalone, nunca entre módulos normais do pacote).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/audit.py` (estrutura `Finding`/`AuditReport`, padrão de
    severidade/score/penalidade a espelhar — NÃO importar, mecanismo
    distinto), `src/harness/verify.py` (schema de evidência), `src/harness/
    stop_hook.py` (IMPORTAR `is_feature_in_progress` daqui, fixada pelo
    SUBAGENTE 04 — não reimplementar), `src/harness/cli.py` (padrão do
    subcomando `audit`), `tests/test_audit.py`, `tests/test_cli.py`
  - Modificar: `src/harness/runtime_audit.py` (novo arquivo), `src/harness/cli.py`
    (novo subcomando `audit-runtime`), `tests/test_runtime_audit.py`
    (novo arquivo), `tests/test_cli.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `src/harness/runtime_audit.py` com dataclasses
  > próprias `RuntimeFinding` (severity/code/message/fix, mesmo shape de
  > `Finding` em `audit.py`, mas classe SEPARADA — não importe de
  > `audit.py`) e `RuntimeAuditReport` (score 0-100 com a MESMA tabela de
  > penalidade `critical=40/warning=15/info=5`, findings list, `to_dict`/
  > `to_json`) e uma função `audit_runtime(target_dir: Path) ->
  > RuntimeAuditReport`. Verifique: (1) `.harness/feature_list.json` existe e
  > é JSON válido com schema esperado (`contract`, `compiled_at`, `features[]`
  > com `id`/`desc`/`files`/`verify_cmd`/`depends`/`passes`) — ausência ou
  > schema quebrado é `critical`; (2) `claude-progress.md` existe (`warning`
  > se ausente, sem exigir conteúdo específico); (3) para cada feature com
  > `passes: true`, existe `.harness/evidence/<id>.json`, é JSON válido, tem
  > `feature_id == id`, os campos obrigatórios do schema (`verify_cmd`,
  > `recorded_at`, `exit_code`, `files_hash`) e `exit_code == 0` — qualquer
  > violação é `critical` citando o id; (4) invariante 'no máximo 1 feature
  > em progresso': IMPORTE `is_feature_in_progress` de `harness.stop_hook`
  > (SUBAGENTE 04) — NÃO reimplemente a lógica de `git diff` — e aplique a
  > cada feature; se mais de uma satisfizer, `critical` citando os ids
  > envolvidos. Registre o
  > subcomando `harness audit-runtime --dir <alvo>` em `src/harness/cli.py`
  > (mesmo padrão do subcomando `audit`: imprime `report.to_json()`, exit 0
  > se score >= 60 senão exit 1). Escreva `tests/test_runtime_audit.py`
  > cobrindo cada invariante isoladamente (feature_list ausente/inválido;
  > evidence ausente para passes:true; evidence com schema quebrado;
  > exit_code != 0 na evidence; duas features 'em progresso' simultâneas;
  > caso saudável com score alto e zero critical). Adicione a
  > `tests/test_cli.py` os testes do subcomando `audit-runtime` (exit 0/1
  > conforme score). NÃO toque em `src/harness/audit.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_runtime_audit.py -q`
  - [ ] `python -m pytest tests/test_cli.py -q`
  - [ ] `python -m pytest tests/test_audit.py -q` (prova que o mecanismo antigo continua intocado)

---

### [SUBAGENTE 06] - Gate de encerramento: dogfood E2E da Fase 3
> ✅ CONCLUÍDO — dogfood real rodado, evidência em tests/e2e/evidence/fase3-dogfood-verify-lock.md
- **🎯 Objetivo:** Ampliar `tests/e2e/test_contract_dogfood.py` (NUNCA
  recomeçar do zero — já tem os gates de Fase 1 e Fase 2 na mesma cobaia
  .NET externa) com o gate final da Fase 3: uma sessão `claude -p` headless
  real prova (a) zero regressão das Fases 1/2 na MESMA cobaia (reaproveitar
  o padrão de asserts já usado nos dois testes existentes) e (b) a novidade
  real da Fase 3 — `harness verify T-01` rodado depois da correção real grava
  evidência real (`.harness/evidence/T-01.json` com schema correto,
  `exit_code == 0`); e uma tentativa, na mesma sessão headless, de editar
  `.harness/feature_list.json` marcando `passes: true` SEM rodar `harness
  verify` antes é negada de verdade pelo `boundary_guard.py` (feature-lock
  do SUBAGENTE 03) — prova via `permission_denials` estruturado do JSON de
  saída do `claude -p`, nunca por texto da resposta, mais confirmação por
  leitura de arquivo de que `feature_list.json` continua com `passes:
  false` para T-01. **Depende de TODOS os subagentes anteriores** (01, 02,
  03, 04, 05) já mergeados — é o gate final, roda por último.
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/test_contract_dogfood.py` (inteiro — reaproveitar
    `SPEC_MD_TEMPLATE`, `PLANS_MD`, `HARNESS_YAML`, `CLAUDE_PROMPT_BOUNDARY`,
    fixture `api_project`, padrão `_write_evidence*`/`_run_dotnet_test`/
    `_parse_trx`), `tests/e2e/conftest.py` (fixture `api_project`),
    `src/harness/verify.py`, `src/harness/boundary_guard.py`
  - Modificar: `tests/e2e/test_contract_dogfood.py` (adicionar nova(s)
    função(ões) de teste — nunca editar as duas funções de teste já
    existentes nem `EVIDENCE_PATH`/`EVIDENCE_PATH_BOUNDARY`)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é adicionar em `tests/e2e/test_contract_dogfood.py`
  > uma nova função de teste (ex.
  > `test_contract_dogfood_verify_and_feature_lock`), seguindo EXATAMENTE o
  > padrão das duas já existentes no arquivo (mesmo `SPEC_MD_TEMPLATE`/
  > `PLANS_MD`/`HARNESS_YAML`/fixture `api_project`, mesmo ciclo TDD real com
  > `_add_new_fact`/`_run_dotnet_test`/`_parse_trx`, mesmo skip via
  > `_require_toolchain`, própria trilha de evidência em
  > `EVIDENCE_DIR / 'fase3-dogfood-verify-lock.md'` — NUNCA reaproveite nem
  > sobrescreva `EVIDENCE_PATH`/`EVIDENCE_PATH_BOUNDARY` das Fases 1/2).
  > Fluxo do novo teste: (1) TDD real igual aos outros (teste vermelho antes
  > da correção); (2) `analyze` -> `compile-contract` -> `compile` ->
  > `compile-session` (mesma sequência dos testes existentes, agora também
  > instalando o hook Stop via `compile-session`, se o SUBAGENTE 04 já o
  > registrou nesse handler); (3) sessão `claude -p` headless real com um
  > prompt novo (baseado em `CLAUDE_PROMPT`, adicione instruções) que pede
  > para: (i) implementar T-01 de verdade, (ii) rodar `python -m harness.cli
  > verify T-01 --dir .` (com `PYTHONPATH` apontando para o pacote, se
  > necessário) e confirmar que grava `.harness/evidence/T-01.json`, (iii)
  > DEPOIS, tentar editar `.harness/feature_list.json` manualmente marcando
  > `passes: true` para T-01 SEM ter rodado verify de novo desde uma mudança
  > (ou simplesmente confiar que o passo (ii) já tornou isso permitido —
  > para provar o DENY, a tarefa deve pedir explicitamente que o agente
  > tente marcar `passes: true` ANTES de rodar verify, e trate a negação
  > como resultado esperado, sem insistir, mesmo padrão de instrução usado
  > em `CLAUDE_PROMPT_BOUNDARY` para a tentativa fora do raio). Depois da
  > sessão: (a) assert `out['is_error'] is False`; (b) assert
  > `.harness/evidence/T-01.json` existe com `exit_code == 0` e `files_hash`
  > correspondente ao conteúdo real do arquivo corrigido; (c) assert
  > `permission_denials` não vazio (prova real do feature-lock) E, por
  > leitura direta de `feature_list.json`, que a tentativa de marcar
  > `passes:true` sem evidência fresca de fato NÃO alterou o arquivo antes
  > da evidência real existir (ou seja, o estado final só tem `passes:true`
  > DEPOIS que a evidência real foi gravada pelo passo (ii), nunca antes);
  > (d) reaproveite os asserts de zero regressão (`dotnet test` real,
  > `_PRE_EXISTING_TESTS` continuam `Passed`) dos testes já existentes. NÃO
  > edite `test_contract_dogfood_document_digits` nem
  > `test_contract_dogfood_boundary_guard_denies_out_of_scope` — apenas
  > adicione a função nova e, se necessário, constantes/helpers NOVOS (com
  > nomes que não colidam com os já existentes)."
- **🧪 Critério de Validação (DoD):**
  - [ ] `HARNESS_E2E_DOGFOOD=1 python -m pytest tests/e2e/test_contract_dogfood.py -q` (exige `claude`+`dotnet` no PATH; os 3 testes do arquivo — 2 antigos + 1 novo — precisam passar)
  - [ ] `python -m pytest tests/ -q -k "not dogfood"` (suíte completa restante segue verde — zero regressão fora do dogfood opt-in)

---

## Mapa de dependências

- **Fase 1 (paralelo — arquivos disjuntos, sem dependência mútua):**
  - [SUBAGENTE 01] `harness verify` + evidência — `src/harness/verify.py`, `src/harness/cli.py`, `tests/test_verify.py`, `tests/test_cli.py`
  - [SUBAGENTE 02] Stop conditions explícitas — `src/harness/contract.py`, `src/harness/lifecycle.py`, `tests/test_contract.py`, `tests/test_lifecycle.py`
- **Fase 2 (paralelo entre si; ambos dependem do schema de evidência fixado no SUBAGENTE 01):**
  - [SUBAGENTE 03] Feature-lock no boundary_guard — depende de 01 — `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
  - [SUBAGENTE 04] Hook Stop — depende de 01 — `src/harness/stop_hook.py`, `src/harness/cli.py`, `tests/test_stop_hook.py`, `tests/test_cli.py`
- **Fase 3 (sequencial — depende de 01 e 04 pela definição compartilhada de "feature em progresso" e pelo schema de evidência):**
  - [SUBAGENTE 05] Segunda máquina de audit (runtime) — depende de 01, 04 — `src/harness/runtime_audit.py`, `src/harness/cli.py`, `tests/test_runtime_audit.py`, `tests/test_cli.py`
- **Fase 4 (gate final — depende de TODOS: 01, 02, 03, 04, 05):**
  - [SUBAGENTE 06] Dogfood E2E da Fase 3 — `tests/e2e/test_contract_dogfood.py`

Ordem de execução recomendada: `{01, 02}` em paralelo → `{03, 04}` em
paralelo → `05` → `06`.
