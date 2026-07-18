# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Correção do arnês de verificação da Fase 1 — outcomes 2/3 sem veredito + evidência clobrada
# Origem: ROADMAP-fase1.outcomes-report.md (seções 4, 5 e 7). Gerado 2026-07-15.
# Alvo único de código: tests/e2e/test_fase1_outcomes.py (os DOIS bugs são do teste novo,
# não da implementação da Fase 1 — nenhum arquivo de src/ ou skills/ é tocado aqui).
#
# Validação global ao fechar: os 6 outcomes da Fase 1 com veredito REAL (ATINGIDO ou
# NÃO ATINGIDO — nunca "NÃO EXECUTADO") em tests/e2e/evidence/fase1-outcomes-verification.md,
# e `$env:PYTHONPATH = "src"; python -m pytest tests -q` verde sem apagar esses vereditos.
# [SUBAGENTE 03] é opt-in de verdade (HARNESS_E2E_HEADLESS=1, custa tokens reais, exige
# `claude` autenticada no PATH e a cobaia .NET externa em disco).
#
# Decisão de arquitetura registrada (Bug 2): entre as duas alternativas do relatório —
# (a) _evidence_writer ler+mesclar o .md existente vs (b) rodar tudo num único processo
# pytest sempre com HARNESS_E2E_HEADLESS=1 — fica a (a) MERGE. Justificativa: a opção (b)
# é convenção operacional, não código — o gate padrão do repo (`pytest tests -q`, SEM a
# env var, usado como validação global no ROADMAP-fase1.backlog.md) roda só a bateria
# barata e voltaria a clobrar os vereditos 2/3 a cada execução; bastaria um dev rodar a
# suíte pra destruir evidência cara (tokens reais). O merge torna o writer idempotente e
# robusto a QUALQUER padrão de invocação (bateria barata só, cara só, as duas em qualquer
# ordem, suíte inteira), sem depender de disciplina humana.
#
# 🗺️ Mapa de Dependências dos Subagentes (estritamente sequencial — 01 e 02 editam o
# MESMO arquivo, e 03 só faz sentido com os dois corrigidos):
#   - 🟢 Fase 1: [SUBAGENTE 01] — Bug 2: merge do writer de evidência (barato, validável sem tokens)
#   - 🟡 Fase 2: [SUBAGENTE 02] (depende de 01) — Bug 1: baseline de permissões antes do claude -p
#   - 🏁 Fase 3: [SUBAGENTE 03] (depende de 01 e 02) — RE-EXECUÇÃO real das duas baterias + veredito dos 6 outcomes

