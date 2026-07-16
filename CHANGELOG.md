# Changelog

## 0.13.0 — 2026-07-16

Fase 3 do roadmap (Auto-verificação e Correção em Loop): *"confidence ≠
correctness"* — o agente roda a própria suíte, conserta as próprias falhas e
só declara vitória com prova executável. Backlog revisado por plan-critic +
judge antes da execução.

### Adicionado
- `src/harness/verify.py` — `harness verify <feature-id>`: roda o
  `verify_cmd` da tarefa (vindo do contrato, validado contra o profile);
  sucesso grava `.harness/evidence/<id>.json` (timestamp, comando, hash). É o
  passo 11 do lifecycle ("registra a prova").
- `src/harness/contract.py` — `get_stop_conditions`: expõe as stop conditions
  do `spec.md` como disjuntor do loop de autocorreção (passos 9–10): N falhas
  consecutivas da mesma suíte ou sinal de impossibilidade → o agente para,
  registra o estado no `claude-progress.md` e devolve ao humano com
  diagnóstico.
- `src/harness/boundary_guard.py` — feature-lock: `passes: true` no
  `feature_list.json` só com evidência fresca (`evidence/<id>.json` mais novo
  que o último commit). Edição que marca feature concluída sem evidência
  válida → `deny` com razão ("rode harness verify primeiro"). Mata a
  manipulação de lista de tarefas sem nenhum prompt humano.
- `src/harness/stop_hook.py` — hook `Stop`: feature `in_progress` com
  verificação nunca rodada ou falhando → o encerramento devolve a razão ao
  agente (continua o ciclo ou executa o ritual de handoff dos passos 12–16).
  Redireciona o agente, não interrompe o humano.
- `src/harness/runtime_audit.py` — segunda máquina de audit, distinta do diff
  byte-exato do [audit.py](src/harness/audit.py): audita os artefatos
  runtime-mutáveis (`claude-progress.md`, `feature_list.json`, `evidence/`)
  por schema + frescor + invariantes (1 feature `in_progress`; todo
  `passes:true` com evidência válida).
- `harness verify <feature-id>` e `harness audit-runtime` na CLI.

## 0.12.0 — 2026-07-16

Fase 2 do roadmap (Execução Autônoma no Raio de Impacto): dentro do contrato
já aprovado (Fase 1), o agente passa a trabalhar sem interromper o humano —
o microgerenciamento por `ask`/`deny` por ação dá lugar a uma superfície de
`allow` enumerada e compilada do próprio contrato.

### Adicionado
- `src/harness/session_permissions.py` — compila `.harness/feature_list.json`
  + `.harness/repo-profile.json` para `allow` ENUMERADO (nunca genérico) em
  `.claude/settings.json`: `Edit`/`Write` nos `files[]` de todas as tarefas,
  `Bash` dos `verify_cmd` e extras de lint/build do profile, e o comando de
  instalação de dependências derivado do `package_manager` detectado (ex.:
  `npm ci`) — a instalação roda na aprovação do contrato, não no meio da
  sessão. Git local do ritual (`status/log/diff/add/commit`) fixo. Estado
  gerenciado em `.harness/compiled-state-session.json`, chave
  `managed_session_permissions`.
- `src/harness/boundary_guard.py` — dispatcher único de hook `PreToolUse`
  cobrindo `Edit`/`Write`/`Bash` numa passada só (resolve a latência de N
  subprocessos por tool call do design anterior). Duas garantias, nesta
  ordem, sempre: (1) **runtime floor** avaliado incondicionalmente antes de
  qualquer outra checagem — `git push`, rede/publicação não planejada
  (`curl`, `wget`, `npm publish`, `pip upload`, `twine upload`, `gh
  release`) e escrita em arquivo de segredo (`.env`, `.pem`, `id_rsa`,
  `*credentials*`) nunca viram `allow`, com ou sem contrato ativo; (2)
  **proteção contra enfraquecimento de teste** — arquivo que casa
  `test_glob` só é editável se alguma tarefa do contrato ativo o declarar em
  `files[]`. Remove o hook legado `guard_tests.py` (sempre-`ask` estático)
  quando presente, substituindo-o pela decisão por-tarefa.
