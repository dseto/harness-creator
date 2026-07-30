# harness-creator

**v0.28.0** · [CHANGELOG](docs/reference/CHANGELOG.md) · [Arquitetura visual (HTML interativo)](docs/plugin/arquitetura-visual.html)

Plugin do Claude Code que **cria, avalia e compila** estrutura de harness
(governança de agentes) para projetos.

> **Agente = Modelo + Harness.** O modelo raciocina; o harness garante
> governança. Aqui a governança compila para os mecanismos NATIVOS do Claude
> Code — permissions, hooks PreToolUse e AGENTS.md — e o próprio Claude Code
> enforça. Nada de executor próprio, nada de API key.

## Como funciona

```
.harness/harness.yaml  ──harness compile──►  .claude/settings.local.json  (permissions + hooks)
      (sua spec)                              .harness/hooks/*.py    (guards PreToolUse)
                                              AGENTS.md              (bloco gerenciado)
```

- **Política de aprovação** (`paranoid` | `balanced` | `auto`) vira regras
  `allow`/`ask` de permissions. Rede (WebFetch/curl/wget) sempre pede aprovação.
- **Disciplina TDD** vira hooks: editar arquivo de teste ou rodar a suíte
  direto dispara confirmação humana na sessão.
- **Orçamento** vira orientação no AGENTS.md (o Claude Code não expõe tokens a
  hooks — dito explicitamente, sem teatro de enforcement).

O ciclo de uma demanda tem **dois portões read-only antes de qualquer
escrita** — um sobre o repositório, outro sobre a demanda:

```
repositório ──preflight──► READY?          ← o repo tem o mínimo para o ciclo?
demanda     ──assess────► laudo (4 fontes) ← ela pertence a este projeto?
                            │                 já foi feita? contradiz algo?
                            ▼
                          plan ──► contrato ──► GATE HUMANO ──► sessão autônoma
```

`assess` avalia a demanda contra código, documentação, histórico do git e
contratos anteriores. Só `FORA_DE_ESCOPO` barra; `PRECISA_ESCLARECER` e
`CONFLITANTE` seguem como warning, porque são demandas legítimas com trabalho
pendente — quem decide se vale a pena é o humano, no gate do `plan`.

Uso no dia a dia (instalar → criar harness → trabalhar com os prompts de
aprovação aparecendo sozinhos): ver [GUIDE.md](docs/plugin/GUIDE.md).

## Instalação (plugin local)

```powershell
# 1. dependências da biblioteca
pip install -e .

# 2. abrir o Claude Code com o plugin
claude --plugin-dir C:\Projetos\Harness-creator
```

