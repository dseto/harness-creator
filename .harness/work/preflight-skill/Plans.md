# Plans: `/harness-creator:preflight`

Backlog do contrato `preflight-skill`. Formato parseável por
`src/harness/contract.py` (`## [T-XX]` + `files`/`verify`/`depends`).
Cadeia intencionalmente sequencial: T-01→T-04 tocam o mesmo par de arquivos
(`preflight.py` + `test_preflight.py`) — paralelizar geraria conflito de
escrita; o custo de wall-clock é baixo (módulo pequeno).

Convenção de trabalho (vale para todas as tarefas): teste PRIMEIRO no
`tests/test_preflight.py`, depois a implementação mínima que o faz passar;
mensagens/fixes em pt-BR, chaves JSON em inglês; nenhum byte escrito no
repo-alvo avaliado.

## [T-01] Núcleo do laudo: dataclasses `PreflightCheck`/`PreflightCategory`/`PreflightReport`, agregação de status e veredito
- files: `src/harness/preflight.py`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -q`

Detalhe: espelhar o padrão `Finding`/`AuditReport` de `audit.py` (`to_dict`/
`to_json`, `ensure_ascii=False`). Status da categoria = pior status dos checks
(FAIL > WARNING > PASS); veredito READY / READY_WITH_WARNINGS / NOT_READY
conforme spec. Invariante testada aqui: check não-PASS sem `fix` não-vazio é
erro de construção do laudo. `PreflightError` para alvo inexistente/não-diretório.

## [T-02] Categoria 1 — detector Git (binário, repo próprio, baseline commit, worktree limpo, .gitignore)
- files: `src/harness/preflight.py`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -q`
- depends: T-01

Detalhe: `shutil.which("git")` para `git_binary`; presença de repo por
`(alvo/.git).exists()` (dir OU gitfile — nunca `--is-inside-work-tree`, ver
spec); `git -C <alvo> rev-parse --verify HEAD` para `git_baseline_commit`;
`git --no-optional-locks -C <alvo> status --porcelain` para
`git_worktree_clean` (a flag impede o refresh/escrita do `.git/index` pelo
próprio git — requisito da garantia read-only); `.gitignore` na raiz para
`gitignore_present`. Subprocess com timeout e captura; falha inesperada de
subprocess vira check FAIL com a mensagem do erro, nunca exceção não-tratada.
Curto-circuito conforme spec — laudo esperado exato: sem binário →
`git_binary` FAIL, `git_repo` e `gitignore_present` AINDA avaliados, apenas
`git_baseline_commit` e `git_worktree_clean` (os 2 checks de subprocess)
omitidos; sem repo → omite baseline/worktree. Testes cobrem: sem binário
(monkeypatch), dir sem `.git`, repo 0 commits, repo sujo, repo limpo, mock
criado DENTRO de outro repo git (não pode passar de carona).

## [T-03] Categorias 2-4 — política de severidade sobre o `RepoProfile` de `analyze_project()`
- files: `src/harness/preflight.py`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -q`
- depends: T-02

Detalhe: chamar `analyze_project()` UMA vez (puro, sem `write_profile`) e
mapear: `languages` vazio → `manifest_present` FAIL; `test_command is None` →
`test_runner_detected` FAIL; `test_glob is None` → `test_files_present`
WARNING; `extras.lint_command` ausente → `linter_configured` WARNING. PASS
carrega `evidence` do Finding correspondente. Fixes contextuais à linguagem
detectada (ex.: fix de runner para Python sugere pytest; para Node sugere
script `test`). Proibido reimplementar detecção que o analyzer já faz.
Message de `test_files_present` segue o spec: sinaliza convenção de testes
não observada em disco (`tests/**/*.py` etc.), NÃO afirma ausência absoluta
de testes no repo.

## [T-04] `run_preflight()`: orquestração das 4 categorias + garantia read-only
- files: `src/harness/preflight.py`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -q`
- depends: T-03