- `src/harness/lifecycle.py` — compila o Agent Session Lifecycle de 16
  passos como bloco gerenciado adicional no `AGENTS.md` (progressive
  disclosure, detalhe em `.harness/LIFECYCLE.md`). **[Design próprio]**:
  diverge deliberadamente do texto literal do ROADMAP.md, que descrevia a
  entrega como seções `state`/`lifecycle` no `harness.yaml`; implementado em
  vez disso via bloco em `AGENTS.md` + arquivo de detalhe, sem estender o
  schema do yaml, por ser essencialmente texto/instrução e não configuração.
- `src/harness/templates.py` — gera `claude-progress.md` (esqueleto runtime,
  só se ainda não existir — recompilar nunca sobrescreve progresso já
  registrado) e `init.sh`/`init.ps1` (determinísticos a partir do
  `repo-profile.json`, sempre regenerados).
- `src/harness/session_start.py` — hook `SessionStart` (schema
  `hookSpecificOutput.additionalContext`, confirmado contra a documentação
  oficial, distinto do schema de `PreToolUse`) que injeta no início da
  sessão o resumo do progresso, a feature ativa/pendente e o `git log`
  recente.
- `harness compile-session --dir` na CLI — orquestra os cinco módulos acima
  numa única compilação da sessão de trabalho autônoma.

### Corrigido (achados da revisão plan-critic + judge)
- Bypass do runtime floor sem contrato ativo: uma primeira versão do
  `boundary_guard.py` só aplicava o runtime floor depois de confirmar que
  havia contrato ativo, o que liberaria `git push`/segredos por omissão em
  qualquer repo sem `feature_list.json`. Corrigido — o runtime floor agora
  roda incondicionalmente, antes de qualquer checagem de contrato.
- Colisão de estado com o mecanismo antigo: os novos hooks de sessão
  (`session_permissions.py`, `boundary_guard.py`, `session_start.py`)
  gravavam risco de colidir com `.harness/compiled-state.json`, que
  `compiler.py::_write_state` reconstrói do zero a cada `harness compile` —
  uma chave nova ali seria apagada silenciosamente na próxima compilação do
  mecanismo antigo. Resolvido com arquivo próprio,
  `.harness/compiled-state-session.json`, compartilhado só entre os três
  hooks de sessão, cada um sob sua própria chave.

## 0.11.0 — 2026-07-15

Fase 1 do roadmap (Delegação Baseada em Contratos): move a autoridade humana
de aprovar cada ação para aprovar um único contrato por demanda, antes de
qualquer código.

### Adicionado
- `src/harness/analyzer.py` — análise determinística do repo-alvo (stack,
  comando de teste, lint/build, CI, convenções). Cada achado grava
  `evidence`; o que não foi observado entra em `unknowns[]` — o contrato só
  pode referenciar fatos com evidência.
- `.harness/repo-profile.json` — saída persistida do analyzer, consumida
  pela skill `plan`.
- `src/harness/contract.py` — parseia `spec.md` + `Plans.md` e compila para
  `.harness/feature_list.json` (`{id, desc, files[], verify_cmd, passes}`
  por tarefa). Gate de aprovação: exige `approved_by`/`approved_at`
  preenchidos no frontmatter do `spec.md`; sem isso, `ContractNotApprovedError`.
- `harness analyze --dir` e `harness compile-contract --dir --slug` na CLI.
- Skill `/harness-creator:plan` — entrevista a demanda, apresenta o profile e
  os `unknowns`, escreve o contrato (`spec.md`/`Plans.md`) em
  `.harness/work/<slug>/` e só compila depois da aprovação humana explícita
  (a skill nunca preenche `approved_by`/`approved_at` por conta própria).
- `tests/e2e/test_contract_flow.py` — E2E do fluxo completo
  analyze → spec/Plans → gate de aprovação → compile-contract.
