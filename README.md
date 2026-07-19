# harness-creator

**v0.17.0** · [CHANGELOG](CHANGELOG.md)

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

`--plugin-dir` é uma flag de CLI — não existe no app **desktop** (sem
terminal, sem flag). Para o plugin ficar disponível sem repetir o comando
(inclusive no desktop), registre-o como marketplace local em
`~/.claude/settings.json`: ver [GUIDE.md §10](GUIDE.md#10-deixar-o-plugin-sempre-disponível-opcional).

## Skills

| Skill | Faz |
|---|---|
| `/harness-creator:preflight` | Laudo de prontidão de um repo cru ANTES de instalar o harness: PASS/WARNING/FAIL em 4 categorias (Git, Manifestos, Verificação/TDD, Linting) com Actionable Fix e veredito READY/NOT_READY — read-only |
| `/harness-creator:init` | Entrevista curta → gera `.harness/harness.yaml` → compila |
| `/harness-creator:audit` | Score 0-100 + findings (drift, hooks ausentes, política arriscada) |
| `/harness-creator:compile` | Recompila após edição manual do yaml (idempotente, preserva settings manuais) |
| `/harness-creator:plan` | Demanda em linguagem natural → `spec.md` + `Plans.md` → aprovação humana → `feature_list.json` |
| `/harness-creator:team` | Analisa o domínio → propõe padrão de time (Produtor-Revisor, Supervisor, ...) → **aprovação humana da arquitetura (único toque humano)** → gera agentes/skills/manifesto → `harness audit-team` |

Detalhe completo do preflight (tabela de checks, contrato do JSON, decisões de
arquitetura): [docs/preflight.md](docs/preflight.md).

CLI equivalente: `harness preflight --dir <alvo>` (v0.15 — laudo de prontidão
read-only de um repo cru; JSON no stdout, exit 0/1/2 conforme
READY/NOT_READY/erro-de-uso) · `harness compile --dir <alvo>` ·
`harness audit --dir <alvo>` ·
`harness analyze --dir <alvo>` · `harness compile-contract --dir <alvo> --slug <slug>` ·
`harness compile-session --dir <alvo>` (Fase 2 — compila a superfície de
permissions do raio de impacto, o `boundary_guard.py`, o lifecycle de 16
passos, os templates de sessão e o hook SessionStart) · `harness verify
<feature-id> --dir <alvo>` (Fase 3 — roda o `verify_cmd` real da tarefa e só
grava evidência com prova executável) · `harness audit-runtime --dir <alvo>`
(Fase 3 — audita schema/frescor/invariantes dos artefatos runtime-mutáveis,
distinto do `harness audit`) · `harness team design|generate --dir <alvo>`,
`harness review <feature-id> submit|approve|reject --dir <alvo>`, `harness
supervise --dir <alvo>`, `harness audit-team --dir <alvo>` (Fase 4 — time de
agentes com revisão de qualidade independente embutida; ver seção abaixo).

## Fase 4 — Team-Architecture Factory (Nível L3)

Depois do contrato aprovado (`/harness-creator:plan`) e da sessão autônoma
compilada (Fase 2/3), o `/harness-creator:team` monta um **time de agentes**
para trabalhar o contrato, com revisão de qualidade independente já embutida
— o único toque humano é aprovar a arquitetura do time, uma vez por projeto:

- **Catálogo de 6 padrões** (`teams/patterns/*.yaml`, conteúdo do plugin):
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
├── .claude-plugin/plugin.json   # manifesto do plugin
├── skills/                      # init, audit, compile
├── src/harness/
│   ├── compiler.py              # harness.yaml -> governança nativa (coração)
│   ├── audit.py                 # score + findings (dogfooding: compile+diff)
│   ├── config.py                # HarnessConfig (pydantic) — fonte de verdade
│   └── cli.py                   # harness compile|audit
└── tests/                       # 414+ testes (sem Docker/API para compile/audit)
```

## Testes

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -q          # unit + E2E
```

A suíte E2E (`tests/e2e/`) roda inteira sobre repos sintéticos criados em
`tmp_path` (Node, Python, YAML) — compile, audit, hooks via stdin, drift e
merge, tudo em subprocess como na vida real, sem depender de nenhum projeto
externo ao plugin.

Achado que a suíte documenta (via `harness.cli` chamado com
`--output-format json`, mesmo padrão usado pelo `claude -p` real): uma ação
negada nunca precisa travar a sessão — o hook responde `deny` e quem chama
decide o que fazer. Pra detectar o bloqueio num script, não dá pra confiar no
exit code isolado: tem que checar o campo estruturado da decisão
(`permissionDecision`/`permission_denials`).