Detalhe: função pública única `run_preflight(target_dir: Path) -> PreflightReport`
que valida o alvo (`PreflightError` se inexistente/não-diretório), roda as 4
categorias na ordem contratada e monta o report com `target` absoluto. Teste
de read-only do AC-5: snapshot `sorted(rglob)` + mtimes antes/depois idêntico
EXCLUINDO APENAS `.git/` (documentar no teste: `git status` faz refresh de
stat-cache no index — comportamento interno do git, não escrita do preflight,
mitigado por `--no-optional-locks`), ausência de `.harness/` criado, e mock
OBRIGATORIAMENTE repo git com >=1 commit para cobrir o caminho de subprocess.
Testes dos cenários AC-1 (READY com 4 PASS) e AC-2 (NOT_READY do dir vazio)
fecham aqui.

## [T-05] CLI: subcomando `harness preflight --dir` com exit codes 0/1/2
- files: `src/harness/cli.py`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -q`
- depends: T-04

Detalhe: seguir o padrão dos subparsers existentes (import lazy dentro do
branch, `--dir` default `.`, help em pt-BR). Imprime `report.to_json()` no
stdout; exit 0 (READY/READY_WITH_WARNINGS), 1 (NOT_READY), 2 (`PreflightError`
com mensagem em stderr). Testes invocam `main()` com `monkeypatch.setattr(sys, "argv", ...)`
+ `capsys` + `pytest.raises(SystemExit)` cobrindo os três exit codes (AC-6).

## [T-06] Skill `/harness-creator:preflight` (`skills/preflight/SKILL.md`) + teste de frontmatter
- files: `skills/preflight/SKILL.md`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -q`
- depends: T-05

Detalhe: frontmatter no padrão de `skills/plan/SKILL.md` (`name`, `description`,
`when_to_use`, `argument-hint`); corpo: pré-requisito de `PYTHONPATH` idêntico
ao da skill plan, passo 1 roda `python -m harness.cli preflight --dir <alvo>`,
passo 2 apresenta tabela `[PASS]/[WARNING]/[FAIL]` por categoria com Actionable
Fix de cada não-PASS, passo 3 roteia: READY → sugerir `/harness-creator:plan`;
NOT_READY → oferecer aplicar fixes um a um SÓ com confirmação explícita e
re-rodar. Teste (AC-9): parseia o frontmatter YAML do arquivo real e afirma
campos obrigatórios + presença da string do comando CLI no corpo.

## [T-07] Docs e versão 0.15.0: CHANGELOG, README, TUTORIAL, pyproject, plugin.json — gate de regressão total
- files: `CHANGELOG.md`, `README.md`, `TUTORIAL.md`, `pyproject.toml`, `.claude-plugin/plugin.json`
- verify: `python -m pytest tests -q`
- depends: T-06

Detalhe: bump `0.14.1 → 0.15.0` em `pyproject.toml` e `.claude-plugin/plugin.json`
(feature nova, minor); entrada no `CHANGELOG.md` no padrão das anteriores;
seção curta no `README.md` (tabela de comandos) e no `TUTORIAL.md` (preflight
como passo 0, antes do plan). AC-7 (ruff) roda junto desta tarefa. O verify é
a suíte INTEIRA — zero regressão (AC-8).

## [T-08] E2E real (gate final da demanda): mocks em disco, CLI via subprocess, evidência legível commitada
- files: `tests/e2e/test_preflight_e2e.py`, `tests/e2e/evidence/preflight-dogfood-2026-07-17.md`
- verify: `python -m pytest tests/e2e/test_preflight_e2e.py -q`
- depends: T-07

Detalhe (regra permanente do ROADMAP — fase fecha com prova real, não
sintética): o teste monta DOIS mocks reais em disco: (a) "repo Python vazio
sem testes" — `git init` + commit + `pyproject.toml` mínimo sem pytest/ruff,
sem `tests/` — e (b) repo completo (AC-1); invoca `python -m harness.cli preflight`
por `subprocess.run` DE VERDADE (mesmo interpretador, `PYTHONPATH=src`),
valida (a) → exit 1 + `NOT_READY` + fixes acionáveis nas categorias tests/lint
e (b) → exit 0 + `READY`. Grava `tests/e2e/evidence/preflight-dogfood-2026-07-17.md`
com os dois laudos JSON reais colados + comando executado + data — evidência
legível por humano SEM reler código de teste, commitada no repo. Não usa
`HARNESS_E2E_DOGFOOD` (não invoca claude/dotnet — barato, roda no gate padrão).
