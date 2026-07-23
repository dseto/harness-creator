# Evidência dogfood — preflight (gate final da demanda)

**Data:** 2026-07-17
**Teste:** `tests/e2e/test_preflight_e2e.py::test_preflight_e2e_dogfood`

Prova REAL exigida pelo ROADMAP: dois repositórios git de verdade criados em
disco (num `tmp_path` efêmero gerado pelo próprio teste) e avaliados pelo
COMANDO REAL do CLI via `subprocess.run` — o mesmo caminho que a skill
`/harness-creator:preflight` percorre. Os blocos JSON abaixo são o laudo real
de cada subprocess, com o único campo variável por rodada (o path absoluto
efêmero do `tmp_path`) redigido para um placeholder estável — sem isso, o
arquivo versionado sujaria a cada execução da suíte só pelo path, mesmo sem
nenhuma mudança real de comportamento.

Ambiente do subprocess: `PYTHONPATH=C:/Projetos/Harness-creator/src`,
interpretador `C:\Python314\python.exe`.

---

## Mock (a) — repo Python cru, sem runner de teste

`git init` + 1 commit, `pyproject.toml` mínimo (projeto Python válido, mas SEM
declarar `pytest` e SEM `[tool.ruff]`), SEM diretório `tests/`.

O `--dir` abaixo é um mock efêmero gerado pelo teste (path de `tmp_path`,
redigido para `<mock_a_cru>`), NÃO um caminho fixo do repositório:

```
python.exe -m harness.cli preflight --dir <mock_a_cru>
```

Exit code: **1** — veredito **NOT_READY**.

Laudo real (stdout do subprocess):

```json
{
  "verdict": "NOT_READY",
  "target": "<mock_a_cru>",
  "categories": [
    {
      "id": "git",
      "title": "Controle de Versão (Git)",
      "status": "WARNING",
      "checks": [
        {
          "code": "git_binary",
          "status": "PASS",
          "message": "binário git encontrado no PATH",
          "fix": "",
          "evidence": null
        },
        {
          "code": "git_repo",
          "status": "PASS",
          "message": "diretório é um repositório git",
          "fix": "",
          "evidence": ".git"
        },
        {
          "code": "git_baseline_commit",
          "status": "PASS",
          "message": "há ao menos um commit (baseline para diff/rollback)",
          "fix": "",
          "evidence": null
        },
        {
          "code": "git_worktree_clean",
          "status": "PASS",
          "message": "árvore de trabalho limpa",
          "fix": "",
          "evidence": null
        },
        {
          "code": "gitignore_present",
          "status": "WARNING",
          "message": ".gitignore ausente na raiz",
          "fix": "criar um .gitignore para a stack detectada",
          "evidence": null
        }
      ]
    },
    {
      "id": "manifest",
      "title": "Manifestos de Projeto Estruturados",
      "status": "PASS",
      "checks": [
        {
          "code": "manifest_present",
          "status": "PASS",
          "message": "manifest de projeto reconhecido",
          "fix": "",
          "evidence": "pyproject.toml"
        }
      ]
    },
    {
      "id": "tests",
      "title": "Ferramentas de Verificação/TDD",
      "status": "FAIL",
      "checks": [
        {
          "code": "test_runner_detected",
          "status": "FAIL",
          "message": "nenhum runner de testes detectado no projeto",
          "fix": "declarar um runner de testes (ex.: pytest em [project.optional-dependencies] no pyproject.toml)",
          "evidence": null
        },
        {
          "code": "test_files_present",
          "status": "WARNING",
          "message": "convenção de testes reconhecida pelo analyzer não observada em disco (ex.: tests/**/*.py para Python) — podem existir testes fora dela (ex.: test_*.py na raiz) não reconhecidos por esta convenção fixa",
          "fix": "criar o primeiro teste na convenção detectável pelo analyzer (ex.: tests/**/*.py para Python) ou mover os testes existentes para ela",
          "evidence": null
        }
      ]
    },
    {
      "id": "lint",
      "title": "Qualidade Estática/Linting",
      "status": "WARNING",
      "checks": [
        {
          "code": "linter_configured",
          "status": "WARNING",
          "message": "nenhum linter configurado para a stack detectada",
          "fix": "configurar linter da stack (ex.: [tool.ruff] no pyproject.toml, config do eslint)",
          "evidence": null
        }
      ]
    }
  ]
}
```