### [SUBAGENTE 01] - Bug 2: `_evidence_writer` lê e mescla o .md existente em vez de sobrescrever
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Tornar `tests/e2e/evidence/fase1-outcomes-verification.md` confiável como fonte única: cada rodada de pytest grava só as seções dos outcomes que ELA executou, preservando os vereditos reais gravados por rodadas anteriores (hoje a segunda rodada apaga a primeira — relatório, seção 5).
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/test_fase1_outcomes.py` (fixture `_evidence_writer`, dict `_SECTIONS`, `_OUTCOME_TITLES` — linhas ~113-160), `ROADMAP-fase1.outcomes-report.md` (seção 5, descrição do clobber)
  - Modificar: `tests/e2e/test_fase1_outcomes.py` (SOMENTE a fixture `_evidence_writer` e, se necessário, um helper privado de parse; docstring do módulo atualizada)
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `tests/e2e/test_fase1_outcomes.py`, corrija a fixture module-scoped `_evidence_writer` para MESCLAR com o arquivo existente em vez de sobrescrever. Contexto: os testes do módulo rodam em dois processos pytest separados (bateria barata sem `HARNESS_E2E_HEADLESS`, bateria cara com a env var), o estado `_SECTIONS` vive em memória de processo, e hoje a segunda rodada regrava `tests/e2e/evidence/fase1-outcomes-verification.md` inteiro marcando como 'NÃO EXECUTADO' outcomes que passaram na rodada anterior. Comportamento novo: (1) mantenha o guard existente — se `_SECTIONS` estiver vazio (run 100% skipado), não escreva nada; (2) antes de escrever, se `EVIDENCE_PATH` existir, parseie as seções existentes com um helper privado (ex.: `_parse_existing_sections(text) -> dict[int, str]`) usando split por regex no cabeçalho `^## Outcome (\\d) — ` (re.MULTILINE) — o corpo de cada seção é o texto até o próximo cabeçalho `## Outcome` ou EOF; (3) para cada outcome 1..6: se está em `_SECTIONS`, escreva a seção nova (mesmo formato atual: 'Veredito: **ATINGIDO/NÃO ATINGIDO**' + prova) e acrescente uma linha `_Atualizado em <iso-utc> por esta rodada._` ao fim da seção; se NÃO está em `_SECTIONS` mas existe no arquivo antigo com veredito real, PRESERVE o corpo antigo byte a byte; se não está em lugar nenhum (ou o corpo antigo era 'NÃO EXECUTADO'), escreva o placeholder 'NÃO EXECUTADO' atual; (4) o cabeçalho do arquivo ('# Evidência — ...' + linha 'Gerado em ...') pode ser regravado a cada rodada — a informação por-rodada fica no `_Atualizado em ..._` de cada seção. Não mude `_record`, `_SECTIONS`, `_OUTCOME_TITLES` nem nenhum teste. Atualize o parágrafo final do docstring do módulo (o que descreve a evidência) explicando a semântica de merge entre processos. Nenhuma mudança fora da fixture, do helper novo e do docstring."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -m ruff check tests/e2e/test_fase1_outcomes.py` — limpo
  - [x] Prova real de merge SEM tokens (semeia veredito falso no outcome 2, roda a bateria barata — que só grava 1/4/5/6 — e confirma que a semente sobreviveu): `Set-Content -Encoding utf8 tests/e2e/evidence/fase1-outcomes-verification.md "# Evidência — Fase 1: verificação dos 6 outcomes`n`n## Outcome 2 — skill plan usa o profile como fonte de fatos (não reentrevista do zero)`n`nVeredito: **ATINGIDO**`n`nSEED-MERGE-CHECK`n"; $env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -q; Select-String -Path tests/e2e/evidence/fase1-outcomes-verification.md -Pattern "SEED-MERGE-CHECK"` — o pytest sai 4 passed/1 skipped e o Select-String retorna 1 match (a rodada barata NÃO apagou o veredito pré-existente do outcome 2)
  - [x] Na mesma execução acima, os outcomes da rodada barata foram regravados de verdade: `(Select-String -Path tests/e2e/evidence/fase1-outcomes-verification.md -Pattern "Veredito: \*\*ATINGIDO\*\*").Count` retorna 5 (outcomes 1/4/5/6 reais + a semente do 2)
  - [x] Idempotência: rodar `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -q` uma SEGUNDA vez mantém o resultado do check anterior inalterado (mesmos 5 ATINGIDO, semente ainda presente)
  - [ ] Nota ao encerrar: o conteúdo semeado é descartável — o [SUBAGENTE 03] regrava o arquivo com os vereditos reais; NÃO commitar o estado semeado.

---