- `tests/e2e/test_contract_dogfood.py` — gate de encerramento da fase: contrato
  aprovado + `claude -p` real implementando uma melhoria genuína na cobaia
  `MinimumAPI` (validação de `Document` só por dígitos), provada por
  `dotnet test` real antes/depois; evidência em
  `tests/e2e/evidence/fase1-dogfood-document-digits.md`.
- `tests/e2e/test_fase1_outcomes.py` — suíte de verificação independente dos
  6 outcomes prometidos pela Fase 1, com evidência acumulada em
  `tests/e2e/evidence/fase1-outcomes-verification.md`.

### Corrigido
- Arnês de verificação independente (`test_fase1_outcomes.py`): o teste do
  fluxo headless da skill `plan` não compilava baseline de permissões
  (`approval_policy: auto`) antes de invocar `claude -p`, então o headless
  negava toda ação `ask` e os outcomes "skill usa o profile"/"skill nunca se
  auto-aprova" ficavam sem veredito; e a fixture de evidência sobrescrevia o
  `.md` inteiro a cada processo pytest separado, apagando vereditos de rodadas
  anteriores. Ambos corrigidos — evidência agora mescla entre execuções e o
  teste headless compila o baseline antes de rodar.

## 0.10.0 — 2026-07-15

Pivot: de executor agêntico próprio para **plugin do Claude Code** que cria,
avalia e compila governança de harness — sem executar tarefas, sem
`ANTHROPIC_API_KEY`.

### Adicionado
- `src/harness/compiler.py` — `.harness/harness.yaml` → `.claude/settings.json`
  (permissions + hooks PreToolUse) + `AGENTS.md` (bloco gerenciado). Reusa
  `_POLICY_MATRIX`/`_ALWAYS_GATED` e `_glob_to_regex` da biblioteca existente.
- `src/harness/audit.py` — score 0-100 + findings via dogfooding (recompila
  em memória e compara com o disco).
- `harness compile --dir` / `harness audit --dir` na CLI.
- Plugin (`.claude-plugin/plugin.json`) com 3 skills:
  `/harness-creator:init|audit|compile`.
- Merge não-destrutivo do `settings.json` (preserva regras/hooks manuais do
  usuário; estado gerenciado em `.harness/compiled-state.json`).
- Suíte de testes em 3 camadas: 77 unit + 8 E2E (cópia real de API .NET via
  subprocess) + 2 headless reais (`claude -p`, opt-in).
- `scripts/make_playground.py` — gera playground reprodutível pra teste
  manual contra API real.

### Corrigido
- `guard_test_runner.py` sobre-bloqueava `test_command` de 2+ palavras (ex.:
  `dotnet test` marcava `dotnet build` também) — trocado por matching de
  sequência consecutiva de tokens.
- `audit.py` só procurava arquivo de teste `.py` (hardcoded) — agora varre
  qualquer extensão respeitando `test_glob`.

### Descoberto e documentado
- `claude -p` (headless) nunca trava numa ação `ask` — nega automaticamente
  e a sessão termina normal (exit 0). O sinal de bloqueio pra scripts é o
  campo `permission_denials` do `--output-format json`, não o exit code.
- Razão específica do hook de TDD não aparece na UI de aprovação do Claude
  Code — visualmente idêntica a um `ask` genérico (achado de UX, não bug).
- Regra `ask` sempre vence `allow` por precedência de bucket, independente
  de especificidade — não dá pra abrir exceção pontual pras próprias skills
  sem afrouxar o gate geral de `Bash`.

### Congelado (referência, fora do produto atual)
- Orquestrador próprio (`orchestrator.py`) + sandbox Docker + TDD loop — a
  versão anterior deste projeto, um executor agêntico completo de 6 camadas.
  Segue no repo, testado, mas fora do caminho principal.

## 0.1.0

Versão inicial: arcabouço de execução agêntica com orquestrador próprio,
sandbox Docker, aprovação HITL, roteamento de modelo e telemetria.
