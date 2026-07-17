# `/harness-creator:preflight` — laudo de prontidão de repositório cru

> Portão de entrada do ciclo Plan→Work→Review. Roda ANTES de `analyze`/`plan`
> e responde uma pergunta só: **este repo, do jeito que está hoje, tem o
> mínimo pra instalar e operar o harness?** 100% read-only — não escreve um
> byte no repositório avaliado, nem mesmo `.harness/`.

- Skill: `skills/preflight/SKILL.md`
- CLI: `harness preflight --dir <alvo>`
- Implementação: [`src/harness/preflight.py`](../src/harness/preflight.py)
- Testes: [`tests/test_preflight.py`](../tests/test_preflight.py) (47 casos)
- E2E real + evidência: [`tests/e2e/test_preflight_e2e.py`](../tests/e2e/test_preflight_e2e.py) · [`tests/e2e/evidence/preflight-dogfood-2026-07-17.md`](../tests/e2e/evidence/preflight-dogfood-2026-07-17.md)
- Contrato de origem (spec aprovada + backlog): [`.harness/work/preflight-skill/`](../.harness/work/preflight-skill/)

## Por que existe

Antes deste laudo, um repositório cru ia direto para `/harness-creator:plan`,
que só descobre no meio da entrevista que faltam pré-requisitos básicos (sem
git não há baseline pra diff/rollback; sem manifest o `analyze` não tem fatos;
sem runner de teste não há `verify_cmd`; sem linter o quality gate fica cego).
O preflight move essa descoberta pro início, com um laudo estruturado e
Actionable Fix por achado, em vez de o agente topar com a lacuna no meio do
fluxo.

## As 4 categorias e seus checks