## Mock (b) — repo completo

`git init` + 1 commit, `.gitignore`, `pyproject.toml` com `pytest` em
`[project.optional-dependencies]` e `[tool.ruff]`, `tests/test_x.py`.

```
python.exe -m harness.cli preflight --dir <mock_b_completo>
```

Exit code: **0** — veredito **READY**.

Laudo real (stdout do subprocess):

```json
{
  "verdict": "READY",
  "target": "<mock_b_completo>",
  "categories": [
    {
      "id": "git",
      "title": "Controle de Versão (Git)",
      "status": "PASS",
      "checks": [
        {
          "code": "git_binary",
          "status": "PASS",
          "message": "binário git encontrado no PATH",
          "fix": "",
          "evidence": null
        },
        {
          "code": "git_repo",
          "status": "PASS",
          "message": "diretório é um repositório git",
          "fix": "",
          "evidence": ".git"
        },
        {
          "code": "git_baseline_commit",
          "status": "PASS",
          "message": "há ao menos um commit (baseline para diff/rollback)",
          "fix": "",
          "evidence": null
        },
        {
          "code": "git_worktree_clean",
          "status": "PASS",
          "message": "árvore de trabalho limpa",
          "fix": "",
          "evidence": null
        },
        {
          "code": "gitignore_present",
          "status": "PASS",
          "message": ".gitignore presente na raiz",
          "fix": "",
          "evidence": ".gitignore"
        }
      ]
    },
    {
      "id": "manifest",
      "title": "Manifestos de Projeto Estruturados",
      "status": "PASS",
      "checks": [
        {
          "code": "manifest_present",
          "status": "PASS",
          "message": "manifest de projeto reconhecido",
          "fix": "",
          "evidence": "pyproject.toml"
        }
      ]
    },
    {
      "id": "tests",
      "title": "Ferramentas de Verificação/TDD",
      "status": "PASS",
      "checks": [
        {
          "code": "test_runner_detected",
          "status": "PASS",
          "message": "runner de testes detectado",
          "fix": "",
          "evidence": "pyproject.toml"
        },
        {
          "code": "test_files_present",
          "status": "PASS",
          "message": "arquivos de teste observados na convenção reconhecida",
          "fix": "",
          "evidence": "tests/test_x.py"
        }
      ]
    },
    {
      "id": "lint",
      "title": "Qualidade Estática/Linting",
      "status": "PASS",
      "checks": [
        {
          "code": "linter_configured",
          "status": "PASS",
          "message": "linter configurado",
          "fix": "",
          "evidence": "pyproject.toml"
        }
      ]
    }
  ]
}
```

---

## Interpretação

O **mock (a)** recebe veredito **NOT_READY** porque falta o runner de teste: o
analyzer não encontra `pytest` (nem qualquer runner) declarado no
`pyproject.toml`, então `test_runner_detected` é **FAIL** — um requisito
bloqueante do ciclo Plan→Work→Review, já que sem runner não há `verify_cmd`. O
laudo ainda acompanha fixes acionáveis nas categorias `tests` (declarar pytest)
e `lint` (configurar `[tool.ruff]`), provando que o veredito negativo vem com
próximos passos concretos, não só um "não".

O **mock (b)** recebe veredito **READY** (exit 0): git com baseline, manifest
reconhecido, runner de teste detectado e linter configurado — as quatro
categorias em PASS. O repositório tem o mínimo para o harness operar.