### [SUBAGENTE 02] - Bug 1: compilar baseline de permissões (`approval_policy: auto`) antes do `claude -p`
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Fazer `test_outcomes2_3_plan_skill_uses_profile_and_never_self_approves` compilar `.harness/harness.yaml` + `.claude/settings.json` na cobaia ANTES de invocar `claude -p`, seguindo o padrão de `test_contract_dogfood.py` — sem isso o headless nega todo `ask` (Bash/Write) e a skill nem consegue rodar `harness analyze` ou escrever `spec.md` (relatório, seção 4, outcomes 2/3).
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/test_contract_dogfood.py` (constante `HARNESS_YAML` com `approval_policy: auto` + `enforce_tdd: false` e o comentário das linhas ~91-99 explicando por quê; passo 5 do teste), `tests/e2e/test_headless.py` (achado documentado: headless nega `ask` e segue até o fim, sinal real em `permission_denials`), `src/harness/compiler.py` (`render`: `auto` -> `_POLICY_MATRIX["auto"] = set()`, então só `network`/`edit_test` ficam gateados; Bash/Edit/Write entram em `allow` no settings.json; `enforce_tdd: true` geraria `guard_test_runner.py` que responde `ask` a qualquer invocação do test_command — veneno em headless), `src/harness/cli.py` (subcomando `compile`), `skills/plan/SKILL.md` (Passo 5: o gate de auto-aprovação é regra SEMÂNTICA da skill, não permissão de ferramenta)
  - Modificar: `tests/e2e/test_fase1_outcomes.py` (SOMENTE o teste `test_outcomes2_3_...` e o docstring do módulo)
- **🤖 Prompt para o Claude Code:**
  > "Claude, em `tests/e2e/test_fase1_outcomes.py`, corrija o setup de `test_outcomes2_3_plan_skill_uses_profile_and_never_self_approves`. Entre o `analyze` pré-gerado e o `subprocess.run(['claude', ...])`, adicione:
  > (1) escrever `<api_project>/.harness/harness.yaml` com uma constante de módulo nova (ex.: `HARNESS_YAML_AUTO`), conteúdo EXATO no padrão de `test_contract_dogfood.py`:
  > ```yaml
  > governance:
  >   approval_policy: auto
  > verification:
  >   enforce_tdd: false
  >   test_command: "dotnet test Cobaia.Tests"
  >   test_glob: "Cobaia.Tests/**/*.cs"
  > ```
  > com um comentário Python explicando: `enforce_tdd: false` porque o hook `guard_test_runner` gerado com `true` responde `ask` a qualquer invocação do test_command e headless nega todo `ask` (achado de `test_headless.py`); `approval_policy: auto` libera Bash/Write/Edit no settings.json compilado — mas `edit_test` e `network` continuam SEMPRE gateados (`_ALWAYS_GATED` em `governance/approval.py`), o que não atrapalha: a skill plan só escreve sob `.harness/work/`, fora do `test_glob`.
  > (2) compilar via subprocess da CLI real, mantendo a disciplina do módulo (nunca import in-process — diferente do dogfood, que importa `compile_project`): `compile_proc = _run_cli(['compile', '--dir', str(api_project)], cwd=api_project)` + `assert compile_proc.returncode == 0, compile_proc.stderr` + assert de que `<api_project>/.claude/settings.json` existe. Registre em `proof2` que o baseline foi compilado (política `auto`, caminho do settings).
  > (3) DEIXE EXPLÍCITO EM COMENTÁRIO no corpo do teste, antes dos asserts do outcome 3: `approval_policy: auto` libera PERMISSÕES DE FERRAMENTA, não a aprovação do CONTRATO — a regra 'nunca auto-aprovar' é semântica da skill (Passo 5 de skills/plan/SKILL.md). Com `auto`, este teste fica MAIS forte: a skill tem permissão de ferramenta para preencher `approved_by`/`approved_at` e ainda assim é obrigada a deixá-los vazios. Mantenha intactos os asserts existentes: frontmatter com `approved_by`/`approved_at` vazios, `feature_list.json` ausente, `compile-contract` -> exit 1 com 'não aprovado'.
  > (4) FECHE O CICLO com a confirmação humana explícita SIMULADA (novo, ao fim do outcome 3): depois do gate recusar, simule o humano aprovando o spec QUE A SKILL ESCREVEU — não use `_approve_spec` (ele assume linhas adjacentes literais do template do módulo); em vez disso, reescreva por regex com `re.MULTILINE` sobre o texto do `spec_path`: `^approved_by:.*$` -> `approved_by: humano-e2e-fase1` e `^approved_at:.*$` -> `approved_at: <iso utc agora>`. Então rode `compile-contract --slug <slug>` de novo e assert exit 0 + `feature_list.json` existente. Isso prova a formulação completa do outcome 3: os campos ficam vazios ATÉ a confirmação humana explícita, e a aprovação humana era o ÚNICO ingrediente que faltava. Registre em `proof3`.
  > (5) atualize o docstring do módulo (item 2/3 da lista e o parágrafo de env vars) mencionando que o teste compila baseline `approval_policy: auto` antes do headless, citando `test_contract_dogfood.py` como precedente.
  > Não mude a fixture `_evidence_writer` (corrigida pela tarefa anterior), os outros testes, nem nenhum arquivo de `src/` ou `skills/`. Não rode `claude -p` de verdade nesta tarefa — a execução real é a tarefa seguinte."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -m ruff check tests/e2e/test_fase1_outcomes.py` — limpo
  - [x] Coleta íntegra sem executar nada caro: `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py --collect-only -q` — 5 testes coletados, zero erros
  - [x] Bateria barata continua verde e o teste caro continua skipado por padrão: `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -q` — 4 passed, 1 skipped
  - [x] Grep determinístico do setup novo: `Select-String -Path tests/e2e/test_fase1_outcomes.py -Pattern "approval_policy: auto"` e `Select-String -Path tests/e2e/test_fase1_outcomes.py -Pattern "'compile', '--dir'|\"compile\", \"--dir\""` retornam match
  - [x] Grep do ciclo fechado: `Select-String -Path tests/e2e/test_fase1_outcomes.py -Pattern "humano-e2e-fase1"` retorna match (aprovação humana simulada presente)

---

