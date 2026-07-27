---
slug: preflight-skill
approved_by: "Daniel Seto"
approved_at: "2026-07-17T02:00:00Z"   # timestamp real
stop_conditions:
  - "3 falhas consecutivas do verify_cmd DA MESMA TAREFA (contador por task-id, não pela string do comando) — parar e devolver ao humano com o log da última falha"
  - "Implementação exigir dependência nova fora da stdlib (além do reuso de analyzer/pyyaml já presentes) — parar e perguntar"
  - "Implementação exigir QUALQUER escrita no repo-alvo avaliado pelo preflight — parar (viola a garantia read-only deste contrato)"
  - "Necessidade de mudar assinatura pública de analyzer.py ou contract.py — parar (fora do raio de impacto)"
  - "Suíte completa (python -m pytest tests -q) quebrar em teste que NÃO pertence ao preflight — parar e reportar a regressão sem tentar consertar código alheio"
---

# Spec: `/harness-creator:preflight` — laudo de prontidão de repositório cru

## Escopo

Nova skill `/harness-creator:preflight` e novo subcomando `harness preflight --dir <alvo>`
que avaliam um repositório **antes** da instalação do harness e emitem um laudo
com status `[PASS]`, `[WARNING]` ou `[FAIL]` para 4 categorias de pré-requisitos.
Cada check não-PASS carrega um **Actionable Fix** (comando ou passo concreto).

Posição no fluxo do plugin: `preflight` roda ANTES de `analyze`/`plan` — é o
portão de entrada que diz se o repo cru tem o mínimo para o ciclo
Plan→Work→Review funcionar (git para baseline/diff/rollback, manifest para o
analyzer ter fatos, testes para o `verify_cmd`, lint para o quality gate).

### Decisões de arquitetura (fixadas por este contrato)

1. **Reuso obrigatório do analyzer**: as categorias 2, 3 e 4 derivam de
   `analyze_project()` (`src/harness/analyzer.py`) — detectores de manifest,
   `test_command`, `test_glob` e `extras.lint_command` NÃO são reimplementados.
   O preflight é uma camada de **política de severidade** sobre o `RepoProfile`.
2. **Detector Git é peça nova**: o analyzer ignora `.git` de propósito
   (`_SKIP_DIRS`). A categoria 1 usa `shutil.which("git")` + subprocess
   read-only (`git -C <alvo> rev-parse ...`,
   `git --no-optional-locks -C <alvo> status --porcelain`). A flag
   `--no-optional-locks` é obrigatória: sem ela o próprio git reescreve
   `.git/index` (refresh de stat-cache) como efeito colateral do `status` —
   comprovado empiricamente — o que violaria a decisão 3 e a stop condition
   de read-only; com a flag o git não toma locks opcionais nem escreve o index.
   A presença de repo é decidida por `(alvo/.git).exists()` (dir ou gitfile) —
   NÃO por `rev-parse --is-inside-work-tree`, para um mock criado dentro de
   outro repositório não passar de carona no repo-pai.
3. **Read-only absoluto**: `run_preflight()` não escreve um byte no alvo —
   nem `.harness/repo-profile.json` (usa `analyze_project()` puro, sem
   `write_profile`). Ausência do binário git é um achado da categoria 1, não um crash.
4. **Zero dependência nova**: stdlib + módulos já existentes do pacote.
5. **Saída do CLI é JSON** (convenção do repo — `audit`, `analyze`); a
   apresentação humana `[PASS]/[FAIL]` é responsabilidade da skill.

### As 4 categorias e seus checks (política de severidade exata)

