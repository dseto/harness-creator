# harness-creator

**v0.12.0** · [CHANGELOG](CHANGELOG.md)

Plugin do Claude Code que **cria, avalia e compila** estrutura de harness
(governança de agentes) para projetos.

> **Agente = Modelo + Harness.** O modelo raciocina; o harness garante
> governança. Aqui a governança compila para os mecanismos NATIVOS do Claude
> Code — permissions, hooks PreToolUse e AGENTS.md — e o próprio Claude Code
> enforça. Nada de executor próprio, nada de API key.

## Como funciona

```
.harness/harness.yaml  ──harness compile──►  .claude/settings.json   (permissions + hooks)
      (sua spec)                              .harness/hooks/*.py    (guards PreToolUse)
                                              AGENTS.md              (bloco gerenciado)
```

- **Política de aprovação** (`paranoid` | `balanced` | `auto`) vira regras
  `allow`/`ask` de permissions. Rede (WebFetch/curl/wget) sempre pede aprovação.
- **Disciplina TDD** vira hooks: editar arquivo de teste ou rodar a suíte
  direto dispara confirmação humana na sessão.
- **Orçamento** vira orientação no AGENTS.md (o Claude Code não expõe tokens a
  hooks — dito explicitamente, sem teatro de enforcement).

Uso no dia a dia (instalar → criar harness → trabalhar com os prompts de
aprovação aparecendo sozinhos): ver [GUIDE.md](GUIDE.md).

## Instalação (plugin local)

```powershell
# 1. dependências da biblioteca
pip install -e .

# 2. abrir o Claude Code com o plugin
claude --plugin-dir C:\Projetos\Harness-creator
```

## Skills

| Skill | Faz |
|---|---|
| `/harness-creator:init` | Entrevista curta → gera `.harness/harness.yaml` → compila |
| `/harness-creator:audit` | Score 0-100 + findings (drift, hooks ausentes, política arriscada) |
| `/harness-creator:compile` | Recompila após edição manual do yaml (idempotente, preserva settings manuais) |
| `/harness-creator:plan` | Demanda em linguagem natural → `spec.md` + `Plans.md` → aprovação humana → `feature_list.json` |

CLI equivalente: `harness compile --dir <alvo>` · `harness audit --dir <alvo>` ·
`harness analyze --dir <alvo>` · `harness compile-contract --dir <alvo> --slug <slug>` ·
`harness compile-session --dir <alvo>` (Fase 2 — compila a superfície de
permissions do raio de impacto, o `boundary_guard.py`, o lifecycle de 16
passos, os templates de sessão e o hook SessionStart).

## Estrutura do repo

```
harness-creator/
├── .claude-plugin/plugin.json   # manifesto do plugin
├── skills/                      # init, audit, compile
├── src/harness/
│   ├── compiler.py              # harness.yaml -> governança nativa (coração)
│   ├── audit.py                 # score + findings (dogfooding: compile+diff)
│   ├── config.py                # HarnessConfig (pydantic) — fonte de verdade
│   ├── cli.py                   # harness run|compile|audit
│   └── (orchestrator, sandbox, tools, ...)  # modo execução — CONGELADO
└── tests/                       # 75 testes (sem Docker/API para compile/audit)
```

## Modo execução (congelado)

`src/harness/orchestrator.py` + sandbox Docker + TDD loop são um executor
agêntico completo (6 camadas, ver [ARCHITECTURE.md](ARCHITECTURE.md)). Ficou
**congelado como referência**: exigia `ANTHROPIC_API_KEY` e infraestrutura
própria. O pivot (2026-07) moveu o valor para dentro do Claude Code. A
biblioteca (config, matriz de aprovação, matching de testes) segue viva —
é ela que valida e alimenta o compilador.

## Testes

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -q          # unit + E2E
```

A suíte E2E (`tests/e2e/`) usa uma cópia real da MinimumAPI (.NET) como
cobaia — compile, audit, hooks via stdin, drift e merge, tudo em subprocess
como na vida real. Precisa de `C:\Projetos\MinimumAPI` no disco (ou
`HARNESS_E2E_API_SRC` apontando pra outra API); sem ela os E2E são skipped.
Não precisa de dotnet — os E2E operam só em arquivos.

Headless real (`tests/e2e/test_headless.py`) — invoca o binário `claude -p`
de verdade contra o playground compilado e confere o campo
`permission_denials` do JSON de saída. Custa tokens reais e exige `claude`
autenticado no PATH; **opt-in**, sempre skipped a menos que:

```powershell
$env:HARNESS_E2E_HEADLESS = "1"
python -m pytest tests/e2e/test_headless.py -v
```

Achado que esses testes documentam: `claude -p` sem TTY **nunca trava** numa
ação `ask` — nega sozinho e a sessão termina normal (exit 0). Pra detectar o
bloqueio num script, não dá pra confiar no exit code: tem que checar
`permission_denials` no `--output-format json`.

Playground manual (com dotnet de verdade):

```powershell
python scripts/make_playground.py   # gera C:\Projetos\MinimumAPI-harness
# roteiro de teste: MinimumAPI-harness\HARNESS-TEST-REPORT.md
```