| Categoria | `code` | Condição de não-PASS | Severidade | Actionable Fix |
|---|---|---|---|---|
| **1. Controle de Versão (Git)** | `git_binary` | binário `git` ausente do PATH | FAIL | instalar o git |
| | `git_repo` | `<alvo>/.git` inexistente (nem dir nem gitfile) | FAIL | `git init` |
| | `git_baseline_commit` | HEAD não resolve (0 commits) | WARNING | `git add -A && git commit -m "baseline pré-harness"` |
| | `git_worktree_clean` | `git --no-optional-locks status --porcelain` não-vazio | WARNING | commitar/stashear |
| | `gitignore_present` | `.gitignore` ausente na raiz | WARNING | criar `.gitignore` da stack |
| **2. Manifestos de Projeto** | `manifest_present` | `RepoProfile.languages` vazio | FAIL | criar manifest (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.csproj`) |
| **3. Verificação/TDD** | `test_runner_detected` | `RepoProfile.test_command is None` | FAIL | declarar runner (fix contextual à linguagem) |
| | `test_files_present` | `RepoProfile.test_glob is None` | WARNING | criar teste na convenção detectável, ou mover os existentes pra ela |
| **4. Qualidade Estática/Linting** | `linter_configured` | `RepoProfile.extras["lint_command"]` ausente | WARNING | configurar linter (`[tool.ruff]`, eslint, ...) |

**Duas severidades foram decisão explícita do usuário** (não default de
design): linter ausente = WARNING, e repo git com 0 commits = WARNING — em
ambos os casos, alerta em vez de bloqueio.

### Agregação e veredito

- Status de uma categoria = pior status entre seus checks (`FAIL > WARNING >
  PASS`; categoria sem checks avaliados = `PASS`).
- Veredito global: `NOT_READY` se ≥1 categoria `FAIL`; `READY_WITH_WARNINGS`
  se 0 `FAIL` e ≥1 `WARNING`; `READY` caso contrário.
- Invariante testada: todo check com status ≠ `PASS` tem `fix` não-vazio —
  violar isso é erro de **construção** do laudo (`ValueError` no
  `__post_init__` de `PreflightCheck`), não um resultado válido sobre o
  repo-alvo.

### Curto-circuito da categoria Git

- `git_binary` FAIL (git ausente do PATH) → `git_repo` e `gitignore_present`
  continuam avaliados (não dependem do binário); só os 2 checks de subprocess
  (`git_baseline_commit`, `git_worktree_clean`) são omitidos do laudo.
- `git_repo` FAIL (sem `.git`) → `git_baseline_commit`/`git_worktree_clean`
  são omitidos (não há repo pra medir); `gitignore_present` continua.

## Decisões de arquitetura

1. **Reuso obrigatório do analyzer.** As categorias 2-4 são uma camada de
   **política de severidade** sobre o `RepoProfile` que
   [`analyze_project()`](../src/harness/analyzer.py) já produz — zero
   reimplementação de detecção de manifest/test runner/lint. `analyze_project`
   é chamado **uma única vez** por `run_preflight`, de forma **pura** (nunca
   `write_profile` — o preflight não grava `.harness/repo-profile.json`).
2. **Detector Git é peça nova.** O analyzer ignora `.git` de propósito
   (`_SKIP_DIRS`). Presença de repo é decidida por `(alvo/.git).exists()` —
   cobre tanto o formato diretório quanto o formato **gitfile** (o que
   `git worktree add` gera: um arquivo de texto `gitdir: <path>` em vez de um
   diretório `.git/`) — e **nunca** por `git rev-parse --is-inside-work-tree`:
   um mock de teste criado dentro de outro repositório git não pode passar de
   carona na work tree do repo-pai.
3. **Read-only absoluto, inclusive contra o próprio git.** Os dois checks que
   chamam subprocess usam `git --no-optional-locks -C <alvo> ...`. A flag é
   obrigatória: sem ela, `git status` reescreve `.git/index` como efeito
   colateral do refresh do stat-cache — comprovado empiricamente durante a
   revisão do contrato — o que violaria a garantia read-only mesmo sem
   nenhuma intenção de escrita. `_run_git()` escopa o subprocess ao alvo via
   `-C` internamente (o chamador nunca precisa, nem deve, repetir o `-C`).
4. **Zero dependência nova.** Só stdlib (`shutil`, `subprocess`) + módulos já
   existentes do pacote (`harness.analyzer`).
5. **Saída do CLI é JSON puro** (mesma convenção de `audit`/`analyze`); a
   apresentação humana `[PASS]/[WARNING]/[FAIL]` é responsabilidade da skill,
   não do CLI.

## Contrato do JSON

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
Chaves JSON em inglês, mensagens/fixes em pt-BR — convenção do repo inteiro.

## CLI

```powershell
harness preflight --dir <alvo>
```

- Imprime `report.to_json()` no stdout (`indent=2, ensure_ascii=False`).
- Exit code `0` — `READY` ou `READY_WITH_WARNINGS`.
- Exit code `1` — `NOT_READY`.
- Exit code `2` — erro de uso (`PreflightError`: alvo inexistente ou não é um
  diretório), mensagem em stderr.
- `main()` chama `sys.stdout.reconfigure(encoding="utf-8")` antes de imprimir
  — sem isso, no Windows, stdout redirecionado/piped cai na locale do
  console (tipicamente `cp1252`), corrompendo o JSON `ensure_ascii=False` e
  chegando a crashar com `UnicodeEncodeError` em alvos cujo caminho tem
  caracteres fora do cp1252 (achado por revisão pós-implementação, ver seção
  "Histórico" abaixo).

## Skill

`/harness-creator:preflight` roda o CLI, monta uma tabela por categoria com
`[PASS]/[WARNING]/[FAIL]` + o Actionable Fix de cada não-PASS, e roteia pelo
veredito:

- `READY` / `READY_WITH_WARNINGS` → sugere `/harness-creator:plan` como
  próximo passo.
- `NOT_READY` → oferece aplicar os fixes **um a um**, cada um só com
  confirmação explícita do usuário (a skill nunca aplica fix sozinha, nunca
  em lote), e re-roda o preflight para confirmar que o veredito melhorou.

## Garantia read-only — como é provada

`run_preflight()` nunca escreve no alvo. A prova (AC-5 do contrato) é um teste
de integração real: monta um repositório git de verdade com ≥1 commit (o
único jeito de exercitar o caminho de subprocess, onde mora o risco de
escrita), tira um snapshot `sorted(rglob) + mtime` da árvore **excluindo
apenas `.git/`** antes e depois de rodar o preflight, e afirma que são
idênticos — mais a checagem explícita de que `.harness/` não nasce. `.git/`
fica fora do snapshot porque o próprio `git status` faz refresh de
stat-cache em `.git/index` como comportamento interno dele (mitigado, mas não
contratualmente eliminado, por `--no-optional-locks`); isso não é escrita do
preflight.

## Prova real (dogfooding)

O gate final do contrato (`tests/e2e/test_preflight_e2e.py`) não chama
`run_preflight()` direto em Python — invoca o **comando real do CLI** via
`subprocess.run`, contra dois repositórios montados de verdade em disco:

- **Mock "repo Python cru"**: git + 1 commit, `pyproject.toml` mínimo sem
  runner de teste nem linter, sem `tests/` → `NOT_READY`, exit 1.
- **Mock "repo completo"**: git + commit + `.gitignore` + `pyproject.toml`
  com pytest e `[tool.ruff]` + `tests/test_x.py` → `READY`, exit 0.

Os dois laudos JSON reais (stdout literal do subprocess) ficam colados em
[`tests/e2e/evidence/preflight-dogfood-2026-07-17.md`](../tests/e2e/evidence/preflight-dogfood-2026-07-17.md).

## Histórico do contrato

A feature nasceu de um contrato formal (`spec.md` + `Plans.md` em
`.harness/work/preflight-skill/`), aprovado pelo usuário, implementado em 8
tarefas sequenciais (T-01 a T-08) e passou por **dois** ciclos independentes
de reflect (Claude Opus, effort xhigh) + LLM-as-judge (Claude Fable 5):

1. **Sobre o contrato, antes de codar** — 4 findings reais recuperados de uma
   falha de formatação na primeira tentativa do reflector; o judge aceitou 2
   e modificou 2 (nenhum rejeitado): fixou a flag `--no-optional-locks`, a
   contagem exata de checks de subprocess, a mensagem não-absolutista de
   `test_files_present`, e o escopo por-tarefa da stop condition de falhas
   consecutivas.
2. **Sobre a implementação já concluída** — achou um bug real
   (`UnicodeEncodeError` no stdout do CLI em paths fora do cp1252 no Windows,
   corrigido com `sys.stdout.reconfigure`), um parâmetro morto/armadilha em
   `_run_git` (não escopava o subprocess por si só), e 2 gaps de cobertura
   (ramo FAIL de `git_worktree_clean` sob erro de subprocess; caminho gitfile
   de `git worktree add`). Um quinto achado (fix de `.gitignore` "genérico
   demais") foi **rejeitado** pelo judge — o texto já casava com o exemplo
   não-vinculante do próprio spec.

Suíte final: 437 passed, 10 skipped, zero regressão.