| Categoria | Check (`code`) | Condição de não-PASS | Status | Actionable Fix (exemplo) |
|---|---|---|---|---|
| 1. Controle de Versão (`git`) | `git_binary` | binário `git` ausente do PATH | FAIL | instalar git (link/gerenciador da plataforma) |
| | `git_repo` | `<alvo>/.git` inexistente | FAIL | `git init` |
| | `git_baseline_commit` | HEAD não resolve (0 commits) | WARNING | `git add -A && git commit -m "baseline pré-harness"` |
| | `git_worktree_clean` | `git --no-optional-locks status --porcelain` não-vazio | WARNING | commitar/stashear antes de instalar o harness |
| | `gitignore_present` | `.gitignore` ausente na raiz | WARNING | criar `.gitignore` para a linguagem detectada |
| 2. Manifestos (`manifest`) | `manifest_present` | `profile.languages` vazio (nenhum manifest reconhecido) | FAIL | criar manifest da stack (ex.: `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.csproj`) |
| 3. Verificação/TDD (`tests`) | `test_runner_detected` | `profile.test_command is None` | FAIL | declarar runner (ex.: `pytest` em `[project.optional-dependencies]`, script `test` no `package.json`) |
| | `test_files_present` | `profile.test_glob is None` | WARNING | criar o primeiro teste na convenção detectável pelo analyzer (ex.: `tests/**/*.py` para Python) ou mover os testes existentes para ela |
| 4. Qualidade Estática (`lint`) | `linter_configured` | `extras.lint_command` ausente | WARNING | configurar linter da stack (ex.: `[tool.ruff]` no pyproject, config do eslint) |

Nota sobre `test_files_present`: `test_glob is None` significa "convenção de
testes não observada em disco" — pode haver testes legítimos fora dela (ex.:
`test_*.py` na raiz, que a descoberta padrão do pytest encontra). A `message`
do check diz isso explicitamente; o laudo NÃO afirma ausência absoluta de
testes no repo.

Regras de agregação:
- Status da categoria = pior status entre seus checks (`FAIL > WARNING > PASS`).
- Se `git_repo` falha, `git_baseline_commit`/`git_worktree_clean` são omitidos
  (não há o que medir); `git_binary` ausente → `git_binary` FAIL, `git_repo` e
  `gitignore_present` continuam avaliados (não dependem do binário) e apenas
  os 2 checks de subprocess (`git_baseline_commit`, `git_worktree_clean`) são
  omitidos.
- Veredito global: `NOT_READY` se existe ≥1 FAIL; `READY_WITH_WARNINGS` se
  0 FAIL e ≥1 WARNING; `READY` caso contrário.
- Exit code do CLI: `0` para READY e READY_WITH_WARNINGS, `1` para NOT_READY,
  `2` para erro de uso (alvo inexistente ou não-diretório).
- Todo check não-PASS DEVE ter `fix` não-vazio (invariante testada).

### Formato de saída (contrato do JSON)

```json
{
  "verdict": "READY | READY_WITH_WARNINGS | NOT_READY",
  "target": "<caminho absoluto avaliado>",
  "categories": [
    {
      "id": "git",
      "title": "Controle de Versão (Git)",
      "status": "PASS | WARNING | FAIL",
      "checks": [
        {
          "code": "git_repo",
          "status": "FAIL",
          "message": "diretório não é um repositório git",
          "fix": "git init",
          "evidence": null
        }
      ]
    }
  ]
}
```

`evidence` segue a semântica do analyzer: caminho relativo (POSIX) que provou
o achado quando PASS (ex.: `pyproject.toml`), `null` quando não há prova.
Chaves em inglês (convenção do repo), mensagens/fixes em pt-BR.

### Skill

`skills/preflight/SKILL.md` no padrão das skills existentes (`skills/plan/SKILL.md`):
roda `python -m harness.cli preflight --dir <alvo>` (com o mesmo fallback de
`PYTHONPATH` documentado na skill plan), apresenta o laudo como tabela
`[PASS]/[WARNING]/[FAIL]` por categoria com os fixes, e:
- veredito `READY` → aponta o próximo passo (`/harness-creator:plan`);
- veredito `NOT_READY` → oferece aplicar os fixes UM A UM mediante confirmação
  explícita do usuário (a skill nunca aplica fix sozinha) e re-roda o preflight.

## Critérios de aceitação

- **AC-1 (repo pronto)**: repo mock com git init + 1 commit + `.gitignore` +
  `pyproject.toml` (pytest e `[tool.ruff]`) + `tests/test_x.py` → veredito
  `READY`, 4 categorias PASS. Prova: `python -m pytest tests/test_preflight.py -q`.
