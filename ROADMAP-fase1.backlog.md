# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Fase 1 do ROADMAP.md — Delegação Baseada em Contratos
# Origem: ROADMAP.md (Fase 1). Gerado 2026-07-15 via plan-to-backlog.
# Validação global ao fechar: $env:PYTHONPATH = "src"; python -m pytest tests -q  (87 pré-existentes + novos, zero falhas)
# [SUBAGENTE 08] é opt-in (HARNESS_E2E_DOGFOOD=1) e NÃO entra nesse gate — mesmo padrão de
# tests/e2e/test_headless.py: custa tokens reais + precisa de `claude`/`dotnet` no PATH.
#
# Bootstrap (rodar uma vez, antes do primeiro subagente — ambiente pode não ter os dev-deps):
#   pip install -e ".[dev]"
#
# 🗺️ Mapa de Dependências dos Subagentes (revisado após reflect — ver nota no bloco 04):
#   - 🟢 Fase 1: [SUBAGENTE 01] e [SUBAGENTE 03] (paralelo — analyzer.py/tests vs contract.py/tests, arquivos disjuntos, sem dependência entre si)
#   - 🟡 Fase 2: [SUBAGENTE 02] (depende de 01) e [SUBAGENTE 04] (depende de 01 e 03) — paralelo, arquivos disjuntos (04 usa tests/test_cli.py dedicado, não mais test_analyzer.py/test_contract.py)
#   - 🟠 Fase 3: [SUBAGENTE 05] e [SUBAGENTE 06] (ambos dependem de 04 — CLI completa) — paralelo, arquivos disjuntos
#   - 🔴 Fase 4: [SUBAGENTE 07] (depende de tudo acima — documenta CLI, skill e E2E prontos) — sequencial
#   - 🏁 Fase 5: [SUBAGENTE 08] (depende de 04 — CLI completa; roda por último como gate final, opt-in) — prova real: cópia de C:\Projetos\MinimumAPI, contrato aprovado, Claude real implementando, dotnet test real

> 🏁 DEMANDA FECHADA — 2026-07-16
> Correção consolidada em `ROADMAP-fase1.correction.backlog.md` (2 bugs do arnês de teste:
> evidence writer sobrescrevendo entre processos; teste headless sem baseline de permissões —
> nenhum dos dois era bug de produto). Os 6 outcomes da Fase 1 (ver
> `ROADMAP-fase1.outcomes-report.md` seção 2) estão com veredito **ATINGIDO** em
> `tests/e2e/evidence/fase1-outcomes-verification.md`.

### [SUBAGENTE 01] - Analyzer: schema do profile + detectores core
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Criar `src/harness/analyzer.py` com o schema evidence/confidence/unknowns e os detectores de linguagem, manifest e teste — análise 100% determinística (zero LLM, zero rede).
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/compiler.py` (estilo do módulo: dataclasses, docstring PT-BR, funções puras separadas de I/O), `src/harness/audit.py` (padrão `_SKIP_DIRS`), `src/harness/verification/tdd_loop.py` (`_glob_to_regex` — reusar, não reimplementar), `ROADMAP.md` (seção "Fase 1")
  - Modificar (criar): `src/harness/analyzer.py`, `tests/test_analyzer.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie `src/harness/analyzer.py` no padrão do repo (docstring PT-BR, dataclasses, funções puras + camada fina de I/O, stdlib apenas — sem dependência nova). Estruturas: `@dataclass Finding {value: Any, evidence: str, confidence: float}` (evidence = caminho relativo do arquivo que provou o achado) e `@dataclass RepoProfile {languages: list[Finding], package_manager: Finding|None, test_command: Finding|None, test_glob: Finding|None, extras: dict[str, Finding], unknowns: list[str], analyzed_at: str, manifest_snapshot: dict[str,str]}` com `to_dict()`/`from_dict()`. Funções: `analyze_project(target_dir: Path) -> RepoProfile` e `write_profile(profile, target_dir)` gravando `.harness/repo-profile.json` (UTF-8, indent 2, regenerado do zero a cada chamada). Detectores desta tarefa (ignore diretórios do padrão `_SKIP_DIRS` do audit.py): (1) linguagens/manifests — `pyproject.toml`/`setup.py`→python, `package.json`→javascript/typescript (typescript se `tsconfig.json`), `*.csproj`/`*.sln`→csharp, `go.mod`→go, `Cargo.toml`→rust; (2) package manager — lockfiles (`package-lock.json`→npm, `pnpm-lock.yaml`→pnpm, `yarn.lock`→yarn, `uv.lock`→uv, `poetry.lock`→poetry); (3) test_command — por manifest: python→`pytest` se pytest em deps/dev-deps ou `pytest.ini`/`[tool.pytest.ini_options]`; node→script `test` do package.json (valor literal); csharp→`dotnet test`; go→`go test ./...`; (4) test_glob — proponha convenção por linguagem (`tests/**/*.py`, `**/*.test.ts`, `**/*Tests.cs`, `**/*_test.go`) e VALIDE contra o disco usando `_glob_to_regex` de `harness.verification.tdd_loop` (já usado por compiler.py e audit.py — reuse essa função em vez de reimplementar o matching de glob, pra não divergir semanticamente do resto do repo): se nenhum arquivo casar, o glob NÃO entra como Finding — registre em `unknowns` (regra do ROADMAP: não-observado não vira fato). Tudo que não for detectável com evidência entra em `unknowns` como string descritiva (ex.: 'test_command: nenhum runner detectado'). `manifest_snapshot` = {caminho relativo do manifest: sha256 do conteúdo} para os manifests encontrados. Crie `tests/test_analyzer.py` com repos sintéticos via `tmp_path` (python com pyproject+pytest+tests/, node com package.json+lockfile+script test, repo vazio→unknowns povoado, glob sem arquivos→vira unknown). Não toque em cli.py nem em nenhum outro módulo. Não faça refatoração fora deste objetivo."
