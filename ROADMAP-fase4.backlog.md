> 🏁 DEMANDA FECHADA — 2026-07-16

# BACKLOG DE EXECUÇÃO - CLAUDE CODE

> Decompõe a Fase 4 do ROADMAP ("Team-Architecture Factory (Nível L3)",
> `ROADMAP.md` linhas ~251-321) em tarefas atômicas para subagentes frios,
> seguindo o Gate de Encerramento por Fase (linhas ~324-362, obrigatório).
> Molde de formato: `ROADMAP-fase3.backlog.md`. Mapa de dependências
> completo ao final do arquivo.
>
> ✅ Revisado por plan-critic + llm-as-judge (Fable). 5 achados reais
> confirmados e corrigidos diretamente nos blocos 01, 02, 04, 08 e 10
> (precedência da heurística de recomendação, teto duro de iterações,
> comparação review-vs-evidência no feature-lock, `on_feature_verified`
> agora acionado de verdade pelo comando `verify`, e o gate de encerramento
> redesenhado para usar sessões de revisor genuinamente independentes em
> vez de uma única sessão roteirizada). 1 achado (histórico de
> `justification`) julgado falso-positivo, sem ajuste. Pronto para
> `run-backlog`.

---

## Decisões do planejador (ambiguidades do ROADMAP.md resolvidas aqui)

O `ROADMAP.md` descreve a Fase 4 em prosa de alto nível; várias decisões de
formato/schema precisam ser fixadas ANTES da execução para que subagentes
frios e independentes não divirjam entre si. Registradas aqui, citadas nos
blocos relevantes:

1. **Modo de execução (Agent Teams vs Subagents).** "Agent Teams" é recurso
   **experimental** do Claude Code sem interface scriptável estável para
   verificação headless determinística (o próprio ROADMAP already flagra
   isso como dependência de disponibilidade declarada). Para não cair em
   "teatro de enforcement" (princípio já fixado em `ROADMAP.md`, seção
   "Fundamentos preservados"), **os artefatos gerados por este backlog são
   SEMPRE compatíveis com Subagents** (formato padrão `.claude/agents/*.md`
   que o Claude Code já executa hoje via `Task`). `mode` é só um RÓTULO
   declarativo gravado em `.harness/team/manifest.json`
   (`"subagents"` por padrão; `"agent-teams"` aceito como valor advisory,
   sem nenhum caminho de código exclusivo dele) — nenhum subagente deste
   backlog deve depender de um recurso de fila de mensagens nativa que não
   pode ser testado de ponta a ponta hoje.
2. **Escopo de "revisão obrigatória".** Em vez de estender o schema de
   `Plans.md`/`contract.py` com um campo por-tarefa (o que exigiria mexer no
   parser da Fase 1, ampliando o raio de impacto deste backlog), a revisão
   obrigatória é **por PROJETO**: se `.harness/team/manifest.json` existe e
   declara os papéis `producer` e `reviewer`, TODA transição de feature para
   `passes:true` exige aprovação do revisor, além da evidência fresca da
   Fase 3. Sem `manifest.json` (projeto sem time compilado), o comportamento
   é EXATAMENTE o da Fase 3 (só evidência) — zero regressão.
3. **Schema do estado de revisão** (`.harness/review/<feature_id>.json`) e do
   manifesto do time (`.harness/team/manifest.json`) são **[design
   próprio]**, fixados no SUBAGENTE 02 abaixo — o ROADMAP só nomeia os
   estados (`pending → in_review → rejected|approved`), não o formato do
   arquivo.
4. **Limite de iterações:** 3 por padrão (ROADMAP aceita 2–3), configurável
   via `max_review_iterations` no manifesto. Estourar o limite **nunca**
   força `approved` — vira uma flag `escalate=True` devolvida por
   `advance`/`record_decision`, consumida como stop condition pelo agente
   (o estado formal continua sendo só os 4 nomeados pelo ROADMAP; não
   inventamos um 5º estado "escalated").
5. **Namespace de arquivos NOVO**, deliberadamente separado de
   `.harness/compiled-state.json` (reconstruído do zero por
   `compiler.py::_write_state`) e de `.harness/compiled-state-session.json`
   (bookkeeping de merge de `settings.json`/hooks): `.harness/team/` e
   `.harness/review/` guardam estado runtime-mutável de negócio (mesma
   natureza de `feature_list.json`/`evidence/`), nunca merge de
   settings/hooks. Nenhum subagente deste backlog escreve em nenhum dos
   dois arquivos de compiled-state existentes.