- **AC-2 (repo cru)**: diretório vazio (sem git, sem manifest) → `NOT_READY`;
  categoria git FAIL (`git_repo`), manifest FAIL, tests FAIL, lint WARNING;
  todo não-PASS com `fix` não-vazio. Prova: `python -m pytest tests/test_preflight.py -q`.
- **AC-3 (runner sem testes)**: repo Python com pytest declarado e zero
  arquivos de teste → categoria tests = WARNING (`test_files_present`),
  `test_runner_detected` PASS. Prova: `python -m pytest tests/test_preflight.py -q`.
- **AC-4 (árvore suja)**: repo com mudança não-commitada → `git_worktree_clean`
  WARNING. Prova: `python -m pytest tests/test_preflight.py -q`.
- **AC-5 (read-only)**: rodar `run_preflight` não cria/altera/remove NENHUM
  arquivo do alvo: snapshot da árvore (paths + mtimes) antes/depois idêntico
  EXCLUINDO APENAS `.git/` — o index sofre refresh de stat-cache pelo próprio
  git, mitigado por `--no-optional-locks` mas não contratualmente garantido —
  mais checagem explícita de que `.harness/` não nasce. O mock deste teste
  DEVE ser um repo git com >=1 commit, para o caminho de subprocess (o único
  com risco de escrita) ser exercitado. Prova: `python -m pytest tests/test_preflight.py -q`.
- **AC-6 (CLI e exit codes)**: `harness preflight --dir` retorna 0 (READY e
  READY_WITH_WARNINGS), 1 (NOT_READY), 2 (alvo inexistente, mensagem clara em
  stderr). Prova: `python -m pytest tests/test_preflight.py -q`.
- **AC-7 (lint do próprio código)**: `ruff check src/harness/preflight.py tests/test_preflight.py tests/e2e/test_preflight_e2e.py` sem findings.
- **AC-8 (zero regressão)**: `python -m pytest tests -q` inteira verde.
- **AC-9 (skill)**: `skills/preflight/SKILL.md` existe, frontmatter YAML
  parseável com `name`/`description`/`when_to_use`, corpo referencia o comando
  real do CLI. Prova: `python -m pytest tests/test_preflight.py -q` (teste dedicado).
- **AC-10 (prova real, gate final)**: E2E cria mock em disco de "repo Python
  vazio sem testes", invoca `python -m harness.cli preflight` via subprocess
  real, valida `NOT_READY` + fixes no JSON, e grava evidência legível em
  `tests/e2e/evidence/preflight-dogfood-2026-07-17.md` (laudo real colado,
  commitado). Prova: `python -m pytest tests/e2e/test_preflight_e2e.py -q`.

## Não-objetivos

- Aplicar fixes automaticamente por conta própria (o CLI nunca escreve no alvo;
  a skill só aplica fix com confirmação explícita, um a um).
- Validação profunda de manifest (parse/schema de pyproject/package.json além
  do que o analyzer já faz).
- Checks de typecheck/build/CI como categorias próprias (ficam para evolução;
  hoje o laudo cobre exatamente as 4 categorias contratadas).
- Flag `--format text`/saída humana no CLI (JSON only; renderização é da skill).
- Integrar o preflight como passo automático da skill `plan` (avaliar depois,
  demanda separada).
- Score numérico 0-100 (o laudo é categórico: PASS/WARNING/FAIL + veredito).

## Unknowns

- **Severidade de linter ausente** — RESOLVIDO (Daniel Seto, 2026-07-17):
  **WARNING** confirmado.
- **Severidade de repo git com 0 commits** — RESOLVIDO (Daniel Seto,
  2026-07-17): **WARNING** (proposta original era FAIL; decisão do usuário —
  ausência de baseline alerta, não bloqueia).
- Nenhum unknown de repo-profile se aplica (o alvo desta demanda é o próprio
  plugin, cujo perfil — pytest, ruff, src-layout — é fato observado).