`--plugin-dir` é uma flag de CLI — não existe no app **desktop** (sem
terminal, sem flag). Para o plugin ficar disponível sem repetir o comando
(inclusive no desktop), registre-o como marketplace local em
`~/.claude/settings.json`: ver [GUIDE.md §12](docs/plugin/GUIDE.md#12-deixar-o-plugin-sempre-disponível-opcional).

## Instalação (GitHub)

```bash
# Instalar do repositório
pip install git+https://github.com/dseto/harness-creator

# Localizar o path da instalação
python -c "from pathlib import Path; import harness; print(Path(harness.__file__).parent)"

# Abrir Claude Code com o plugin
claude --plugin-dir <path-acima>
```

Ou registre em `~/.claude/settings.json` como marketplace local (path do `pip show harness-creator | grep Location`).

## Atualizando

O harness-creator chega ao usuário por 3 camadas independentes, cada uma
com ciclo de atualização próprio — atualizar só uma e esquecer as outras é
a causa mais comum de "atualizei e continua com comportamento antigo":

```bash
# 1. pacote Python (lib + CLI `harness`)
pip install --upgrade harness-creator            # ou: pip install -e . (checkout local)

# 2. artefatos compilados no repo-alvo (hooks, permissions, AGENTS.md)
harness compile --dir <repo-alvo>

# 3. plugin instalado no Claude Code (skills, comandos) — reiniciar a sessão depois
claude plugin update harness-creator@<marketplace>

# 4. confirma que as 3 camadas batem — aponta exatamente o que ficou pra trás
harness doctor --dir <repo-alvo>
```

`harness doctor` compara a versão do pacote pip instalado, a versão gravada
no último `harness compile` (`.harness/compiled-state.json`) e a versão no
cache de plugin do Claude Code (`~/.claude/plugins/installed_plugins.json`);
exit code 0 se tudo bate, 1 se alguma camada ficou atrasada — com o comando
exato para corrigir.

## Skills

| Skill | Faz |
|---|---|
| `/harness-creator:preflight` | Laudo de prontidão de um repo cru ANTES de instalar o harness: PASS/WARNING/FAIL em 4 categorias (Git, Manifestos, Verificação/TDD, Linting) com Actionable Fix e veredito READY/NOT_READY — read-only |
| `/harness-creator:init` | Entrevista curta → gera `.harness/harness.yaml` → compila |
| `/harness-creator:assess` | Laudo de aderência de uma **demanda** contra documentação, código, git e contratos anteriores: COERENTE / PRECISA_ESCLARECER / CONFLITANTE / FORA_DE_ESCOPO — read-only, antes do `plan` |
| `/harness-creator:audit` | Score 0-100 + findings (drift, hooks ausentes, política arriscada) |
| `/harness-creator:compile` | Recompila após edição manual do yaml (idempotente, preserva settings manuais) |
| `/harness-creator:plan` | Demanda em linguagem natural → `spec.md` + `Plans.md` → aprovação humana → `feature_list.json` |
| `/harness-creator:team` | Analisa o domínio → propõe padrão de time (Produtor-Revisor, Supervisor, ...) → **aprovação humana da arquitetura (único toque humano)** → gera agentes/skills/manifesto → `harness audit-team` |

Detalhe completo do preflight (tabela de checks, contrato do JSON, decisões de
arquitetura): [docs/preflight.md](docs/preflight.md).

## CLI — os 19 subcomandos

Todos aceitam `--dir <alvo>` (default `.`) e só operam sobre um diretório que
já existe: um `--dir` com erro de digitação sai com código 2 sem escrever nada.

### Ciclo da demanda

| Comando | Faz |
|---|---|
| `harness preflight` | Laudo de prontidão de um repo cru, read-only. Exit 0 READY/READY_WITH_WARNINGS, 1 NOT_READY, 2 erro de uso |
| `harness analyze` | Detecta linguagem, package manager, comando e glob de teste → `.harness/repo-profile.json`, cada achado com evidência |
| `harness compile` | `.harness/harness.yaml` → permissions + hooks de TDD + bloco do `AGENTS.md`. Idempotente, merge não-destrutivo |
| `harness compile-contract --slug <slug>` | `spec.md` + `Plans.md` → `.harness/feature_list.json`. **Sem `approved_by`/`approved_at`, não escreve um byte** |
| `harness compile-session` | Fase 2 — branch `contract/<slug>`, permissions enumeradas do raio de impacto, `boundary_guard.py`, lifecycle de 17 passos, templates e os hooks SessionStart/Stop |
| `harness verify <id>` | Fase 3 — roda o `verify_cmd` real e grava `.harness/evidence/<contrato>/<id>.json`. Marca `passes:true` por padrão desde a v0.23.0 |
| `harness supervise` | Devolve a próxima feature pronta respeitando `depends[]`. Leitura síncrona, não daemon |
| `harness finish` | Encerra a demanda: audita o fecho e, só se aprovado, varre os descartáveis do `.harness/`. **Nunca toca git** |

### Ajustes sem reabrir o gate de aprovação

| Comando | Faz |
|---|---|
| `harness task add-file <id> <path> --slug <slug>` | Append no `files[]` de UMA tarefa do `Plans.md` + recompila o contrato |
| `harness profile set <chave> <valor>` | Corrige uma chave de **ambiente** do perfil (`package_manager`, `test_command`, `lint_command`, `typecheck_command`, `build_command`). Comando seu, no seu terminal — não do agente |

### Time de agentes (Fase 4)

| Comando | Faz |
|---|---|
| `harness team design --description "..."` | Dry-run: analisa o domínio e recomenda um padrão do catálogo, com justificativa |
| `harness team generate --pattern <nome>` | Gera `.claude/agents/`, `.claude/skills/`, bloco de time e manifesto — só após aprovação da arquitetura |
| `harness review <id> submit\|approve\|reject` | Transições do state machine do revisor |

### Diagnóstico e controle

| Comando | Faz |
|---|---|
| `harness audit` | Score 0-100 + findings dos artefatos **compilados** (diff byte-exato contra o que o yaml geraria) |
| `harness audit-runtime` | Schema, frescor e invariantes dos artefatos **mutáveis** (`feature_list.json`, `evidence/`, `progress.md`) |
| `harness audit-team` | Papel órfão, papel sem agente, ferramenta além do mínimo do catálogo, drift do bloco de time |
| `harness doctor` | Compara pip / `.harness/` compilado / cache de plugin do Claude Code, e detecta hook registrado que não roda |
| `harness disable [--note "..."]` | **Kill-switch**: desativa TODOS os hooks. Rodar só no seu terminal |
| `harness enable` | Reativa o harness |
| `harness status` | Diz se o harness está ativo ou desativado, mais a contagem de ciclos de fricção |

`audit`, `audit-runtime` e `audit-team` saem com código 1 se houver qualquer
finding `critical` (ou score < 60) — servem como gate de CI.

## Kill-switch: quem pode desligar

O estado é o arquivo-sentinela `.harness/harness.disabled` (machine-local).
Presente, todo hook gerado faz no-op no topo do `main()`.

**O agente não pode se auto-desativar.** Enquanto o harness está ativo, o
`boundary_guard` tem uma regra de nível *floor* que nega criar o sentinel
(por `Edit`/`Write`/PowerShell/redirecionamento no Bash) e rodar
`harness disable`. Você, no seu terminal, não passa por hook nenhum — o
comando funciona livremente.

```powershell
harness disable --dir . --note "investigando um deny"
harness status  --dir .    # a ÚNICA fonte de verdade sobre estar ligado ou não
harness enable  --dir .
```

> **Cuidado que custou caro aqui:** um kill-switch ligado é **invisível** na
> sessão. O guard já ficou em no-op por quatro dias sem sinal nenhum, e tudo
> que passou nesse período rodou sem governança. Antes de tratar qualquer
> sessão como evidência de que a governança valeu, rode `harness status`.
> Por isso `harness finish` trata `killswitch_active` como bloqueador de fecho.

## Encerrar a demanda

Depois que `harness supervise` devolve `next: null`, o ciclo tem um fim
explícito:

```powershell
harness finish --dir .
```

Duas metades, nesta ordem e nada além disso:

1. **Auditoria do fecho** — só leitura. Bloqueadores possíveis:
   `killswitch_active` (a demanda rodou sem governança), `no_contract`,
   `feature_not_passed`, `evidence_missing` (marcação à mão),
   `evidence_stale` (o `files_hash` não bate — o código mudou depois da prova)
   e `tree_residue` (tracked sujo fora dos `files[]` do contrato).
2. **Varredura dos descartáveis** — só roda com a auditoria limpa: reescreve o
   `.harness/progress.md` como demanda encerrada e esvazia o
   `.harness/scratch/`.

`.harness/work/`, `.harness/evidence/` e o `feature_list.json` ficam
intactos — são o registro auditável do que foi feito. O comando **não** faz
`git commit`, `git push` nem `gh pr create`: uma ação de rede irreversível
dentro de um subcomando que está na allowlist do agente transformaria o
próprio `finish` num bypass do runtime floor.

## Fase 4 — Team-Architecture Factory (Nível L3)

Depois do contrato aprovado (`/harness-creator:plan`) e da sessão autônoma
compilada (Fase 2/3), o `/harness-creator:team` monta um **time de agentes**
para trabalhar o contrato, com revisão de qualidade independente já embutida
— o único toque humano é aprovar a arquitetura do time, uma vez por projeto:

- **Catálogo de 6 padrões** (`src/harness/teams/patterns/*.yaml`, empacotado no plugin):
  `producer-reviewer` e `supervisor` com schema completo (papéis + `tools`
  mínimas — revisor/supervisor nunca têm `Edit`/`Write`); `pipeline`,
  `expert-pool`, `fan-out-fan-in`, `hierarchical-delegation` declarativos.
  `harness team design` analisa o domínio (`repo-profile.json`) e recomenda
  um padrão com justificativa, sem gravar nada (dry-run); `harness team
  generate` gera os artefatos (`.claude/agents/`, `.claude/skills/`,
  `AGENTS.md`/`.harness/TEAM.md`, `.harness/team/manifest.json`) só depois da
  aprovação explícita da arquitetura.
- **Produtor-Revisor** (`src/harness/review.py`) — state machine `pending →
  in_review → rejected|approved` por feature. Teto duro de iterações
  (`max_review_iterations`, default 3): esgotado, o estado **nunca** vira
  `approved` sozinho — escala ao humano. Aprovar diff que toca `test_glob`
  exige justificativa registrada.
- **Feature-lock estendido** (`boundary_guard.py`) — quando o time declara
  `producer`+`reviewer`, `passes: true` exige evidência fresca **e**
  aprovação do revisor mais recente que a evidência (aprovação obsoleta
  frente a uma evidência regravada depois dela → `deny`). Sem time
  compilado, comportamento idêntico à Fase 3.
- **Supervisor** (`src/harness/supervisor.py`) — `harness supervise` devolve
  a próxima feature pronta, respeitando `depends[]`; `on_feature_verified`
  aciona a submissão para revisão automaticamente após `harness verify`.
- **Audit de time** (`harness audit-team`) — papel órfão, papel sem agente
  gerado, ferramenta além do mínimo do catálogo, drift do bloco gerenciado.

## Estrutura do repo

```
harness-creator/
├── .claude-plugin/
│   ├── plugin.json              # manifesto do plugin
│   └── marketplace.json         # auto-referência p/ instalar como marketplace local
├── AGENTS.md                    # 3 blocos gerenciados + prosa humana
├── skills/                      # preflight, init, plan, compile, audit, team
├── src/harness/                 # 30 módulos, uma responsabilidade cada
│   ├── cli.py                   # dispatch dos 19 subcomandos
│   │
│   │                            # -- base (fonte única de cada verdade) --
│   ├── config.py                # HarnessConfig (pydantic) — schema do yaml
│   ├── governance/approval.py   # matriz de política: o que cada modo gateia
│   ├── patterns.py              # glob -> regex (compiler, analyzer, guards)
│   ├── settings_paths.py        # fronteira machine-local: destino único do settings
│   ├── hook_launcher.py         # comando do hook fail-closed (`|| exit 2`)
│   ├── killswitch.py            # sentinel + snippet embutido em todo hook
│   │
│   │                            # -- compiladores (determinísticos, zero LLM) --
│   ├── compiler.py              # harness.yaml -> governança nativa (coração)
│   ├── contract.py              # spec.md + Plans.md -> feature_list.json
│   ├── analyzer.py              # detecta linguagem/package manager/test command
│   ├── session_permissions.py   # contrato -> superfície ENUMERADA de permissions
│   ├── lifecycle.py             # bloco dos 17 passos + .harness/LIFECYCLE.md
│   ├── templates.py             # .harness/progress.md + init.sh/init.ps1
│   ├── branching.py             # fluxo branch-first: contract/<slug>
│   ├── profile_edit.py          # harness profile set + reconciliação do test_glob
│   ├── install_command.py       # comando de instalação a partir do package manager
│   │
│   │                            # -- enforcement em runtime (hooks gerados) --
│   ├── boundary_guard.py        # dispatcher único: raio de impacto + runtime floor
│   ├── session_start.py         # injeta o estado da sessão anterior
│   ├── stop_hook.py             # avisa (sem bloquear) sobre trabalho não verificado
│   │
│   │                            # -- prova e controle --
│   ├── verify.py                # roda verify_cmd e grava a evidência
│   ├── review.py                # state machine do revisor (teto duro de iterações)
│   ├── supervisor.py            # próxima feature pronta, respeitando depends[]
│   ├── teams.py                 # catálogo de 6 padrões + análise de domínio
│   ├── finish.py                # encerra a demanda: audita o fecho e varre
│   │
│   │                            # -- diagnóstico (read-only) --
│   ├── preflight.py             # laudo de prontidão do repo cru
│   ├── audit.py                 # score + findings (dogfooding: compile+diff)
│   ├── runtime_audit.py         # invariantes dos artefatos mutáveis
│   ├── team_audit.py            # papéis, ferramentas e drift do time
│   ├── doctor.py                # saúde da instalação (3 camadas de versão)
│   └── metrics.py               # contagem de ciclos de fricção
├── .harness/                    # o produto governado por si mesmo:
│   │                            #   work/ + evidence/ versionados;
│   │                            #   hooks/ + compiled-state* machine-local
│   └── .gitignore               # a regra de ignore é do próprio produto
├── docs/plugin/                 # TUTORIAL, GUIDE, ARCHITECTURE, arquitetura-visual.html
├── docs/project/                # ROADMAP, PLAN, laudos e handoffs
└── tests/                       # 724 casos (sem Docker/API para compile/audit)
```

Quem decide o que entra no git é a **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md` — política
canônica, uma frase: *especificação, contrato e prova são versionados; saída
de compilação que carrega dado de máquina é machine-local e regenerada por
`compile`*. O inventário artefato a artefato está em `docs/plugin/TUTORIAL.md`.

## Testes

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -q          # unit + E2E — 724 casos
```

A suíte E2E (`tests/e2e/`) roda inteira sobre repos sintéticos criados em
`tmp_path` (Node, Python, YAML) — compile, audit, hooks via stdin, drift e
merge, tudo em subprocess como na vida real, sem depender de nenhum projeto
externo ao plugin.

**Convenção da suíte (v0.26.0):** um teste = uma REGRA, com tabela de casos
(`Case` + `_expect`), nunca um `def` por caso. A suíte tinha chegado a 1008
casos e caiu para 724 sem perder uma asserção — o que sobrou é o piso
mecânico, não gordura restante.

Achado que a suíte documenta (via `harness.cli` chamado com
`--output-format json`, mesmo padrão usado pelo `claude -p` real): uma ação
negada nunca precisa travar a sessão — o hook responde `deny` e quem chama
decide o que fazer. Pra detectar o bloqueio num script, não dá pra confiar no
exit code isolado: tem que checar o campo estruturado da decisão
(`permissionDecision`/`permission_denials`).