- **🧪 Critério de Validação (DoD):**
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests/test_analyzer.py -q` — verde
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — suíte inteira verde (nenhuma regressão)
  - [x] `python -m ruff check src/harness/analyzer.py tests/test_analyzer.py` — limpo

---

### [SUBAGENTE 02] - Analyzer: detectores estendidos (lint/build, CI, monorepo, serviços, docs)
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Completar `analyzer.py` com os detectores de lint/typecheck/build, CI, monorepo, docker-compose e docs existentes — mesmo contrato Finding/unknowns da tarefa 01.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/analyzer.py` (estado pós-tarefa 01), `tests/test_analyzer.py`
  - Modificar: `src/harness/analyzer.py`, `tests/test_analyzer.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, estenda `src/harness/analyzer.py` (NÃO altere o schema Finding/RepoProfile nem os detectores existentes) adicionando detectores que preenchem `extras` — chaves: (1) `lint_command` — ruff em pyproject/`ruff.toml`→`ruff check .`, eslint config→script `lint` do package.json ou `npx eslint .`; (2) `typecheck_command` — `tsconfig.json`→`npx tsc --noEmit`, mypy em config→`mypy`; (3) `build_command` — script `build` do package.json, `dotnet build` se csproj, `go build ./...` se go.mod; (4) `ci` — arquivos `.github/workflows/*.yml`|`*.yaml` (evidence = caminho do workflow; value = lista de nomes de arquivo); (5) `monorepo` — `workspaces` no package.json, `pnpm-workspace.yaml`, ou `*.sln` referenciando 2+ csproj; (6) `services` — `docker-compose.yml`|`compose.yaml` (value = lista de nomes de service, parse com PyYAML que já é dependência do projeto); (7) `docs` — presença de `README.md`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md` (value = lista dos presentes). Cada detector: achou com prova → Finding com evidence; não achou → NADA (ausência de CI não é unknown, é ausência — só registre unknown quando houver sinal ambíguo, ex.: package.json sem script test já é tratado na 01). Adicione casos em `tests/test_analyzer.py`: repo com workflow de CI, repo com docker-compose com 2 services, monorepo com workspaces, repo python com ruff configurado. Não toque em nenhum outro arquivo."
- **🧪 Critério de Validação (DoD):**
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests/test_analyzer.py -q` — verde
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — suíte inteira verde
  - [x] `python -m ruff check src/harness/analyzer.py tests/test_analyzer.py` — limpo

---

### [SUBAGENTE 03] - Contract: formato do contrato + compile_contract com gate de aprovação
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Criar `src/harness/contract.py`: parse de `spec.md` (gate approved_by/approved_at) + `Plans.md` (tarefas com files[] e verify_cmd) → `.harness/feature_list.json`, preservando `passes` de tarefas inalteradas.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/compiler.py` (padrão de constantes de caminho e merge preservando estado), `ROADMAP.md` (Fase 1 e Fase 3 — schema do feature_list)
  - Modificar (criar): `src/harness/contract.py`, `tests/test_contract.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie `src/harness/contract.py` (stdlib + PyYAML para frontmatter, docstring PT-BR). Formato do contrato — diretório `.harness/work/<slug>/` contendo: `spec.md` com frontmatter YAML (`slug`, `approved_by`, `approved_at`, opcional `stop_conditions`) e `Plans.md` com blocos de tarefa em markdown no formato exato:
  > ```
  > ## [T-01] <descrição curta>
  > - files: `caminho/a.py`, `caminho/b.py`
  > - verify: `<comando de verificação>`
  > - depends: T-01, T-02
  > ```
  > (`depends` é OPCIONAL e vazio por padrão — lista de ids de que essa tarefa depende; ROADMAP.md define Plans.md como tendo "sequência de tarefas, **dependências**, arquivos afetados" e a Fase 4 promete um Supervisor que despacha "respeitando dependências do Plans.md", então reserve a sintaxe agora para não quebrar compatibilidade depois — mas NÃO implemente nenhuma lógica de ordenação/dispatch nesta tarefa, só parseie e preserve o campo). Funções: `parse_spec(spec_path) -> dict` (frontmatter; erro claro se malformado), `parse_plans(plans_path) -> list[Task]` (`@dataclass Task {id: str, desc: str, files: list[str], verify_cmd: str, depends: list[str] = campo com default_factory=list}`; erro nomeando a tarefa se faltar files ou verify), e `compile_contract(target_dir: Path, slug: str) -> Path`. GATE OBRIGATÓRIO: se `approved_by` ou `approved_at` ausentes/vazios no frontmatter → levante `ContractNotApprovedError` com mensagem 'contrato não aprovado — preencha approved_by/approved_at no spec.md' e NÃO escreva nada em disco (regra do ROADMAP: sem aprovação, nada compila). Saída: `.harness/feature_list.json` = `{"contract": "<slug>", "compiled_at": "<iso>", "features": [{"id", "desc", "files": [...], "verify_cmd", "depends": [...], "passes": false}]}`. Recompilação: se o feature_list.json já existir, preserve `passes: true` das features cujo (id, verify_cmd, files) não mudaram — id novo entra com passes:false, id removido do plano sai do json. No docstring do módulo, inclua um exemplo COMPLETO e LITERAL de um `spec.md` e um `Plans.md` válidos (com frontmatter preenchido e 1-2 blocos `## [T-XX]`), pra servir de referência exata pra quem for gerar esses arquivos depois (skill `plan`, tarefa 05) sem precisar reverse-engenheirar o parser. Crie `tests/test_contract.py`: contrato aprovado compila com schema correto; não aprovado → ContractNotApprovedError e nenhum arquivo escrito; recompilação preserva passes de id inalterado e zera id modificado; recompilação com SÓ a `desc` de uma tarefa mudando (id/verify_cmd/files iguais) preserva passes:true dessa tarefa; id removido do Plans.md desaparece de `features` no feature_list.json recompilado; Plans.md com tarefa sem verify → erro nomeando T-XX; `depends` presente no bloco é parseado e aparece em `Task.depends`/no JSON de saída, ausente vira lista vazia; `parse_spec` retorna `stop_conditions` no dict quando presente no frontmatter. Não toque em cli.py nem em outros módulos."
- **🧪 Critério de Validação (DoD):**
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests/test_contract.py -q` — verde
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — suíte inteira verde
  - [x] `python -m ruff check src/harness/contract.py tests/test_contract.py` — limpo

---

### [SUBAGENTE 04] - CLI: subcomandos `analyze` e `compile-contract`
> ✅ CONCLUÍDO
> ⚠️ Nota pós-reflect: escopo de testes movido para `tests/test_cli.py` dedicado (em vez de anexar a `tests/test_analyzer.py`/`tests/test_contract.py`) — essa tarefa roda em paralelo com [SUBAGENTE 02] na Fase 2 (ambas dependem só de 01/03), e 02 também edita `tests/test_analyzer.py`; um arquivo de teste novo e exclusivo desta tarefa elimina a colisão de merge entre agentes paralelos.
- **🎯 Objetivo:** Expor analyzer e contract no CLI existente com saída JSON e exit codes coerentes com o padrão do repo.
- **📂 Escopo de Arquivos:**
  - Ler: `src/harness/cli.py` (padrão dos subcomandos compile/audit: import lazy, `--dir`, JSON no stdout, erro no stderr + exit 1), `src/harness/analyzer.py`, `src/harness/contract.py`, `tests/test_compiler.py` ou `tests/test_audit.py` (estilo de teste de CLI já existente no repo, se subcomandos análogos já tiverem teste lá — só para referência, não modificar)
  - Modificar (criar): `src/harness/cli.py`, `tests/test_cli.py` (arquivo novo, dedicado aos testes de CLI desta tarefa — NÃO tocar em `tests/test_analyzer.py` nem `tests/test_contract.py`)
- **🤖 Prompt para o Claude Code:**
  > "Claude, adicione dois subcomandos ao parser de `src/harness/cli.py`, seguindo exatamente o padrão dos existentes (import lazy dentro do branch, flag `--dir` default '.', JSON indent 2 ensure_ascii=False no stdout): (1) `harness analyze --dir X` — chama `analyze_project` + `write_profile`, imprime o profile completo em JSON e SEMPRE exit 0 (unknowns são resultado válido, não erro); (2) `harness compile-contract --dir X --slug Y` — chama `compile_contract`; sucesso imprime `{"feature_list": "<path>", "features": <n>, "contract": "<slug>"}` exit 0; `ContractNotApprovedError` ou arquivo ausente → mensagem no stderr prefixada 'erro: ' + exit 1 (mesmo shape do subcomando compile). Crie `tests/test_cli.py` (arquivo NOVO — não anexe a test_analyzer.py/test_contract.py) com um teste de CLI para cada subcomando, invocando `main()` com `monkeypatch.setattr(sys, 'argv', ...)` e capsys (siga o estilo dos testes existentes do repo). Não altere os subcomandos run/compile/audit. Nenhuma refatoração fora disso."
- **🧪 Critério de Validação (DoD):**
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests/test_cli.py -q` — verde
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — suíte inteira verde
  - [x] `python -m ruff check src/harness/cli.py tests/test_cli.py` — limpo
  - [x] Assert automatizável (substitui smoke manual por eyeball): `$env:PYTHONPATH = "src"; python -c "import json, subprocess, sys; r = subprocess.run([sys.executable, '-m', 'harness.cli', 'analyze', '--dir', '.'], capture_output=True, text=True); assert r.returncode == 0, r.stderr; data = json.loads(r.stdout); assert 'python' in [f['value'] for f in data['languages']], data; print('OK')"` imprime `OK`

---

### [SUBAGENTE 05] - Skill `/harness-creator:plan`
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Criar `skills/plan/SKILL.md` — o fluxo demanda→spec.md+Plans.md→aprovação humana (gate único)→compile-contract, no padrão das skills existentes do plugin.
- **📂 Escopo de Arquivos:**
  - Ler: `skills/init/SKILL.md` (padrão: frontmatter name/description/when_to_use, dica de PYTHONPATH só-se-falhar, regras no fim), `skills/compile/SKILL.md`, `src/harness/contract.py` (formato exato de spec/Plans/frontmatter), `ROADMAP.md` (Fase 1)
  - Modificar (criar): `skills/plan/SKILL.md`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie `skills/plan/SKILL.md` com frontmatter no padrão das skills existentes (name: plan; description e when_to_use citando 'contrato', 'spec', 'plano aprovado', 'delegação'; argument-hint: \"[descrição da demanda]\"). Passos do workflow que a skill instrui: (1) rodar `python -m harness.cli analyze --dir <alvo>` (dica de PYTHONPATH igual à skill init: só se der ModuleNotFoundError); (2) apresentar achados do profile em 1 tabela curta e os `unknowns` como perguntas diretas ao usuário — unknowns confirmados viram fatos do contrato, não-confirmados permanecem unknowns no spec (proibido inventar); (3) entrevista mínima da demanda (objetivo, critérios de aceite EXECUTÁVEIS — cada um com comando de prova, não-objetivos, stop conditions); (4) escrever `.harness/work/<slug>/spec.md` e `Plans.md` NO FORMATO EXATO que `contract.py` parseia (embuta os dois templates no SKILL.md, com o frontmatter `approved_by`/`approved_at` VAZIOS); (5) apresentar o contrato ao usuário e pedir aprovação explícita — REGRA DURA em destaque: a skill NUNCA preenche approved_by/approved_at por conta própria; só após o humano dizer que aprova, preencher com o nome dele e timestamp ISO; (6) rodar `python -m harness.cli compile-contract --dir <alvo> --slug <slug>` e mostrar o feature_list.json gerado (n de features, verify_cmd de cada). Seção 'Regras' final: nunca auto-aprovar; nunca promover unknown a fato sem confirmação do usuário; se compile-contract der exit 1 de não-aprovado, voltar ao passo 5, não contornar. Não modifique nenhuma outra skill nem código Python."
- **🧪 Critério de Validação (DoD):**
  - [x] Frontmatter válido, checado por grep determinístico (não por leitura/eyeball): `Select-String -Path skills/plan/SKILL.md -Pattern "^name:|^description:|^when_to_use:|^argument-hint:"` retorna as 4 linhas
  - [x] Templates embutidos batem com o parser: copiar o template de Plans.md do SKILL.md para um contrato de teste e rodar `$env:PYTHONPATH = "src"; python -m pytest tests/test_contract.py -q` continua verde (o formato não divergiu)
  - [x] Grep de sanidade: `Select-String -Path skills/plan/SKILL.md -Pattern "approved_by"` retorna as menções do gate (template + regra de nunca auto-aprovar)

---

### [SUBAGENTE 06] - E2E: fluxo contrato completo em repo sintético
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Teste E2E que roda analyze→spec/Plans→gate reprovado→aprovação→compile-contract via subprocess, como na vida real, num repo sintético em tmp.
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/conftest.py` e `tests/e2e/test_minimumapi.py` (padrão E2E do repo: subprocess, env com PYTHONPATH, sem rede), `src/harness/contract.py`, `src/harness/analyzer.py`
  - Modificar (criar): `tests/e2e/test_contract_flow.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie `tests/e2e/test_contract_flow.py` seguindo o padrão de subprocess dos E2E existentes (invocar `python -m harness.cli ...` com env PYTHONPATH=src, cwd controlado, sem rede, sem Docker). Cenário num repo sintético node criado em tmp_path (package.json com script test + package-lock.json + um arquivo `src/index.test.js`): (1) `analyze --dir` → exit 0, stdout JSON com language javascript, package_manager npm, test_command do script, e `.harness/repo-profile.json` gravado; (2) escrever `.harness/work/demo/spec.md` SEM approved_by + `Plans.md` com 2 tarefas válidas → `compile-contract --dir --slug demo` → exit 1, stderr contém 'não aprovado', e `.harness/feature_list.json` NÃO existe; (3) preencher approved_by/approved_at → recompilar → exit 0, feature_list.json com 2 features passes:false; (4) marcar passes:true na T-01 à mão, editar a desc da T-02 no Plans.md, recompilar → T-01 preserva passes:true, T-02 continua false. Use os formatos exatos de contract.py. Não modifique conftest nem os E2E existentes."
- **🧪 Critério de Validação (DoD):**
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_contract_flow.py -v` — verde
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — suíte inteira verde (E2E MinimumAPI podem estar skipped sem a cobaia; zero falhas)
  - [x] `python -m ruff check tests/e2e/test_contract_flow.py` — limpo

---

### [SUBAGENTE 07] - Docs: README, GUIDE, CHANGELOG e pyproject.toml da Fase 1
> ✅ CONCLUÍDO
- **🎯 Objetivo:** Documentar os artefatos novos (analyze, plan, compile-contract) e registrar a versão 0.11.0 EM TODOS os arquivos de versão do repo, no tom PT-BR direto do repo.
- **📂 Escopo de Arquivos:**
  - Ler: `README.md`, `GUIDE.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `pyproject.toml`, `ROADMAP.md` (Fase 1)
  - Modificar: `README.md`, `GUIDE.md`, `CHANGELOG.md`, `.claude-plugin/plugin.json`, `pyproject.toml`
- **🤖 Prompt para o Claude Code:**
  > "Claude, atualize a documentação para a Fase 1 do ROADMAP (Delegação Baseada em Contratos), mantendo o tom existente (PT-BR, direto, sem marketing): (1) README.md — adicione `/harness-creator:plan` à tabela de skills (uma linha: demanda → spec.md + Plans.md → aprovação humana → feature_list.json), os subcomandos `harness analyze` e `harness compile-contract` à linha de CLI equivalente, e troque a linha de versão no topo do arquivo (`**v0.10.0** · [CHANGELOG](CHANGELOG.md)`) para `**v0.11.0**`; (2) GUIDE.md — nova seção curta 'Trabalhar por contrato' inserida DEPOIS da seção 4 atual ('Mudou de ideia sobre a política?'), com o fluxo: `/harness-creator:plan` → revisar/aprovar spec e Plans → feature_list.json gerado (mencione que o gate exige approved_by/approved_at e que a skill nunca aprova sozinha). Como isso empurra as seções existentes, RENUMERE: a seção 5 atual ('Verificar se está tudo consistente') vira 6, a seção 6 atual ('Deixar o plugin sempre disponível') vira 7, e a nova seção de contrato é a 5 — confira que não sobra número duplicado nem buraco. Atualize também o diagrama ASCII em 'Resumo do ciclo completo' no fim do arquivo pra refletir a nova etapa (pode ser uma linha extra no fluxo, não precisa redesenhar tudo); (3) CHANGELOG.md — entrada 0.11.0 no topo, mesmo formato das existentes, listando: analyzer determinístico com evidence/unknowns, repo-profile.json, contract.py com gate de aprovação, skill plan, 2 subcomandos de CLI, E2E do fluxo de contrato; (4) `.claude-plugin/plugin.json` — version para 0.11.0; (5) `pyproject.toml` — `version = \"0.11.0\"` em `[project]` (hoje está em 0.10.0, desalinhado do plugin.json — mantenha os dois sincronizados). Não altere ARCHITECTURE.md nem ROADMAP.md. Nenhuma mudança de código."
- **🧪 Critério de Validação (DoD):**
  - [x] `python -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"` imprime `0.11.0`
  - [x] `python -c "import tomllib; print(tomllib.load(open('pyproject.toml','rb'))['project']['version'])"` imprime `0.11.0`
  - [x] `Select-String -Path README.md -Pattern "compile-contract"`, `Select-String -Path README.md -Pattern "v0.11.0"` e `Select-String -Path CHANGELOG.md -Pattern "0.11.0"` retornam match
  - [x] `Select-String -Path GUIDE.md -Pattern "^## "` não retorna dois `## 5` nem dois `## 6` (renumeração sem duplicata)
  - [x] `$env:PYTHONPATH = "src"; python -m pytest tests -q` — verde (garantia de que nada de código foi tocado)

---

### [SUBAGENTE 08] - E2E dogfood real: contrato completo na MinimumAPI + Claude real implementando
> ✅ CONCLUÍDO — rodado de verdade, 1 passed in 46.99s, evidência em tests/e2e/evidence/fase1-dogfood-document-digits.md
> ⚠️ Gate final da Fase 1, não um teste unitário sintético. Roda numa CÓPIA fresca de
> `C:\Projetos\MinimumAPI` (repo real, mesma cobaia que `tests/e2e/conftest.py` já usa),
> aprova um contrato de verdade, invoca o binário `claude` de verdade em modo headless pra
> implementar uma melhoria REAL, e prova com `dotnet test` real — não com asserção sobre o
> texto de saída do Claude. Segue o mesmo padrão opt-in de `tests/e2e/test_headless.py`
> (custa tokens reais, exige `claude` e `dotnet` no PATH) — por isso NÃO entra no gate
> `pytest tests -q` do cabeçalho deste backlog.
- **🎯 Objetivo:** Provar de ponta a ponta que analyze→spec/Plans aprovado→compile-contract→execução real produz uma melhoria de código genuína e verificável, na cobaia real do projeto.
- **📂 Escopo de Arquivos:**
  - Ler: `tests/e2e/conftest.py` (fixture `api_project`, função `copy_api_source`, `API_SRC` — a cópia gerada tem `MinimumAPI/` + `MinimumAPI.Tests/` com `CustomerValidatorTests.cs` já presente), `tests/e2e/test_headless.py` (padrão real: `claude -p <prompt> --output-format json`, timeout, skip se `claude` ausente do PATH, checar `permission_denials`/`is_error` no JSON — NÃO confiar em exit code), `scripts/make_playground.py` (harness.yaml de exemplo com `governance.approval_policy`, `verification.test_command: "dotnet test"`; nota de que sem `.sln` o comando real é `dotnet test MinimumAPI.Tests`), `src/harness/contract.py` (formato exato de spec.md/Plans.md — usar o exemplo literal do docstring do módulo), `src/harness/analyzer.py`, `src/harness/cli.py`, `src/harness/compiler.py` (`compile_project`, `governance.approval_policy: auto` libera Edit em arquivos de código sem prompt; `edit_test`/rede continuam sempre gateados independente da política — por isso a tarefa do contrato desta melhoria toca SÓ o arquivo de validação, nunca o arquivo de teste)
  - Modificar (criar): `tests/e2e/test_contract_dogfood.py`
- **🤖 Prompt para o Claude Code:**
  > "Claude, crie `tests/e2e/test_contract_dogfood.py`. Marque o módulo inteiro com
  > `pytestmark = pytest.mark.skipif(os.environ.get('HARNESS_E2E_DOGFOOD') != '1', reason='opt-in: custa tokens reais e exige dotnet+claude no PATH (rode com HARNESS_E2E_DOGFOOD=1)')`,
  > e adicione um fixture `autouse=True` que dá skip se `shutil.which('claude')` ou
  > `shutil.which('dotnet')` forem `None` (mesmo padrão de `test_headless.py`). Use a fixture
  > `api_project` de `tests/e2e/conftest.py` (cobaia real de `C:/Projetos/MinimumAPI`, já skip se
  > `HARNESS_E2E_API_SRC`/MinimumAPI não existir no disco).
  >
  > O gap real a corrigir (confirmado por leitura de `C:\Projetos\MinimumAPI\Validators\CustomerValidators.cs`):
  > `CreateCustomerRequestValidator` valida `Document` só por tamanho (`MinimumLength(11)`/`MaximumLength(20)`),
  > sem checar que é só dígitos — hoje um documento tipo `'abc12345678'` passa na validação.
  >
  > Passos do teste (nessa ordem, cada assert usando prova real de subprocess, nunca confiança
  > no texto do Claude):
  > 1. TDD real antes de tudo: edite (via Python, não via Claude) `<cobaia>/MinimumAPI.Tests/CustomerValidatorTests.cs`
  >    adicionando um `[Fact] Document_with_letters_fails` que cria um `CreateCustomerRequest`
  >    com `Document: '1234567890a'` e `ShouldHaveValidationErrorFor(x => x.Document)`. Rode
  >    `dotnet test MinimumAPI.Tests` (cwd=cobaia, subprocess, timeout generoso ~180s) e
  >    **assert que FALHA** (prova que o teste é real e vermelho antes da correção).
  > 2. Rode `python -m harness.cli analyze --dir <cobaia>` (subprocess, env PYTHONPATH=src) —
  >    assert exit 0, profile no stdout JSON tem `csharp` em `languages` e `.harness/repo-profile.json`
  >    foi gravado.
  > 3. Escreva `.harness/work/dogfood-document-digits/spec.md` (frontmatter `slug`,
  >    `approved_by: 'harness-e2e-dogfood'`, `approved_at: <iso agora>` — PRÉ-APROVADO, já que
  >    esta tarefa prova o mecanismo de contrato compilado, não a UI de aprovação humana, que é
  >    coberta por `tests/e2e/test_contract_flow.py`) e `Plans.md` com EXATAMENTE uma tarefa,
  >    tocando só o arquivo de produção (nunca o de teste, pra não esbarrar no gate `edit_test`
  >    sempre-ativo de `compiler.py`):
  >    ```
  >    ## [T-01] Documento deve conter apenas dígitos
  >    - files: `MinimumAPI/Validators/CustomerValidators.cs`
  >    - verify: `dotnet test MinimumAPI.Tests`
  >    ```
  > 4. Rode `python -m harness.cli compile-contract --dir <cobaia> --slug dogfood-document-digits`
  >    — assert exit 0 e `.harness/feature_list.json` com 1 feature `passes: false`.
  > 5. Compile TAMBÉM um `harness.yaml` de governança nessa cobaia (mecanismo já existente,
  >    `compile_project` de `harness.compiler` — igual `scripts/make_playground.py` faz) com
  >    `governance.approval_policy: auto` e `verification.test_command: 'dotnet test MinimumAPI.Tests'`,
  >    pra que a edição do arquivo de produção não fique presa em `ask` num headless sem TTY
  >    (headless nunca aprova `ask` sozinho — nega e segue, documentado em `test_headless.py`).
  > 6. Invoque `claude` real e headless (`subprocess.run(['claude', '-p', <prompt>, '--output-format', 'json'], cwd=<cobaia>, timeout=180)`)
  >    com um prompt que cita literalmente a tarefa T-01 do Plans.md e instrui: implementar a
  >    regra em `CreateCustomerRequestValidator` (`RuleFor(x => x.Document)` ganha
  >    `.Matches(@'^\d+$').WithMessage('O documento deve conter apenas dígitos.')` ou equivalente)
  >    e rodar `dotnet test MinimumAPI.Tests` ele mesmo antes de terminar, só declarando feito se
  >    o comando passar. Assert `out['is_error'] is False`.
  > 7. PROVA FINAL (não confie no que o Claude disse): rode `dotnet test MinimumAPI.Tests` de novo,
  >    via subprocess, fora do Claude — assert `returncode == 0` (suíte inteira verde, incluindo o
  >    `Document_with_letters_fails` que estava vermelho no passo 1) E que os 3 testes que já
  >    existiam antes da mudança (`Valid_request_passes`, `Empty_name_fails`, `Short_document_fails`)
  >    continuam passando — isso é a prova de ZERO REGRESSÃO, não só de funcionalidade nova.
  > 8. EVIDÊNCIA EM ARQUIVO (não basta o pytest passar — grave prova legível pro humano conferir):
  >    crie o diretório `tests/e2e/evidence/` se não existir, e escreva
  >    `tests/e2e/evidence/fase1-dogfood-document-digits.md` (commitado no repo, não em tmp) com:
  >    saída completa (nomes de teste + pass/fail) do `dotnet test` do passo 1 (vermelho, antes),
  >    saída completa do passo 7 (verde, depois, todos os 4 testes), o diff exato de
  >    `CustomerValidators.cs` (antes/depois, via `difflib` ou string literal), e um resumo da
  >    resposta do `claude -p` (campos `is_error`, `permission_denials`, `num_turns` se presentes no
  >    JSON, mais os últimos ~500 caracteres do texto de resposta). Formato: markdown com seções
  >    `## Regressão (testes pré-existentes)`, `## Nova funcionalidade`, `## Diff aplicado`,
  >    `## Execução do agente`. O teste grava esse arquivo SEMPRE que rodar (passou ou falhou —
  >    em falha, registre onde parou), não só no caminho feliz.
  > Não modifique `conftest.py` nem os E2E existentes. Não toque no arquivo de teste depois do
  > passo 1 (só o Claude, no passo 6, deve tocar o arquivo de validação)."
- **🧪 Critério de Validação (DoD):**
  - [x] Sem `HARNESS_E2E_DOGFOOD` setado: `$env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_contract_dogfood.py -v` — skipped, suíte não quebra
  - [x] Com o ambiente real disponível: `$env:HARNESS_E2E_DOGFOOD = "1"; $env:PYTHONPATH = "src"; python -m pytest tests/e2e/test_contract_dogfood.py -v -s` — verde (pode levar minutos: dotnet restore + build + claude real)
  - [x] `python -m ruff check tests/e2e/test_contract_dogfood.py` — limpo
  - [x] `Test-Path tests/e2e/evidence/fase1-dogfood-document-digits.md` retorna `True` após a execução real, e o arquivo tem as 4 seções (`Select-String -Path tests/e2e/evidence/fase1-dogfood-document-digits.md -Pattern "^## "` retorna 4 linhas)
  - [x] Confirmação humana pós-execução: `git -C C:\Projetos\MinimumAPI diff --stat` continua vazio (a tarefa só editou a CÓPIA em tmp, nunca o repo original)