6. **Audit de time em módulo NOVO** (`src/harness/team_audit.py`), não
   estendendo `audit.py` (diff byte-exato de artefatos compilados
   determinísticos a partir de `harness.yaml` — não conhece agentes de
   time) nem `runtime_audit.py` (invariantes de feature/evidence da Fase 3,
   já coeso). O ROADMAP permite as duas opções ("extensão do audit
   existente **ou** novo módulo"); seguimos o precedente já estabelecido
   pela própria Fase 3 (`runtime_audit.py` nasceu novo, não colado em
   `audit.py`, exatamente pelo mesmo motivo de invariantes distintos).
7. **Supervisor é um leitor de estado, não um daemon.** `harness supervise`
   é uma chamada síncrona única que devolve qual feature deve ser trabalhada
   a seguir (mesmo estilo síncrono de todo o resto da CLI) — não implementa
   loop/processo de longa duração, fila própria, nem executa comandos
   (`verify_cmd`, git, etc.) por conta própria. Toda execução real continua
   passando por `harness verify`/`boundary_guard.py` já existentes.
8. **Os 4 padrões "template"** (Pipeline, Expert Pool, Fan-out/Fan-in,
   Delegação Hierárquica) são **puramente declarativos** neste backlog —
   entram no catálogo YAML com papéis/descrição/quando-usar, sem nenhuma
   state machine ou enforcement dedicado (o ROADMAP reserva enforcement
   real só para Produtor-Revisor e Supervisor).

---

### [SUBAGENTE 01] - Catálogo de padrões + motor de análise/seleção (`teams.py`)

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Criar `src/harness/teams.py` (novo módulo) com o modelo de
  dados do catálogo de padrões de time e as duas primeiras fases do workflow
  de 6 fases do ROADMAP (análise de domínio + seleção de padrão). Criar
  também o catálogo YAML em `teams/patterns/` (raiz do repo, sibling de
  `skills/` — é conteúdo do PLUGIN, não do projeto-alvo) com os 6 padrões:
  `producer-reviewer.yaml` e `supervisor.yaml` (schema completo, papéis com
  `tools` mínimas — usados de verdade pelos SUBAGENTES 02-08) e
  `pipeline.yaml`, `expert-pool.yaml`, `fan-out-fan-in.yaml`,
  `hierarchical-delegation.yaml` (declarativos/simplificados — só
  `name`/`description`/`when_to_use`/`roles[]`, sem detalhe de state
  machine). Este bloco NÃO implementa geração de arquivos `.claude/agents/`
  nem `.claude/skills/` (isso é o SUBAGENTE 03) nem o state machine do
  revisor (SUBAGENTE 02) — só o catálogo + a lógica de escolher qual padrão
  usar.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/analyzer.py` (schema de `RepoProfile`/`Finding`,
    `REPO_PROFILE_PATH`), `src/harness/contract.py` (padrão de dataclasses +
    exceptions do projeto), `src/harness/audit.py` (padrão
    `Finding`/`AuditReport` a NÃO reusar, só para consistência de estilo),
    `skills/plan/SKILL.md` (referência de progressive disclosure e tom),
    `ROADMAP.md` linhas ~251-321 (Fase 4 completa)
  - Modificar: `src/harness/teams.py` (novo), `teams/patterns/producer-reviewer.yaml`
    (novo), `teams/patterns/supervisor.yaml` (novo),
    `teams/patterns/pipeline.yaml` (novo), `teams/patterns/expert-pool.yaml`
    (novo), `teams/patterns/fan-out-fan-in.yaml` (novo),
    `teams/patterns/hierarchical-delegation.yaml` (novo), `tests/test_teams.py`
    (novo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar o catálogo declarativo de padrões de time e o
  > motor de análise/seleção da Fase 4 ("Team-Architecture Factory"), SEM
  > implementar geração de arquivos de agente/skill nem state machine de
  > revisão (isso é escopo de outras tarefas).
  >
  > **Parte 1 — catálogo YAML em `teams/patterns/` (raiz do repo).** Crie 6
  > arquivos. `producer-reviewer.yaml` e `supervisor.yaml` são os dois
  > padrões priorizados — schema completo:
  > ```yaml
  > name: producer-reviewer
  > description: "Produtor implementa uma feature do feature_list.json; revisor valida contra spec.md + evidência da Fase 3 antes de aprovar."
  > when_to_use: "Projeto quer revisão de qualidade automatizada por outro agente, sem gate humano por tarefa."
  > roles:
  >   - name: producer
  >     responsibilities: "Implementa a feature escolhida, roda harness verify, submete para revisão."
  >     tools: [Read, Grep, Glob, Edit, Write, Bash]
  >   - name: reviewer
  >     responsibilities: "Le o diff da feature contra spec.md e a evidencia da Fase 3; aprova ou rejeita com nota; nunca edita codigo de producao."
  >     tools: [Read, Grep, Glob, Bash]
  > ```
  > (`reviewer.tools` NUNCA inclui `Edit`/`Write` — é o invariante que o
  > SUBAGENTE 07/audit de time vai checar depois; fixe isso exatamente assim
  > agora.) `supervisor.yaml` segue o mesmo shape com papéis
  > `supervisor` (tools: `[Read, Grep, Glob, Bash]` — também sem
  > Edit/Write, só orquestra), `producer`, `reviewer`. Os outros 4
  > (`pipeline.yaml`, `expert-pool.yaml`, `fan-out-fan-in.yaml`,
  > `hierarchical-delegation.yaml`) usam só `name`/`description`/
  > `when_to_use`/`roles` (lista de `{name, responsibilities}`, SEM `tools`
  > detalhado — são templates simplificados, não têm enforcement dedicado
  > nesta fase).
  >
  > **Parte 2 — `src/harness/teams.py`.** Dataclasses `TeamRole` (`name: str`,
  > `responsibilities: str`, `tools: list[str] = field(default_factory=list)`)
  > e `TeamPattern` (`name: str`, `description: str`, `when_to_use: str`,
  > `roles: list[TeamRole]`), ambas com `to_dict()`. Função
  > `list_patterns(patterns_dir: Path | None = None) -> list[str]` (nomes dos
  > arquivos `.yaml` em `patterns_dir`, default
  > `Path(__file__).resolve().parents[2] / 'teams' / 'patterns'` — ATENÇÃO:
  > `src/harness/teams.py` tem `parents[0]=src/harness`, `parents[1]=src`,
  > `parents[2]=raiz do repo`; confirme isso rodando
  > `python -c "from pathlib import Path; print(Path('src/harness/teams.py').resolve().parents[2])"`
  > antes de fixar). Função `load_pattern(name: str, patterns_dir: Path | None
  > = None) -> TeamPattern` que lê `<patterns_dir>/<name>.yaml` via
  > `yaml.safe_load` e valida presença de `name`/`description`/`roles`
  > (levanta `TeamError` — nova exceção — citando o arquivo se schema
  > quebrado ou arquivo ausente).
  >
  > **Parte 3 — análise de domínio e seleção (ainda em `teams.py`).**
  > `analyze_domain(target_dir: Path) -> dict` lê
  > `.harness/repo-profile.json` (se existir; ausência não é erro, devolve
  > dict com `profile: None`) e devolve um dict simples
  > `{'profile': <dict ou None>, 'languages': [...], 'has_tests': bool}`
  > (deriva `has_tests` de `profile['test_glob']` não ser `None` — nenhuma
  > lógica nova de varredura de disco, é só leitura do profile já produzido
  > pela Fase 1). `recommend_pattern(domain: dict, description: str) ->
  > tuple[str, str]` devolve `(pattern_name, justificativa)`: heurística
  > SIMPLES e determinística — **ORDEM DE PRECEDÊNCIA IMPORTA, cheque nesta
  > ordem exata (achado de reflect+judge: sinal explícito da descrição tem
  > que vencer `has_tests`, senão o padrão supervisor nunca é recomendado
  > automaticamente em repo real, que quase sempre tem testes):**
  > 1º) se `description` (case-insensitive) contiver qualquer uma de
  > `['supervisor', 'distribuir', 'paralelo', 'multiplas features',
  > 'múltiplas features']`, recomenda `'supervisor'` (justificativa citando
  > o sinal explícito da descrição — isso vence QUALQUER outro sinal,
  > inclusive `has_tests=True`); 2º) senão, se `description` contiver
  > qualquer uma de `['revisão', 'revisao', 'review', 'qualidade']` OU o
  > domínio tiver `has_tests=True`, recomenda `'producer-reviewer'`
  > (justificativa citando o sinal usado); 3º) caso nenhum sinal bata,
  > default `'producer-reviewer'` (é o padrão mais seguro/testado desta
  > fase) com justificativa dizendo isso explicitamente. NÃO tente ser
  > esperto/usar NLP — é uma heurística legível e determinística,
  > documentada no docstring como tal, incluindo a ordem de precedência
  > (o objetivo é ter ALGO determinístico e testável agora; refinar a
  > heurística é trabalho futuro, fora de escopo).
  >
  > Escreva `tests/test_teams.py` cobrindo: `list_patterns` lista os 6 nomes
  > (usando `patterns_dir` apontando para o `teams/patterns/` real do repo);
  > `load_pattern('producer-reviewer')` e `load_pattern('supervisor')`
  > carregam com os papéis certos e `reviewer`/`supervisor` SEM `Edit`/`Write`
  > em `tools`; `load_pattern('inexistente')` levanta `TeamError`;
  > `analyze_domain` com/sem `repo-profile.json` presente; `recommend_pattern`
  > para os TRÊS ramos, incluindo o caso crítico que prova a precedência
  > corrigida: domínio com `has_tests=True` **e** descrição contendo
  > "supervisor" -> DEVE recomendar `'supervisor'`, não `'producer-reviewer'`
  > (é exatamente o cenário que a ordem errada quebrava); mais o default
  > (producer-reviewer sem nenhum sinal) e producer-reviewer por sinal de
  > revisão/testes sem sinal de supervisor. NÃO implemente
  > `render_agent_md`/`render_skill_md`/
  > `install_team_*`/`generate_team` (SUBAGENTE 03/06) nem toque em
  > `boundary_guard.py`/`cli.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_teams.py -q`
  - [ ] `python -c "from harness.teams import list_patterns; print(list_patterns())"` lista 6 nomes

---

### [SUBAGENTE 02] - Produtor-Revisor: state machine de revisão (`review.py`)

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Criar `src/harness/review.py` com o state machine
  `pending → in_review → rejected|approved` **[design próprio]** para o
  veredito do revisor sobre uma feature, incluindo o limite de 2-3 iterações
  que ESCALA ao humano (nunca força aprovação) e o gate adicional para
  diffs de teste (justificativa exigida para aprovar mudança em arquivo de
  teste). Este bloco NÃO mexe em `boundary_guard.py` (enforcement é o
  SUBAGENTE 04, que IMPORTA as funções daqui) nem em `teams.py`/CLI — só a
  lógica pura de state machine + I/O do arquivo de estado.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/verify.py` (padrão de exceções `VerifyError`/
    `VerifyFailedError` a espelhar em estilo), `src/harness/contract.py`
    (`FEATURE_LIST_FILE`, schema de feature), `src/harness/analyzer.py`
    (`REPO_PROFILE_PATH`, schema de `test_glob`), `src/harness/verification/tdd_loop.py`
    (`_glob_to_regex` — IMPORTAR, não reimplementar; já é o padrão
    estabelecido por `analyzer.py`/`audit.py`)
  - Modificar: `src/harness/review.py` (novo), `tests/test_review.py` (novo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `src/harness/review.py`, o state machine de
  > revisão do padrão Produtor-Revisor. Schema FIXADO do arquivo de estado
  > — `.harness/review/<feature_id>.json`:
  > ```json
  > {
  >   \"feature_id\": \"T-01\",
  >   \"status\": \"pending\",
  >   \"iteration\": 0,
  >   \"max_iterations\": 3,
  >   \"history\": [],
  >   \"justification\": null,
  >   \"updated_at\": \"2026-07-16T12:00:00+00:00\"
  > }
  > ```
  > `status` é sempre um de `'pending'`, `'in_review'`, `'rejected'`,
  > `'approved'` (NUNCA um 5º valor, mesmo ao estourar o limite de
  > iterações). `history` é uma lista de
  > `{\"iteration\": int, \"decision\": \"approved\"|\"rejected\",
  > \"note\": str, \"at\": iso8601}`. `updated_at` é
  > `datetime.now(timezone.utc).isoformat()` a cada escrita.
  >
  > Implemente: `ReviewError(Exception)` (erro de uso — transição inválida,
  > justificativa faltando). `load_review(target_dir: Path, feature_id: str)
  > -> dict` — lê `.harness/review/<feature_id>.json` se existir; se não
  > existir, devolve o registro DEFAULT acima (`status='pending'`,
  > `iteration=0`, etc., SEM gravar em disco — só materializa quando alguma
  > função de transição grava de verdade). `submit_for_review(target_dir:
  > Path, feature_id: str, max_iterations: int = 3) -> dict`: só permitido a
  > partir de `status in ('pending', 'rejected')` (senão `ReviewError`
  > citando o estado atual); **teto duro (achado de reflect+judge: sem isso
  > a escalação é só um aviso, o agente pode resubmeter pra sempre)** — se
  > `status == 'rejected'` E o registro já tem `iteration >= max_iterations`
  > (usando o `max_iterations` JÁ GRAVADO no arquivo), levanta `ReviewError`
  > citando 'limite de max_iterations atingido na iteração anterior — não
  > resubmeta, escale ao humano (ele pode destravar subindo
  > max_review_iterations no manifesto ou resetando o registro de revisão)';
  > só prossegue se `iteration < max_iterations`. Passando essa checagem:
  > grava `status='in_review'`, incrementa `iteration` em 1, preserva
  > `history`/`max_iterations` (usa o `max_iterations` JÁ GRAVADO no arquivo
  > se ele existir, ignora o parâmetro nesse caso — o parâmetro só vale para
  > a primeira criação do registro).
  >
  > `is_test_diff(feature: dict, target_dir: Path) -> bool`: `True` se algum
  > caminho em `feature.get('files') or []` casa o `test_glob` do
  > `.harness/repo-profile.json` (via `_glob_to_regex` IMPORTADA de
  > `harness.verification.tdd_loop` — não reimplemente o algoritmo); `False`
  > se não houver profile ou `test_glob`.
  >
  > `@dataclass class ReviewResult: status: str; iteration: int; escalate:
  > bool; message: str`.
  >
  > `record_decision(target_dir: Path, feature_id: str, feature: dict,
  > decision: str, note: str, justification: str | None = None) ->
  > ReviewResult`: só permitido a partir de `status == 'in_review'` (senão
  > `ReviewError`); `decision` deve ser `'approved'` ou `'rejected'` (senão
  > `ReviewError`). Se `decision == 'approved'` E `is_test_diff(feature,
  > target_dir)` for `True`: `justification` (str não-vazia após `.strip()`)
  > é OBRIGATÓRIA — sem ela, `ReviewError` citando
  > 'aprovar diff de teste exige justificativa de por que a expectativa
  > mudou' — proteção da Fase 2 contra o agente reescrever o próprio teste
  > pra passar, agora também gateada pelo revisor. Grave `justification` no
  > registro quando fornecida (mesmo em decisões não relacionadas a teste,
  > se o chamador passar). Ao gravar: acrescente entrada em `history` com o
  > `iteration` ATUAL; se `decision == 'approved'`, `status='approved'`,
  > `escalate=False`. Se `decision == 'rejected'`: `escalate = (iteration >=
  > max_iterations)`; `status` continua `'rejected'` INDEPENDENTE de
  > `escalate` (nunca vira `'approved'` por estourar o limite — é a
  > divergência deliberada da fonte que o ROADMAP.md exige). `message` do
  > `ReviewResult` é uma frase legível (ex.: 'aprovado na iteração N' /
  > 'rejeitado na iteração N — refaça e resubmeta' / 'rejeitado na iteração
  > N — limite de max_iterations atingido, ESCALE ao humano em vez de
  > insistir').
  >
  > Escreva `tests/test_review.py` cobrindo: `load_review` default
  > sem arquivo; `submit_for_review` de `pending`->`in_review` (iteration=1);
  > `submit_for_review` a partir de `in_review`/`approved` levanta
  > `ReviewError`; `record_decision` aprovado a partir de `in_review` grava
  > `approved`/`escalate=False`; `record_decision` rejeitado com
  > `iteration < max_iterations` -> `escalate=False`, ciclo
  > rejected->submit_for_review->record_decision repetido até
  > `iteration == max_iterations` -> `escalate=True` E `status` continua
  > `'rejected'` (NUNCA `'approved'`); UMA resubmissão A MAIS depois disso
  > (`submit_for_review` com `iteration == max_iterations` já gravado)
  > levanta `ReviewError` (teto duro — prova que a escalação bloqueia
  > resubmissão, não é só aviso); `record_decision` a partir de
  > `pending`/`approved` levanta `ReviewError`; aprovar diff que toca
  > `test_glob` sem `justification` levanta `ReviewError`; com
  > `justification` não-vazia, aprova normalmente; `is_test_diff` true/false
  > conforme `files[]`/`test_glob`. NÃO toque em `boundary_guard.py`,
  > `teams.py` ou `cli.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_review.py -q`

---

### [SUBAGENTE 03] - Geração de agentes e skills do time (`teams.py`)

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Estender `src/harness/teams.py` (SUBAGENTE 01) com a
  geração dos artefatos `.claude/agents/<papel>.md` e
  `.claude/skills/<capacidade>/SKILL.md` do time, a partir de um
  `TeamPattern` já carregado. **Depende do SUBAGENTE 01** (dataclasses
  `TeamRole`/`TeamPattern`, `load_pattern`).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/teams.py` (dataclasses do SUBAGENTE 01),
    `skills/plan/SKILL.md` (frontmatter `name`/`description`/`when_to_use`/
    `argument-hint`/`disable-model-invocation` — mesmo shape a reusar),
    `src/harness/lifecycle.py` (padrão de bloco gerenciado com delimitadores
    próprios + progressive disclosure para arquivo de detalhe — mesmo
    padrão a reaplicar para cada agente gerado)
  - Modificar: `src/harness/teams.py`, `tests/test_teams.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é ESTENDER `src/harness/teams.py` (já existe, com
  > `TeamRole`/`TeamPattern`/`load_pattern`/`list_patterns`/`analyze_domain`/
  > `recommend_pattern` — não toque nessas funções) com geração dos
  > arquivos de agente e skill do time.
  >
  > **Formato FIXADO do arquivo de agente** (`.claude/agents/<role.name>.md`
  > no PROJETO-ALVO, não no plugin) — frontmatter YAML + bloco gerenciado
  > com delimitadores PRÓPRIOS `<!-- harness:team:agent:begin -->`/
  > `<!-- harness:team:agent:end -->` (mesma técnica de
  > `lifecycle.py::LIFECYCLE_BEGIN`/`END` — nunca reescreve o arquivo
  > inteiro se ele já tiver conteúdo do usuário fora do bloco):
  > ```markdown
  > ---
  > name: <role.name>
  > description: <role.responsibilities>
  > tools: <role.tools join por vírgula, ex. \"Read, Grep, Glob, Bash\">
  > ---
  >
  > <!-- harness:team:agent:begin -->
  > # Papel: <role.name> (time <pattern.name>, gerado pelo harness-creator)
  >
  > <role.responsibilities>
  >
  > Ferramentas mínimas deste papel: <role.tools>. NÃO peça nem use
  > ferramentas fora desta lista — o audit de time (`harness audit-team`)
  > detecta e reporta qualquer drift.
  > <!-- harness:team:agent:end -->
  > ```
  > Implemente `render_agent_md(role: TeamRole, pattern: TeamPattern) -> str`
  > (puro, devolve a string acima) e `install_team_agents(target_dir: Path,
  > pattern: TeamPattern) -> list[Path]` que grava um arquivo por
  > `role in pattern.roles` em `target_dir/.claude/agents/<role.name>.md`
  > — se o arquivo já existir e tiver os delimitadores, substitui SÓ o
  > conteúdo entre eles (regex `re.DOTALL`, mesmo padrão de
  > `lifecycle.py::install_lifecycle`); se não tiver o arquivo ainda, cria
  > com o frontmatter+bloco completo. Role sem `tools` declaradas (os 4
  > padrões template do SUBAGENTE 01) usa `tools: \"\"` no frontmatter (Claude
  > Code trata ausência/vazio como 'todas as ferramentas' — documente esse
  > efeito no docstring, mas não tente restringir isso agora, é o
  > comportamento correto para papéis sem `tools` fixadas no catálogo).
  >
  > **Formato FIXADO do arquivo de skill** (`.claude/skills/<slug>/SKILL.md`
  > no projeto-alvo) — `<slug>` é `role.name` (kebab-case, já é: producer,
  > reviewer, supervisor, etc.), mesmo shape de frontmatter de
  > `skills/plan/SKILL.md`:
  > ```markdown
  > ---
  > name: <role.name>
  > description: <role.responsibilities>
  > when_to_use: Papel <role.name> do time <pattern.name> (gerado pelo harness-creator; ver .claude/agents/<role.name>.md para o agente correspondente).
  > disable-model-invocation: false
  > ---
  >
  > <!-- harness:team:skill:begin -->
  > # <role.name> — time <pattern.name>
  >
  > <role.responsibilities>
  > <!-- harness:team:skill:end -->
  > ```
  > Implemente `render_skill_md(role: TeamRole, pattern: TeamPattern) -> str`
  > e `install_team_skills(target_dir: Path, pattern: TeamPattern) ->
  > list[Path]` (mesma técnica de substituição por delimitadores;
  > cria `target_dir/.claude/skills/<role.name>/SKILL.md`, criando os
  > diretórios necessários).
  >
  > Escreva testes em `tests/test_teams.py` (arquivo já existe — ACRESCENTE,
  > não reescreva os testes do SUBAGENTE 01): `render_agent_md` produz o
  > frontmatter/bloco esperado para um `TeamRole` com e sem `tools`;
  > `install_team_agents` grava um arquivo por papel do padrão
  > `producer-reviewer` (2 arquivos: producer.md, reviewer.md) com o
  > conteúdo certo; rodar `install_team_agents` duas vezes é idempotente
  > (substitui só o bloco, não duplica); mesmo conjunto de testes para
  > `render_skill_md`/`install_team_skills`. NÃO implemente
  > `render_orchestrator_md`/`generate_team` (SUBAGENTE 06) nem toque em
  > `boundary_guard.py`/`cli.py`/`review.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_teams.py -q`

---

### [SUBAGENTE 04] - Enforcement do veto do revisor no `boundary_guard.py`

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Estender o feature-lock da Fase 3 (`boundary_guard.py`,
  função `evaluate_feature_list_edit` + a cópia inline no script standalone)
  para, quando `.harness/team/manifest.json` existir e declarar os papéis
  `producer`+`reviewer` (decisão do planejador #2 acima), exigir também
  `.harness/review/<id>.json` com `status == 'approved'` (importado de
  `harness.review`, NUNCA reimplementado) e `updated_at` mais novo que o
  último commit — além da evidência fresca já exigida pela Fase 3 — para
  QUALQUER transição de feature para `passes:true`. **Adicionalmente (achado
  de reflect+judge: aprovação pode ficar obsoleta se o produtor editar o
  código de novo DEPOIS de aprovado e regravar evidência ANTES de
  commitar — comparar só contra o commit não pega isso)** exija também que
  `review.updated_at` não seja mais antigo que `evidencia.recorded_at`
  daquela feature (a aprovação precisa ser posterior OU igual à ÚLTIMA
  evidência gravada; se o produtor rodar `harness verify` de novo depois de
  aprovado, a evidência fica mais nova que a aprovação e o guard deve negar
  até nova aprovação cobrindo essa evidência). Sem `manifest.json` (ou
  sem os dois papéis), comportamento IDÊNTICO à Fase 3 (zero regressão).
  Gate adicional: se a feature transicionada tem `files[]` tocando
  `test_glob` (via `harness.review.is_test_diff`, IMPORTADA — não
  reimplementada), o registro de revisão aprovado precisa ter
  `justification` não-vazia (defesa em profundidade — `review.py`
  já impede gravar aprovação de diff de teste sem justificativa, mas o
  `boundary_guard` reconfirma lendo o arquivo, caso ele tenha sido editado
  por fora da API de `review.py`). **Depende do SUBAGENTE 02**
  (`harness.review` precisa existir e estar com o schema fixado).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/boundary_guard.py` (inteiro — `evaluate_feature_list_edit`
    IMPORTÁVEL e a cópia standalone `_evaluate_feature_list_edit` dentro da
    string de `render_boundary_guard()`), `src/harness/review.py` (schema de
    `.harness/review/<id>.json` e `is_test_diff`, fixados pelo SUBAGENTE 02),
    `tests/test_boundary_guard.py`
  - Modificar: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é estender `src/harness/boundary_guard.py` para
  > reconhecer o veto do revisor (padrão Produtor-Revisor da Fase 4) como
  > parte do feature-lock já existente (Fase 3). NÃO toque no runtime floor,
  > na proteção de teste genérica, nem em nenhuma outra lógica do arquivo
  > além do que está descrito abaixo.
  >
  > Em `_transitions_to_true`/`evaluate_feature_list_edit` (versão
  > IMPORTÁVEL) e na cópia inline dentro do script standalone gerado por
  > `render_boundary_guard()` (as DUAS precisam ficar sincronizadas — mesmo
  > padrão de sincronização já documentado no módulo para o feature-lock da
  > Fase 3): depois de confirmar evidência fresca para cada feature
  > transicionada (lógica já existente, não mude), adicione uma checagem
  > NOVA: leia `.harness/team/manifest.json` (relativo a `cwd`/`base`, mesmo
  > padrão de leitura defensiva de JSON já usado no arquivo — ausência ou
  > JSON inválido = time não compilado, pula esta checagem inteira, mantém
  > o comportamento da Fase 3 intocado). Se o manifesto existir e
  > `set(manifest.get('roles', []))` contiver tanto `'producer'` quanto
  > `'reviewer'`: para cada feature já confirmada com evidência fresca,
  > exija ADICIONALMENTE que `.harness/review/<id>.json` exista, seja JSON
  > válido, tenha `status == 'approved'` e `updated_at` (parseável ISO8601,
  > mesma função `_parse_iso8601` já existente no arquivo) mais novo que o
  > `commit_ts` (mesmo `_read_last_commit_timestamp` já existente — sem
  > timestamp de commit, exija só `status == 'approved'`, sem comparação de
  > data, mesma postura já usada para a evidência). **Checagem adicional
  > (achado de reflect+judge — sem isso uma aprovação antiga cobre um diff
  > que o revisor nunca viu):** exija TAMBÉM que `review.updated_at` não
  > seja mais antigo que `evidencia.recorded_at` daquela mesma feature (leia
  > `.harness/evidence/<id>.json` — já lido pela checagem de evidência
  > fresca existente, reuse o dict já carregado, não releia o arquivo) —
  > compare os dois timestamps parseados via `_parse_iso8601`; se
  > `review.updated_at < evidencia.recorded_at`, é `deny` (a evidência mais
  > recente é posterior à aprovação — o revisor aprovou um diff antigo,
  > precisa reaprovar). Se a feature (dados de
  > `new_data`, já disponíveis na função) tiver `files[]` tocando o
  > `test_glob` do `.harness/repo-profile.json` (implemente uma checagem
  > standalone equivalente a `harness.review.is_test_diff` — SEM importar
  > `harness.review` na cópia do script, que é stdlib-only; na versão
  > IMPORTÁVEL, IMPORTE de verdade `harness.review.is_test_diff` em vez de
  > duplicar), exija também que o registro de revisão tenha
  > `justification` não-vazia (após strip). QUALQUER uma dessas checagens
  > faltando -> `deny` citando o(s) id(s) e o problema específico (ex.:
  > 'T-02: revisão pendente/rejeitada — rode harness review T-02 approve
  > antes' ou 'T-02: aprovação de diff de teste sem justificativa
  > registrada'). Todas passando (evidência fresca + revisão aprovada fresca
  > + justificativa quando aplicável) -> `allow`, mesma mensagem de sucesso
  > já usada, ampliada para citar também a confirmação de revisão.
  >
  > Adicione testes em `tests/test_boundary_guard.py`: sem
  > `.harness/team/manifest.json` -> comportamento IDÊNTICO ao já testado da
  > Fase 3 (evidência fresca basta, sem checar revisão) — rode os testes já
  > existentes do feature-lock da Fase 3 como estão, sem alterá-los, para
  > confirmar isso; com manifesto declarando producer+reviewer e evidência
  > fresca mas SEM `.harness/review/<id>.json` -> deny; com review existente
  > mas `status='rejected'`/`'in_review'`/`'pending'` -> deny; com
  > `status='approved'` mas `updated_at` mais antigo que o commit -> deny;
  > com `status='approved'` mas `updated_at` mais antigo que
  > `evidencia.recorded_at` (aprovação obsoleta — evidência foi regravada
  > depois da aprovação) -> deny; com `status='approved'` fresco (mais novo
  > que commit E que evidência) -> allow; feature com `files[]` tocando
  > `test_glob`, review aprovado SEM `justification` -> deny; com
  > `justification` preenchida -> allow. NÃO altere nomes de funções
  > existentes nem o comportamento do runtime floor/proteção de teste
  > genérica."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_boundary_guard.py -q`
  - [ ] `python -m pytest tests/e2e/test_boundary_flow.py -q`

---

### [SUBAGENTE 05] - Supervisor: despacho dinâmico (`supervisor.py`)

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Criar `src/harness/supervisor.py`: leitor de estado que
  decide qual feature do `feature_list.json` deve ser trabalhada a seguir,
  respeitando `depends[]` (campo já parseado por `contract.py` desde a Fase
  1, mas NUNCA ordenado por ninguém até agora — este é o primeiro
  consumidor real), e que aciona a submissão para revisão (via
  `harness.review.submit_for_review`, IMPORTADA) assim que uma feature tem
  evidência fresca. NÃO é um daemon/loop — uma chamada síncrona que devolve
  um resultado e termina (decisão do planejador #7). NÃO executa nenhum
  comando (`verify_cmd`, git, etc.) por conta própria. **Depende do
  SUBAGENTE 02** (`harness.review`).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/contract.py` (`FEATURE_LIST_FILE`, schema de feature
    com `depends[]`), `src/harness/review.py` (`submit_for_review`,
    `load_review`, fixados pelo SUBAGENTE 02), `src/harness/verify.py`
    (`EVIDENCE_DIR`, para checar se a feature já tem evidência fresca —
    IMPORTE `compute_files_hash`, não reimplemente), `src/harness/stop_hook.py`
    (`needs_verification`/`is_feature_in_progress` — reaproveite se fizer
    sentido para decidir 'evidência ainda válida', não reimplemente a lógica
    de hash/git diff)
  - Modificar: `src/harness/supervisor.py` (novo), `tests/test_supervisor.py`
    (novo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `src/harness/supervisor.py`. Implemente
  > `ready_features(feature_list: dict) -> list[dict]`: devolve, na MESMA
  > ordem em que aparecem em `feature_list['features']`, as features com
  > `passes` != `True` cujos `depends` (lista de ids) estão TODOS com
  > `passes == True` no mesmo `feature_list` (dependência para um id
  > inexistente é tratada como NÃO satisfeita — a feature nunca fica pronta;
  > não levante exceção, apenas não inclua na lista). `dispatch_next(
  > target_dir: Path) -> dict | None`: lê `.harness/feature_list.json` (via
  > `harness.contract.FEATURE_LIST_FILE`; ausência do arquivo -> devolve
  > `None`, não levanta), chama `ready_features`, devolve a PRIMEIRA da
  > lista ou `None` se vazia. Esta função é SÓ LEITURA — nunca escreve nada,
  > nunca executa `verify_cmd`/git/subprocess de qualquer tipo.
  >
  > `on_feature_verified(target_dir: Path, feature_id: str,
  > max_review_iterations: int = 3) -> dict | None`: chamada depois que
  > `harness verify <feature_id>` já rodou com sucesso (evidência gravada).
  > Leia `.harness/team/manifest.json` (ausência ou JSON inválido -> devolve
  > `None`, time não compilado, nada a fazer); se o manifesto declarar os
  > papéis `producer`+`reviewer` (mesma checagem do SUBAGENTE 04:
  > `{'producer','reviewer'} <= set(manifest.get('roles', []))`), chame
  > `harness.review.submit_for_review(target_dir, feature_id,
  > max_iterations=manifest.get('max_review_iterations',
  > max_review_iterations))` (IMPORTADA — não reimplemente a transição) e
  > devolva o dict resultante (`load_review` depois de gravar, ou o valor de
  > retorno de `submit_for_review` se ela já devolver o dict completo —
  > confira a assinatura real fixada pelo SUBAGENTE 02 e ajuste). Sem os dois
  > papéis no manifesto, devolve `None` sem chamar `submit_for_review`
  > (mesma postura de zero-op do SUBAGENTE 04 quando não há time compilado).
  >
  > Escreva `tests/test_supervisor.py` cobrindo: `ready_features` com feature
  > sem dependências (sempre pronta se `passes=False`); com dependência
  > satisfeita/não satisfeita; com dependência para id inexistente (nunca
  > pronta); ordem preservada quando múltiplas estão prontas.
  > `dispatch_next` sem `feature_list.json` -> `None`; com uma feature pronta
  > -> devolve ela; com todas concluídas ou nenhuma pronta -> `None`.
  > `on_feature_verified` sem manifesto -> `None`, sem chamar
  > `submit_for_review`; com manifesto sem os dois papéis -> `None`; com
  > manifesto completo -> chama `submit_for_review` de verdade e o registro
  > em `.harness/review/<id>.json` reflete `status='in_review'`. NÃO
  > implemente nenhum comando de CLI (`harness supervise` é o SUBAGENTE 08)
  > nem toque em `teams.py`/`boundary_guard.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_supervisor.py -q`

---

### [SUBAGENTE 06] - Integração e orquestração: `generate_team()` (`teams.py`)

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Estender `src/harness/teams.py` com o entrypoint de topo
  `generate_team()` que compõe as fases 2-5 do workflow do ROADMAP (design
  já resolvido pelo SUBAGENTE 01/03; aqui é só a COMPOSIÇÃO): escolhe/valida
  o padrão, gera agentes+skills (SUBAGENTE 03), grava o template de
  orquestrador (novo nesta tarefa) e o manifesto `.harness/team/manifest.json`
  (schema fixado aqui — outras tarefas, SUBAGENTE 04/05/07/08, já foram
  escritas ASSUMINDO este schema exato: `roles: list[str]`,
  `max_review_iterations: int`; se algo divergir, ajuste ESTE bloco para
  bater com o que os outros já esperam, nunca o contrário). **Depende dos
  SUBAGENTES 01, 03 e 05** (usa `load_pattern`/`install_team_agents`/
  `install_team_skills`; cita `supervisor.py` na documentação gerada quando
  o padrão é `supervisor`).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/teams.py` (tudo dos SUBAGENTES 01/03),
    `src/harness/lifecycle.py` (padrão de progressive disclosure —
    `LIFECYCLE_BEGIN`/`END` + arquivo de detalhe `.harness/LIFECYCLE.md` — a
    replicar para o time), `src/harness/supervisor.py` (SUBAGENTE 05, só
    para citar o comando `harness supervise` na documentação gerada, sem
    importar nada dele)
  - Modificar: `src/harness/teams.py`, `tests/test_teams.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é ESTENDER `src/harness/teams.py` (já tem
  > `TeamRole`/`TeamPattern`/`load_pattern`/`list_patterns`/`analyze_domain`/
  > `recommend_pattern`/`render_agent_md`/`install_team_agents`/
  > `render_skill_md`/`install_team_skills` — não toque nessas funções) com
  > a integração final.
  >
  > **Delimitadores próprios** `TEAM_BEGIN = '<!-- harness:team:begin -->'`/
  > `TEAM_END = '<!-- harness:team:end -->'` (distintos de
  > `LIFECYCLE_BEGIN`/`END` de `lifecycle.py` e de `AGENTS_BEGIN`/`END` de
  > `compiler.py` — os três blocos convivem no mesmo `AGENTS.md`).
  > `render_team_block(pattern: TeamPattern, mode: str) -> str`: bloco curto
  > (progressive disclosure, mesmo estilo de
  > `lifecycle.py::render_lifecycle_block`) citando o padrão escolhido, os
  > papéis e seus arquivos (`.claude/agents/<role>.md`), e apontando para o
  > detalhe em `.harness/TEAM.md`. Se `pattern.name == 'supervisor'`,
  > inclua uma linha citando `harness supervise` como o comando que decide
  > a próxima feature a trabalhar. `render_team_detail(pattern: TeamPattern,
  > mode: str) -> str`: conteúdo completo de `.harness/TEAM.md` — um
  > parágrafo por papel (responsabilidades + ferramentas mínimas), a regra
  > do feature-lock estendido (`passes:true` exige evidência fresca E
  > aprovação do revisor quando o time declara producer+reviewer — cite o
  > SUBAGENTE 04/`boundary_guard.py`), o limite de iterações e a regra de
  > escalação (nunca força aprovação), e o `mode` (`'subagents'` ou
  > `'agent-teams'`) com a ressalva de que `'agent-teams'` é só rótulo
  > advisory nesta versão do plugin (recurso experimental do Claude Code
  > sem caminho de código dedicado — decisão do planejador #1 do backlog).
  >
  > `install_team_docs(target_dir: Path, pattern: TeamPattern, mode: str) ->
  > tuple[Path, Path]`: aplica `render_team_block`/`render_team_detail` em
  > `target_dir/AGENTS.md` (substituição por delimitadores, criando o
  > arquivo com cabeçalho mínimo se não existir — MESMA técnica de
  > `lifecycle.py::install_lifecycle`, nunca apaga os blocos de
  > `compiler.py`/`lifecycle.py` que já possam estar no arquivo) e
  > `target_dir/.harness/TEAM.md`.
  >
  > Schema FIXADO do manifesto — `target_dir/.harness/team/manifest.json`:
  > ```json
  > {
  >   \"pattern\": \"producer-reviewer\",
  >   \"mode\": \"subagents\",
  >   \"roles\": [\"producer\", \"reviewer\"],
  >   \"max_review_iterations\": 3,
  >   \"generated_at\": \"2026-07-16T12:00:00+00:00\"
  > }
  > ```
  > `roles` é `[r.name for r in pattern.roles]`. Implemente
  > `install_team_manifest(target_dir: Path, pattern: TeamPattern, mode: str,
  > max_review_iterations: int = 3) -> Path` que grava esse JSON em
  > `target_dir/.harness/team/manifest.json` (cria os diretórios
  > necessários; SEMPRE sobrescreve — este arquivo é determinístico a
  > partir do padrão escolhido, mesma natureza de `init.sh`/`init.ps1` em
  > `templates.py`, nunca é editado manualmente pelo agente).
  >
  > `@dataclass class TeamGenerationResult: pattern: str; mode: str; roles:
  > list[str]; agents_written: list[Path]; skills_written: list[Path];
  > agents_md: Path; team_detail: Path; manifest: Path`.
  >
  > `generate_team(target_dir: Path, pattern_name: str, mode: str =
  > 'subagents', max_review_iterations: int = 3, patterns_dir: Path | None =
  > None) -> TeamGenerationResult`: carrega o padrão (`load_pattern`,
  > propaga `TeamError` se inválido — NÃO recomenda pattern aqui, quem chama
  > já decidiu `pattern_name`, seja por `recommend_pattern` seja por escolha
  > explícita do humano), chama `install_team_agents`, `install_team_skills`,
  > `install_team_docs`, `install_team_manifest`, nessa ordem, e monta o
  > `TeamGenerationResult`.
  >
  > Acrescente testes em `tests/test_teams.py`: `render_team_block`/
  > `render_team_detail` citam o padrão e os papéis certos;
  > `install_team_docs` idempotente (substitui só o bloco, preserva
  > conteúdo do usuário e os blocos de `compiler.py`/`lifecycle.py` se
  > presentes no mesmo `AGENTS.md` de teste); `install_team_manifest` grava
  > o schema exato acima; `generate_team` com `pattern_name='producer-reviewer'`
  > devolve um `TeamGenerationResult` com 2 agentes/2 skills escritos e os
  > 3 arquivos de doc/manifesto no lugar certo; `generate_team` com
  > `pattern_name` inválido propaga `TeamError`. NÃO implemente nenhum
  > comando de CLI (SUBAGENTE 08) nem `team_audit.py` (SUBAGENTE 07)."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_teams.py -q`

---

### [SUBAGENTE 07] - Audit de time (`team_audit.py`)

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Criar `src/harness/team_audit.py` (módulo NOVO, decisão
  do planejador #6): detecta papel órfão (agente em `.claude/agents/` sem
  papel correspondente no `manifest.json`/padrão atual), revisor com
  ferramentas além do papel (frontmatter `tools:` do agente `reviewer`/
  `supervisor` excede o `tools` mínimo declarado no catálogo YAML), e drift
  do bloco gerenciado dos agentes (conteúdo entre
  `<!-- harness:team:agent:begin/end -->` diverge do que
  `teams.render_agent_md` geraria hoje). **Depende dos SUBAGENTES 01 e 03**
  (`load_pattern`, formato do bloco gerenciado do agente).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/runtime_audit.py` (padrão `RuntimeFinding`/
    `RuntimeAuditReport`/`_finish`/tabela de penalidade — espelhar o
    ESTILO, classes PRÓPRIAS, não importar), `src/harness/teams.py`
    (`load_pattern`, `render_agent_md`, delimitadores
    `<!-- harness:team:agent:begin/end -->`), `src/harness/cli.py` (padrão
    do subcomando `audit-runtime`)
  - Modificar: `src/harness/team_audit.py` (novo), `tests/test_team_audit.py`
    (novo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `src/harness/team_audit.py`, mecanismo de
  > auditoria DISTINTO de `audit.py` (diff byte-exato de artefatos
  > compilados a partir de `harness.yaml`) e de `runtime_audit.py`
  > (invariantes de feature/evidence da Fase 3) — audita especificamente os
  > artefatos de TIME gerados pela Fase 4.
  >
  > Dataclasses PRÓPRIAS (não importe de `audit.py`/`runtime_audit.py`):
  > `TeamFinding` (`severity`/`code`/`message`/`fix`, mesmo shape) e
  > `TeamAuditReport` (`score`, `findings`, `to_dict`/`to_json`, MESMA
  > tabela de penalidade `critical=40/warning=15/info=5`).
  >
  > `audit_team(target_dir: Path, patterns_dir: Path | None = None) ->
  > TeamAuditReport`. Passos: (1) leia
  > `target_dir/.harness/team/manifest.json` — ausência é `info` ('nenhum
  > time compilado ainda — rode harness team generate'), devolve relatório
  > cedo com score 100 (ausência de time NÃO é erro, é estado válido de
  > projeto sem Fase 4 ativa); JSON inválido é `critical`. (2) Carregue o
  > `TeamPattern` referenciado por `manifest['pattern']` via
  > `harness.teams.load_pattern` (propague o `patterns_dir`, para testes
  > poderem apontar para um catálogo sintético) — se o padrão não existir
  > mais no catálogo, `critical` ('padrão do manifesto não existe mais no
  > catálogo'), pare aqui. (3) **Papel órfão:** para cada arquivo
  > `.md` em `target_dir/.claude/agents/`, extraia o `name:` do
  > frontmatter (parse simples de YAML entre `---`/`---`, mesmo padrão de
  > `contract.py::parse_spec` para frontmatter — reaproveite a MESMA técnica
  > de delimitação, não precisa importar `contract.py`, só replicar o
  > padrão de leitura); se o `name` não estiver em
  > `{r.name for r in pattern.roles}`, `warning` citando o arquivo ('papel
  > órfão: agente não corresponde a nenhum papel do padrão atual'). (4)
  > **Revisor/supervisor com ferramentas além do papel:** para cada
  > `role in pattern.roles` com `role.tools` não-vazia, leia o `tools:` do
  > frontmatter do agente correspondente (se o arquivo não existir,
  > `critical` — 'papel do padrão sem agente gerado'; rode
  > `harness team generate` novamente); parse como lista separada por
  > vírgula; qualquer ferramenta presente no arquivo mas AUSENTE em
  > `role.tools` é `critical` citando o papel e a(s) ferramenta(s) extra(s)
  > — é o invariante mais importante deste audit: um `reviewer`/`supervisor`
  > NUNCA deveria ganhar `Edit`/`Write` por edição manual do arquivo
  > gerado. (5) **Drift do bloco gerenciado:** para cada agente com arquivo
  > presente, recompute `harness.teams.render_agent_md(role, pattern)` e
  > compare o BLOCO (conteúdo entre `<!-- harness:team:agent:begin -->`/
  > `<!-- harness:team:agent:end -->`, extraído por regex do arquivo real)
  > com o bloco correspondente do texto recém-renderizado; divergência é
  > `warning` ('bloco gerenciado do agente diverge do catálogo atual — rode
  > harness team generate para ressincronizar'). Registre `harness
  > audit-team --dir <alvo>` em `src/harness/cli.py`? NÃO — isso é escopo do
  > SUBAGENTE 08, não toque em `cli.py` aqui.
  >
  > Escreva `tests/test_team_audit.py` cobrindo cada checagem isoladamente,
  > usando um `patterns_dir` sintético (`tmp_path`) com um YAML de padrão de
  > teste: sem `manifest.json` -> score 100, finding `info`; manifesto
  > citando padrão inexistente -> `critical`; agente órfão -> `warning`;
  > papel do padrão sem agente gerado -> `critical`; agente com ferramenta
  > extra além de `role.tools` -> `critical`; bloco gerenciado divergente
  > (edite manualmente o texto entre os delimitadores no teste) ->
  > `warning`; caso saudável (time gerado de verdade via
  > `teams.generate_team`, sem nenhuma edição manual) -> score 100, zero
  > findings. NÃO toque em `audit.py`, `runtime_audit.py` ou `cli.py`."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_team_audit.py -q`
  - [ ] `python -m pytest tests/test_audit.py tests/test_runtime_audit.py -q` (prova que os dois mecanismos antigos continuam intocados)

---

### [SUBAGENTE 08] - CLI: `team design|generate`, `review`, `supervise`, `audit-team`

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Registrar em `src/harness/cli.py` os subcomandos da Fase
  4: `harness team design` (dry-run: análise + recomendação, NÃO escreve
  nada), `harness team generate` (escreve os artefatos do time),
  `harness review <feature-id> submit|approve|reject` (transições do state
  machine), `harness supervise` (próxima feature a trabalhar), `harness
  audit-team` (score do audit de time). **Depende dos SUBAGENTES 02, 05, 06,
  07** (todos os módulos que a CLI vai importar precisam já existir com a
  assinatura final).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/cli.py` (inteiro — padrão de todos os subparsers
    existentes, em especial `verify`/`audit-runtime`/`compile-contract`),
    `src/harness/teams.py`, `src/harness/review.py`, `src/harness/supervisor.py`,
    `src/harness/team_audit.py` (assinaturas finais dos 4 módulos),
    `tests/test_cli.py` (padrão de teste via
    `monkeypatch.setattr(sys, 'argv', ...)`)
  - Modificar: `src/harness/cli.py`, `tests/test_cli.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é registrar 5 novos subcomandos em
  > `src/harness/cli.py`, seguindo EXATAMENTE o padrão já usado pelos
  > subcomandos existentes (imports lazy dentro do `if args.command ==
  > ...`, `--dir` default `.`, saída JSON com `indent=2, ensure_ascii=False`,
  > `sys.exit` explícito). NÃO reordene nem refatore os subcomandos
  > existentes.
  >
  > 1. `team design --dir <alvo> --description \"<texto>\"`: chama
  >    `harness.teams.analyze_domain(dir)` +
  >    `harness.teams.recommend_pattern(domain, description)`; imprime JSON
  >    `{'pattern': ..., 'justification': ..., 'roles': [r.name for r in
  >    load_pattern(pattern).roles]}` (NÃO grava nenhum arquivo — é dry-run
  >    dos passos 1-2 do workflow); `sys.exit(0)` sempre que a análise
  >    rodar (erro só se `--description` faltar, tratado pelo próprio
  >    argparse).
  > 2. `team generate --dir <alvo> --pattern <nome> [--mode subagents|
  >    agent-teams] [--max-review-iterations N]` (`--mode` default
  >    `subagents`, `--max-review-iterations` default `3`): chama
  >    `harness.teams.generate_team(...)`; captura `harness.teams.TeamError`
  >    -> `erro: ...` em stderr, exit 1; sucesso imprime JSON com os campos
  >    de `TeamGenerationResult` (paths como `str`), exit 0.
  > 3. `review <feature_id> <decision>` onde `decision` é um subparser
  >    posicional restrito a `submit`/`approve`/`reject` (`choices=[...]` do
  >    argparse) + `--dir` + `--note` (default `''`) + `--justification`
  >    (default `None`): para `submit`, chama
  >    `harness.review.submit_for_review(dir, feature_id)`; para
  >    `approve`/`reject`, PRIMEIRO carregue a feature de
  >    `.harness/feature_list.json` (mesmo padrão de leitura de
  >    `harness.verify._load_feature`, mas leia direto aqui — não precisa
  >    importar função privada de outro módulo; se o arquivo/feature não
  >    existir, `erro: ...` + exit 1) e chame
  >    `harness.review.record_decision(dir, feature_id, feature,
  >    decision, note, justification)`. Capture `harness.review.ReviewError`
  >    -> `erro: ...` em stderr, exit 1. Sucesso imprime o registro de
  >    revisão atual (releia `.harness/review/<feature_id>.json` do disco
  >    depois da chamada) como JSON, exit 0.
  > 4. `supervise --dir <alvo>`: chama `harness.supervisor.dispatch_next(dir)`;
  >    imprime `{'next': <feature ou null>}`; sempre exit 0 (comando
  >    informativo, nunca falha por 'nada pronto').
  > 5. `audit-team --dir <alvo>`: chama `harness.team_audit.audit_team(dir)`;
  >    imprime `report.to_json()`; exit 0 se `score >= 60` senão exit 1
  >    (MESMO padrão de `audit`/`audit-runtime`).
  > 6. **(achado de reflect+judge: sem isso `supervisor.on_feature_verified`
  >    é código morto — nenhum caminho real chama)** No subcomando `verify`
  >    JÁ EXISTENTE (Fase 3, `run_verify`) — encontre o bloco `if args.command
  >    == 'verify':` e ACRESCENTE, logo depois de `run_verify` retornar com
  >    sucesso (evidência gravada, sem lançar `VerifyFailedError`), uma
  >    chamada a `harness.supervisor.on_feature_verified(Path(args.dir),
  >    args.feature_id)` (import lazy, mesmo padrão dos demais). Ignore o
  >    valor de retorno para a saída JSON já existente do comando `verify`
  >    (não mude o schema de saída dele) — é só um efeito colateral
  >    best-effort: se `on_feature_verified` devolver `None` (sem time
  >    compilado ou papéis incompletos), nada acontece; se devolver o dict de
  >    revisão, ótimo, mas NÃO precisa aparecer na saída do `verify` (quem
  >    quiser ver o estado da revisão roda `review <id> submit` ou lê
  >    `.harness/review/<id>.json` diretamente — este bloco só garante que a
  >    submissão automática ACONTECE, não que o comando `verify` vira uma
  >    API de revisão). NÃO deixe uma exceção de `on_feature_verified`
  >    quebrar o exit code do `verify` já existente — envolva a chamada em
  >    `try/except Exception` silencioso não é aceitável (mascara bug real);
  >    em vez disso, confie que `on_feature_verified` já devolve `None`
  >    defensivamente para os casos sem time compilado (SUBAGENTE 05) — se
  >    ela levantar algo em outro cenário, é bug real do SUBAGENTE 05 e deve
  >    propagar (não capture aqui).
  >
  > Acrescente a `tests/test_cli.py`: `team design` imprime pattern válido;
  > `team generate` com pattern válido grava os artefatos esperados
  > (verifique ao menos a existência de `.claude/agents/producer.md` e
  > `.harness/team/manifest.json` no `tmp_path` do teste) e exit 0; `team
  > generate` com pattern inexistente -> exit 1; `review <id> submit` exit
  > 0 e grava `.harness/review/<id>.json` com `status='in_review'`; `review
  > <id> approve` sem submit anterior -> exit 1 (transição inválida, mesmo
  > padrão de erro `ReviewError`); `supervise` sem contrato -> exit 0 com
  > `next: null`; `audit-team` sem time compilado -> exit 0 (score alto,
  > sem time é `info`, não `critical` — confirme isso lendo o SUBAGENTE 07
  > antes de escrever o teste); `verify <id>` com time compilado
  > (producer+reviewer, via `teams.generate_team` real no `tmp_path` do
  > teste) e comando de verify que passa -> depois do comando,
  > `.harness/review/<id>.json` existe com `status='in_review'` (prova que
  > `on_feature_verified` foi chamado de verdade pelo comando `verify`, não
  > só testado isoladamente no SUBAGENTE 05); `verify <id>` SEM time
  > compilado continua se comportando EXATAMENTE como os testes já
  > existentes do subcomando `verify` da Fase 3 (rode-os sem alterar, para
  > confirmar zero regressão). NÃO altere testes já existentes de outros
  > subcomandos."
- **🧪 Critério de Validação (DoD):**
  - [ ] `python -m pytest tests/test_cli.py -q`

---

### [SUBAGENTE 09] - Skill `/harness-creator:team`

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Criar `skills/team/SKILL.md`, análoga a
  `skills/plan/SKILL.md`: guia o humano por análise de domínio -> proposta
  de padrão com justificativa -> **aprovação da arquitetura do time (o
  único toque humano da Fase 4, uma vez por projeto)** -> geração dos
  artefatos -> validação (`harness audit-team`). **Depende do SUBAGENTE 08**
  (nomes/flags finais dos subcomandos `team design`/`team generate`/
  `audit-team`).
- **📂 Escopo de Arquivos:**
  - Ler: `skills/plan/SKILL.md` (molde de tom/estrutura/pré-requisito
    PYTHONPATH), `src/harness/cli.py` (assinatura final dos subcomandos do
    SUBAGENTE 08), `ROADMAP.md` linhas ~251-321 (workflow de 6 fases)
  - Modificar: `skills/team/SKILL.md` (novo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é criar `skills/team/SKILL.md`, seguindo o MESMO
  > formato de frontmatter e tom de `skills/plan/SKILL.md` (`name`,
  > `description`, `when_to_use`, `argument-hint`, `disable-model-invocation:
  > false`). Estruture os passos:
  >
  > Passo 1 — rode `python -m harness.cli team design --dir <alvo>
  > --description \"<descrição do domínio/demanda em linguagem natural>\"`
  > (mesmo aviso de PYTHONPATH de `skills/plan/SKILL.md`, copie literalmente
  > o mesmo parágrafo de pré-requisito). Passo 2 — apresente `pattern` +
  > `justification` + `roles` da saída ao usuário; se o usuário discordar da
  > recomendação, repita o Passo 1 citando o nome do padrão desejado
  > diretamente no Passo 3 abaixo (o comando `team generate` aceita
  > `--pattern` explícito, independente do que `team design` recomendou).
  > Passo 3 — **gate único desta skill, regra dura igual à de
  > `skills/plan/SKILL.md`:** apresente o padrão + papéis + `mode` (padrão
  > `subagents`) ao usuário e peça aprovação EXPLÍCITA da arquitetura do
  > time antes de gerar qualquer arquivo — nunca prossiga por inferência.
  > Passo 4 — só após aprovação explícita, rode `python -m harness.cli team
  > generate --dir <alvo> --pattern <nome> [--mode ...]`; mostre os
  > artefatos gerados (agentes/skills/`.harness/TEAM.md`/manifesto) ao
  > usuário. Passo 5 — rode `python -m harness.cli audit-team --dir <alvo>`
  > e mostre o score/findings; se `critical`, explique que é preciso
  > corrigir antes de considerar o time operacional (mesma postura de
  > `skills/audit/SKILL.md`, se existir — confira o arquivo antes de
  > escrever este passo para manter o tom consistente). Passo 6 — explique
  > o ciclo operacional dali em diante (nenhuma ação nova do humano): o
  > produtor implementa, `harness verify` grava evidência, `harness
  > supervise`/`harness review ... submit` aciona a revisão, o revisor
  > aprova/rejeita via `harness review ... approve|reject`, e só escala ao
  > humano se o limite de iterações estourar sem aprovação (cite
  > explicitamente que isso NUNCA força aprovação automática).
  >
  > Seção 'Regras' final (mesmo estilo de `skills/plan/SKILL.md`): nunca
  > gerar o time sem aprovação explícita da arquitetura; nunca inventar um
  > padrão fora do catálogo (`team design` só recomenda os 6 já existentes);
  > esta skill roda UMA VEZ por projeto (setup do time), diferente de
  > `/harness-creator:plan` que roda por demanda."
- **🧪 Critério de Validação (DoD):**
  - [ ] Arquivo `skills/team/SKILL.md` existe e tem frontmatter YAML válido: `python -c "import yaml,pathlib; t=pathlib.Path('skills/team/SKILL.md').read_text(encoding='utf-8'); fm=t.split('---')[1]; yaml.safe_load(fm); print('ok')"`

---

### [SUBAGENTE 10] - Gate de encerramento: dogfood E2E da Fase 4

> ✅ CONCLUÍDO

- **🎯 Objetivo:** Ampliar `tests/e2e/test_contract_dogfood.py` (NUNCA
  recomeçar do zero — já tem os gates das Fases 1/2/3 na mesma cobaia
  `MinimumAPI`) com o gate final da Fase 4: prova (a) zero regressão das
  Fases 1-3 na MESMA cobaia e (b) a novidade real da Fase 4 — o padrão
  Produtor-Revisor rodando com **REVISÃO INDEPENDENTE DE VERDADE**.
  **Redesenhado por reflect+judge** (achado crítico #1): a versão anterior
  deste bloco fazia a MESMA sessão `claude -p` rodar `review ... reject` e
  depois `review ... approve` consigo mesma, roteirizado — isso prova só a
  mecânica do state machine, não a capacidade central da fase (revisão
  **independente**). O desenho correto usa **MÚLTIPLAS sessões `claude -p`
  separadas**: uma (ou mais) para o produtor, outra(s) DISTINTA(S) para o
  revisor (contexto novo, sem memória da sessão do produtor, com
  `--disallowedTools Edit,Write` de verdade), cada uma tomando sua decisão
  a partir do que lê no disco (spec.md, diff, evidência), nunca por
  instrução roteirizada de "finja que rejeitou". A rejeição real do
  primeiro round tem que ser **mecanicamente fundamentada** (um critério
  objetivo de `spec.md` que o produtor genuinamente deixou incompleto na
  primeira tentativa — não uma opinião subjetiva de estilo, que seria
  no-determinístico demais para um DoD de CI). **Depende de TODOS os
  subagentes anteriores (01-09)** — é o gate final, roda por último. **Aviso
  de custo:** este bloco dispara ATÉ 5 sessões `claude -p` reais + múltiplos
  `dotnet build`/`test` reais — é o teste mais caro do repo até agora; isso
  é esperado e aceitável (gate de fechamento de fase, opt-in via
  `HARNESS_E2E_DOGFOOD=1`), não tente reduzir para 1 sessão só por custo —
  isso reintroduziria exatamente o problema que este redesenho corrige.
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/test_contract_dogfood.py` (inteiro — reaproveitar
    `SPEC_MD_TEMPLATE`/`PLANS_MD`/`HARNESS_YAML`/fixture `api_project`,
    padrão `_add_new_fact`/`_run_dotnet_test`/`_parse_trx`, e a função
    `test_contract_dogfood_verify_and_feature_lock` como referência mais
    próxima — ela já mostra o padrão de `permission_denials` + evidência
    real), `tests/e2e/conftest.py`, `src/harness/teams.py`,
    `src/harness/review.py`, `src/harness/boundary_guard.py`,
    `src/harness/supervisor.py` (o subcomando `verify` agora auto-submete
    para revisão via `on_feature_verified`, SUBAGENTE 08 — não é mais
    preciso rodar `review submit` manualmente depois de cada `verify`)
  - Modificar: `tests/e2e/test_contract_dogfood.py` (adicionar nova(s)
    função(ões) de teste — NUNCA editar as três funções de teste já
    existentes nem seus `EVIDENCE_PATH*`), `tests/e2e/evidence/fase4-dogfood-producer-reviewer.md`
    (novo, gerado pelo próprio teste — não escreva à mão, é o teste que
    grava)
- **🤖 Prompt para o Claude Code:**
  > "Claude, sua tarefa é adicionar em `tests/e2e/test_contract_dogfood.py`
  > uma nova função de teste (ex.
  > `test_contract_dogfood_producer_reviewer`), seguindo o MESMO padrão das
  > três já existentes (mesma fixture `api_project`, mesmo ciclo TDD real,
  > mesmo skip via `_require_toolchain`/`pytestmark`, própria trilha de
  > evidência em `EVIDENCE_DIR / 'fase4-dogfood-producer-reviewer.md'` —
  > NUNCA reaproveite os `EVIDENCE_PATH*` das fases anteriores).
  >
  > **Gap real de T-02, desenhado para produzir uma rejeição objetiva e
  > determinística no round 1 (não uma opinião subjetiva do revisor).**
  > Leia `MinimumAPI/Validators/CustomerValidators.cs` de verdade na cobaia
  > copiada (`api_project`) e confirme que existem DOIS validators que
  > compartilham uma regra de campo (tipicamente
  > `CreateCustomerRequestValidator` e `UpdateCustomerRequestValidator`
  > validando o mesmo campo, ex. `Email`/`Document`/`Phone` — escolha um
  > campo real, DIFERENTE do `Document` já corrigido por T-01). Escreva
  > `spec.md`/`Plans.md` para T-02 (slug `dogfood-producer-reviewer`)
  > exigindo EXPLICITAMENTE, em texto claro, que a regra nova seja aplicada
  > em AMBOS os validators (liste os dois arquivos/classes por nome no
  > `spec.md` como critério de aceitação) — este é o critério objetivo que
  > o revisor vai checar por leitura direta do arquivo, sem precisar de
  > julgamento subjetivo. Escreva DOIS `[Fact]` novos em
  > `MinimumAPI.Tests/CustomerValidatorTests.cs` (um por validator; ACRESCENTE,
  > não apague os existentes) e confirme TDD vermelho real para os dois
  > antes de qualquer correção. O `verify_cmd` de T-02 em `feature_list.json`
  > deve ser o MESMO `dotnet test MinimumAPI.Tests` de sempre (sem filtro
  > estreito — mantém o precedente do repo de rodar a suíte inteira).
  >
  > Fluxo do novo teste (múltiplas sessões `claude -p` reais, cada uma
  > `--output-format json`, timeout generoso — siga o padrão de timeout dos
  > testes existentes):
  >
  > 1. **`analyze` -> `spec.md`/`Plans.md` PRÉ-APROVADOS -> `compile-contract`
  >    -> `compile` -> `compile-session`** (feito pelo test harness Python,
  >    fora de qualquer sessão `claude`, mesmo padrão dos 3 testes
  >    anteriores). Rode também `python -m harness.cli team generate --dir
  >    <api_project> --pattern producer-reviewer --mode subagents` FORA do
  >    Claude (mesmo espírito de `compile-session` já ser chamado pelo test
  >    harness) e confirme que `.harness/team/manifest.json` e
  >    `.claude/agents/producer.md`/`.claude/agents/reviewer.md` existem
  >    antes de iniciar qualquer sessão headless. Confirme também (leitura
  >    de arquivo) que `reviewer.md` tem `tools:` sem `Edit`/`Write`.
  >
  > 2. **Sessão PRODUTOR #1** (`claude -p`, prompt baseado em
  >    `CLAUDE_PROMPT_VERIFY_LOCK` como referência de estilo): instrua o
  >    agente a implementar T-02 aplicando a regra SÓ no
  >    `CreateCustomerRequestValidator` (deliberadamente incompleto — a
  >    instrução do prompt é literal: 'aplique a regra nova apenas na
  >    validação de criação de cliente por enquanto), depois rodar `python
  >    -m harness.cli verify T-02 --dir .` (só o `[Fact]` de create passa;
  >    isso é aceitável para o `verify_cmd` gravar evidência — a suíte
  >    inteira roda mas o teste do update-path deve estar
  >    marcado/comentado/skip nesta primeira rodada, OU simplesmente ainda
  >    não escrito nesta sessão — decida qual mecanismo é mais simples de
  >    implementar corretamente e documente a escolha), e então tentar
  >    marcar `passes: true` para T-02 em `feature_list.json` (deve ser
  >    NEGADO — revisão ainda pendente/in_review, capture
  >    `permission_denials`). NÃO rode `review submit` manualmente — o
  >    subcomando `verify` já aciona `on_feature_verified` sozinho
  >    (SUBAGENTE 08); confirme isso lendo `.harness/review/T-02.json` após
  >    a sessão (`status == 'in_review'`, `iteration == 1`) SEM que a sessão
  >    tenha rodado `review submit` — é uma prova extra de zero regressão
  >    do SUBAGENTE 08.
  >
  > 3. **Sessão REVISOR #1** (`claude -p` SEPARADA — processo novo, sem
  >    contexto da sessão produtor; rode `claude -p --help` no ambiente de
  >    execução primeiro para confirmar o nome real da flag de restrição de
  >    ferramentas — a intenção, não o nome exato da flag, é o invariante;
  >    use `--disallowedTools Edit,Write` ou equivalente confirmado): prompt
  >    novo instruindo o agente a agir como o papel `reviewer` (cite o
  >    conteúdo de `.claude/agents/reviewer.md` no prompt), ler `spec.md` e
  >    o diff real de T-02 (`git diff`/leitura de arquivo via Bash — tools
  >    permitidas), e verificar OBJETIVAMENTE se AMBOS os validators citados
  >    em `spec.md` foram tocados; instrua explicitamente: 'se algum
  >    arquivo/validator que o spec.md cita como critério de aceitação não
  >    foi alterado, rejeite com `python -m harness.cli review T-02 reject
  >    --dir . --note \"<explique especificamente qual arquivo/validator
  >    ficou faltando>\"` — não aprove um critério que você não confirmou
  >    lendo o arquivo real'. Depois da sessão, confirme: `is_error is
  >    False`; `.harness/review/T-02.json` tem `status == 'rejected'`,
  >    `iteration == 1`; a `note` da entrada mais recente de `history`
  >    contém (case-insensitive) o nome do validator/arquivo que ficou
  >    faltando (prova de que a rejeição é fundamentada em leitura real, não
  >    um texto genérico); a sessão revisora NÃO editou nenhum arquivo de
  >    produção (compare hash/conteúdo de `CustomerValidators.cs` antes/
  >    depois da sessão revisora — deve ser idêntico) e/ou `permission_denials`
  >    da sessão revisora mostra alguma tentativa de `Edit`/`Write` negada
  >    (se ela tentou); se a sessão terminar sem rejeitar (aprovou ou não
  >    decidiu), o teste FALHA aqui — não mascare com retry silencioso, é
  >    sinal de spec.md/prompt ambíguo demais e precisa de ajuste no
  >    prompt, não de um segundo round de tentativa automática.
  >
  > 4. **Sessão PRODUTOR #2**: aplica a MESMA regra também no
  >    `UpdateCustomerRequestValidator` (o gap real que o revisor apontou),
  >    roda `python -m harness.cli verify T-02 --dir .` de novo (agora os
  >    DOIS `[Fact]` passam, evidência nova gravada, `on_feature_verified`
  >    auto-resubmete: `status == 'in_review'`, `iteration == 2` — confirme
  >    lendo o arquivo, de novo sem a sessão rodar `review submit`
  >    manualmente).
  >
  > 5. **Sessão REVISOR #2** (processo `claude -p` NOVO, distinto da sessão
  >    revisora #1 — não reaproveite contexto, mesmo precedente de
  >    'subagente frio' já usado no resto do projeto para blocos de
  >    execução): mesmo prompt-base da Sessão REVISOR #1, lendo o diff
  >    atualizado; confirma que AMBOS os validators agora têm a regra e
  >    aprova: `python -m harness.cli review T-02 approve --dir . --note
  >    \"<confirmação concreta, citando os dois validators>\"`. Depois:
  >    `is_error is False`; `.harness/review/T-02.json` final com `status
  >    == 'approved'`, `iteration == 2` (prova de pelo menos um ciclo
  >    rejeitado->corrigido->aprovado, nunca aprovação de primeira
  >    tentativa).
  >
  > 6. **Sessão PRODUTOR #3** (curta): tenta marcar `passes: true` para T-02
  >    de novo — agora deve ser ACEITO (evidência fresca + revisão aprovada
  >    fresca). Confirme por leitura direta de `feature_list.json` E prova
  >    temporal por mtime (`feature_list.json` mtime >= `.harness/review/T-02.json`
  >    mtime >= mtime da evidência mais recente — mesmo padrão de
  >    comparação de mtime já usado por
  >    `test_contract_dogfood_verify_and_feature_lock`).
  >
  > Ao final, reaproveite os asserts de zero regressão: `dotnet test` real
  > (via `_run_dotnet_test`/`_parse_trx` já existentes) depois de tudo,
  > TODOS os `_PRE_EXISTING_TESTS` + o teste de T-01 das fases anteriores +
  > os dois novos `[Fact]` de T-02, todos `Passed`. Grave a evidência em
  > markdown (comandos executados, resultado da suíte antes/depois de cada
  > correção, diff do(s) arquivo(s) de produção tocado(s), resumo
  > `is_error`/`permission_denials`/`num_turns` de CADA uma das 5 sessões, e
  > o histórico completo de `.harness/review/T-02.json`) em
  > `tests/e2e/evidence/fase4-dogfood-producer-reviewer.md`. NÃO edite
  > nenhuma das três funções de teste já existentes no arquivo."
- **🧪 Critério de Validação (DoD):**
  - [ ] `HARNESS_E2E_DOGFOOD=1 python -m pytest tests/e2e/test_contract_dogfood.py -q` (exige `claude`+`dotnet` no PATH; os 4 testes do arquivo — 3 antigos + 1 novo — precisam passar)
  - [ ] `python -m pytest tests/ -q -k "not dogfood"` (suíte completa restante segue verde — zero regressão fora do dogfood opt-in)

---

## Mapa de dependências

- **Onda A (paralelo — arquivos disjuntos, sem dependência mútua):**
  - [SUBAGENTE 01] Catálogo de padrões + motor de análise/seleção — `src/harness/teams.py` (novo), `teams/patterns/*.yaml` (6 novos), `tests/test_teams.py` (novo)
  - [SUBAGENTE 02] Produtor-Revisor: state machine de revisão — `src/harness/review.py` (novo), `tests/test_review.py` (novo)
- **Onda B (paralelo entre si; cada um depende só da sua peça da Onda A):**
  - [SUBAGENTE 03] Geração de agentes e skills do time — depende de 01 — `src/harness/teams.py`, `tests/test_teams.py`
  - [SUBAGENTE 04] Enforcement do veto do revisor — depende de 02 — `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
  - [SUBAGENTE 05] Supervisor: despacho dinâmico — depende de 02 — `src/harness/supervisor.py` (novo), `tests/test_supervisor.py` (novo)
- **Onda C (paralelo entre si; cada um depende de peças já fechadas da Onda B):**
  - [SUBAGENTE 06] Integração e orquestração (`generate_team`) — depende de 01, 03, 05 — `src/harness/teams.py`, `tests/test_teams.py`
  - [SUBAGENTE 07] Audit de time — depende de 01, 03 — `src/harness/team_audit.py` (novo), `tests/test_team_audit.py` (novo)
- **Onda D (sequencial — único dono de `cli.py` nesta fase):**
  - [SUBAGENTE 08] CLI (`team design/generate`, `review`, `supervise`, `audit-team`) — depende de 02, 05, 06, 07 — `src/harness/cli.py`, `tests/test_cli.py`
- **Onda E:**
  - [SUBAGENTE 09] Skill `/harness-creator:team` — depende de 08 — `skills/team/SKILL.md` (novo)
- **Onda F (gate final — depende de TODOS: 01-09):**
  - [SUBAGENTE 10] Dogfood E2E da Fase 4 — `tests/e2e/test_contract_dogfood.py`

Ordem de execução recomendada: `{01, 02}` em paralelo → `{03, 04, 05}` em
paralelo → `{06, 07}` em paralelo → `08` → `09` → `10`.