### [SUBAGENTE 03] - RE-EXECUÇÃO real: as duas baterias + veredito dos 6 outcomes
> ✅ CONCLUÍDO — 6/6 outcomes ATINGIDO, prova real, evidência em tests/e2e/evidence/fase1-outcomes-verification.md
> ⚠️ Opt-in e caro: invoca o binário `claude` REAL em modo headless (tokens reais, exige CLI
> autenticada no PATH) e a cobaia `.NET externa` em disco. O objetivo é PROVA, não
> PASS forçado: se o teste dos outcomes 2/3 falhar com o setup corrigido, o veredito
> "NÃO ATINGIDO" com a prova registrada é um resultado VÁLIDO desta tarefa — reporte-o ao
> humano em vez de mexer na skill ou afrouxar asserts.
- **🎯 Objetivo:** Rodar de verdade `tests/e2e/test_fase1_outcomes.py` completo (bateria barata + bateria cara) com as correções dos SUBAGENTES 01 e 02, e sair com `tests/e2e/evidence/fase1-outcomes-verification.md` mostrando veredito real (ATINGIDO ou NÃO ATINGIDO, nunca "NÃO EXECUTADO") para os 6 outcomes — fechando a lacuna apontada nas seções 4, 5 e 7 do relatório.
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/test_fase1_outcomes.py` (estado final pós 01+02), `ROADMAP-fase1.outcomes-report.md` (o que cada outcome exige como prova)
  - Modificar: NENHUM arquivo de código. Únicos efeitos em disco permitidos: `tests/e2e/evidence/fase1-outcomes-verification.md` (regravado pelos próprios testes) e artefatos temporários de pytest em tmp.
- **🤖 Prompt para o Claude Code:**
  > "Claude, execute a verificação final dos 6 outcomes da Fase 1. Pré-checagens: `shutil.which('claude')` não pode ser None (senão pare e reporte 'claude CLI ausente — tarefa bloqueada'); `Test-Path <caminho da cobaia .NET>` deve ser True. Depois rode, NESTA ordem, cada comando num shell limpo:
  > 1. Bateria barata (grava vereditos reais de 1/4/5/6 por cima de qualquer estado semeado): `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -q` — espere 4 passed, 1 skipped.
  > 2. Bateria cara (outcomes 2/3, claude real, pode levar alguns minutos): `$env:HARNESS_E2E_HEADLESS = "1"; $env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -k outcomes2_3 -v -s` — capture a saída completa. Se falhar, NÃO conserte código: o writer de evidência (corrigido) já registrou o veredito NÃO ATINGIDO com a prova; leia o assert e a evidência, e registre a causa no seu relato.
  > 3. Prova anti-clobber em condições reais (o gate padrão do repo NÃO pode apagar os vereditos caros — é exatamente o cenário do Bug 2): num shell SEM `HARNESS_E2E_HEADLESS` (confirme com `Test-Path Env:HARNESS_E2E_HEADLESS` retornando False, ou remova com `Remove-Item Env:HARNESS_E2E_HEADLESS -ErrorAction SilentlyContinue`), rode `$env:PYTHONPATH = "src"; python -m pytest tests -q` — suíte inteira verde (E2E opt-in skipados) E, depois dela, os vereditos dos outcomes 2/3 continuam no arquivo de evidência.
  > 4. Integridade do original: `git -C <caminho da cobaia .NET> status --short` — saída vazia.
  > Ao final, relate a tabela dos 6 outcomes (número, título, veredito, uma linha de prova) lida do arquivo de evidência. NUNCA rode a suíte inteira com `HARNESS_E2E_HEADLESS=1` setado — isso dispararia também `tests/e2e/test_headless.py` (2 sessões claude extras, tokens desnecessários)."
- **🧪 Critério de Validação (DoD):**
  - [x] Passo 1: `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -q` — `4 passed, 1 skipped`
  - [x] Passo 2 executou de verdade (passou OU falhou com prova — ambos fecham a tarefa): `$env:HARNESS_E2E_HEADLESS = "1"; $env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_fase1_outcomes.py -k outcomes2_3 -v -s` terminou sem skip (proibido `1 skipped` aqui) — passou, 54.94s
  - [x] Evidência completa, sem buraco: `(Select-String -Path tests/e2e/evidence/fase1-outcomes-verification.md -Pattern "Veredito: \*\*(ATINGIDO|NÃO ATINGIDO)\*\*").Count` retorna 6 e `Select-String -Path tests/e2e/evidence/fase1-outcomes-verification.md -Pattern "NÃO EXECUTADO"` retorna 0 matches
  - [x] Anti-clobber sob o gate padrão: `Remove-Item Env:HARNESS_E2E_HEADLESS -ErrorAction SilentlyContinue; $env:PYTHONPATH = "src"; python -m pytest tests -q` verde E, na sequência, o check de evidência do item anterior AINDA retorna 6/0 (a suíte inteira não apagou os vereditos caros)
  - [x] Cobaia original intacta: `git -C <caminho da cobaia .NET> status --short` — saída vazia
  - [x] Relato final ao humano com a tabela dos 6 vereditos — 6/6 ATINGIDO
