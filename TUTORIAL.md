# Tutorial — harness-creator do zero à demanda implementada

Este tutorial mostra, passo a passo e com exemplos reais, como:

1. **Parte A** — instalar o plugin e criar o harness num projeto seu;
2. **Parte B** — usar o Claude Code num repositório que já tem o harness
   instalado para implementar uma demanda de verdade, do pedido em linguagem
   natural até a evidência executável de que ficou pronto.

Ao longo do texto usamos um projeto de exemplo real: uma API Python/FastAPI
chamada `projeto-exemplo` (backend em `backend/`, frontend estático em
`frontend/`, testes pytest em `tests/`). Qualquer stack serve — .NET, Node,
Go — só mudam os comandos de teste que você informa na entrevista.

---

## O que é, para que serve, o que você ganha

### O que é

O **harness-creator** é um plugin do Claude Code que cria, avalia e compila a
**estrutura de harness** (governança de agentes) de um projeto.

A premissa: **Agente = Modelo + Harness**. O modelo (Claude) raciocina e
escreve código; o **harness** é tudo o que garante que esse trabalho aconteça
dentro de limites verificáveis — o que pode editar, o que pode executar, o
que exige aprovação humana, e como se prova que uma tarefa realmente ficou
pronta.

O diferencial deste plugin é que ele **não inventa um executor próprio**: a
governança compila para os mecanismos **nativos** do Claude Code —

```
.harness/harness.yaml  ──harness compile──►  .claude/settings.json   (permissions allow/ask/deny)
      (sua spec)                              .harness/hooks/*.py    (guards PreToolUse)
                                              AGENTS.md              (instruções gerenciadas)
```

Quem enforça é o próprio Claude Code, na infraestrutura de permissions e
hooks que ele já tem. Nada de API key própria, nada de runtime paralelo.

### O objetivo

Tirar a confiança do lugar errado. Sem harness, "ficou pronto" é uma
alegação do agente — ele diz que testou, diz que só mexeu onde devia, diz que
tudo passa. Com harness:

- **O que ele PODE fazer é declarado antes** (contrato aprovado por você) e
  enforçado mecanicamente (hook nega o que está fora).
- **"Pronto" é prova executável**, não opinião: `harness verify` roda o
  comando de verificação de verdade e só grava evidência se passar.
- **Não dá pra trapacear**: marcar uma tarefa como concluída sem evidência
  fresca é negado pelo hook; editar o teste para ele passar exige aprovação
  humana; contrabandear um comando extra atrás de um comando aprovado
  (`comando_aprovado && qualquer_coisa`) é negado.

### O resultado esperado

Depois deste tutorial, no seu repositório existe:

| Artefato | O que é |
|---|---|
| `.harness/harness.yaml` | A spec de governança — fonte de verdade, versionável |
| `.claude/settings.json` | Permissions compiladas (allow/ask) que o Claude Code aplica sozinho |
| `.harness/hooks/*.py` | Guards PreToolUse (disciplina TDD, boundary do contrato) |
| `AGENTS.md` (bloco gerenciado) | Instruções operacionais que toda sessão lê |
| `.harness/work/<slug>/spec.md` + `Plans.md` | O contrato de uma demanda: o quê e o como, aprovados por você |
| `.harness/feature_list.json` | As tarefas do contrato, com estado `passes` protegido por lock |
| `.harness/evidence/<id>.json` | Prova executável de cada tarefa verificada |

E o fluxo de trabalho vira: **você aprova o contrato uma vez, o agente
trabalha sozinho dentro do raio de impacto declarado, e cada "pronto" vem com
prova**.

### Os ganhos, concretamente

1. **Menos interrupção sem perder controle.** Em vez de aprovar edição por
   edição (dezenas de prompts por demanda), você aprova **um contrato** e as
   permissions da sessão liberam exatamente aquela superfície — nem um
   arquivo a mais, nem um comando a mais.
2. **Anti-alucinação estrutural.** O feature-lock impede `passes: true` sem
   evidência mais nova que o último commit. O agente não consegue "declarar
   vitória" editando a lista de tarefas — ele é obrigado a rodar o
   verificador real primeiro.
3. **Anti-trapaça de teste.** Editar arquivo de teste que não está no escopo
   da tarefa ativa é negado. O caminho "o teste falha, então enfraqueço o
   teste" fica fechado.
4. **Blast radius auditável.** Tudo que a sessão pode tocar está declarado em
   arquivos versionados. `git diff` do `.harness/` mostra exatamente o que
   foi autorizado e quando.
5. **Piso de segurança inegociável.** Com ou sem contrato, o runtime floor
   nunca libera: leitura de segredos (`.env`, `.pem`, `id_rsa`,
   `*credentials*`), rede não planejada (`curl`, `wget`), publicação
   (`npm publish`, `pip upload`, `twine upload`, `gh release`) e `git push`
   sempre ficam fora da superfície automática.
6. **Generaliza entre stacks.** O mesmo pipeline foi provado em dogfood real
   contra uma API C#/.NET e uma API Python/FastAPI (projeto-exemplo) — só
   muda o `test_command` e o `test_glob`.

---

# Parte A — Criar o harness num projeto

## A.1 Instalar o plugin (uma vez por máquina)

```powershell
cd C:\Projetos\Harness-creator
pip install -e .
```

Isso instala a biblioteca e o CLI `harness`. Confira:

```powershell
harness --help
# deve listar: run (modo execução, congelado), preflight, compile, audit,
#              analyze, compile-contract, compile-session, verify,
#              audit-runtime, team, review, supervise, audit-team
```

## A.2 Abrir o Claude Code com o plugin, dentro do projeto-alvo

O harness é criado **no repositório que você quer governar** — não no repo do
plugin. Abra a sessão lá:

```powershell
cd C:\Projetos\projeto-exemplo
claude --plugin-dir C:\Projetos\Harness-creator
```

> `--plugin-dir` é um flag **de sessão** — repita toda vez que abrir o Claude
> Code para usar as skills do plugin. (Dá para tornar permanente via
> `~/.claude/settings.json`; ver GUIDE.md seção 10.)

Na sessão, as 6 skills ficam disponíveis:

| Skill | Faz |
|---|---|
| `/harness-creator:preflight` | Laudo de prontidão de um repo cru (READY/NOT_READY) ANTES de instalar o harness — read-only |
| `/harness-creator:init` | Entrevista curta → gera `.harness/harness.yaml` → compila |
| `/harness-creator:audit` | Score 0-100 + findings (drift, hooks ausentes, política arriscada) |
| `/harness-creator:compile` | Recompila após edição manual do yaml |
| `/harness-creator:plan` | Demanda em linguagem natural → contrato (`spec.md` + `Plans.md`) → aprovação sua → `feature_list.json` |
| `/harness-creator:team` | Propõe padrão de time de agentes → você aprova a arquitetura → gera agentes/skills/manifesto |

## A.3 (passo 0) `/harness-creator:preflight` — o repo está pronto?

Antes de instalar qualquer coisa — e, mais adiante, antes de rodar
`/harness-creator:plan` numa demanda — vale rodar o **preflight**: um laudo de
prontidão do repositório **cru**. É o portão de entrada do ciclo
Plan→Work→Review, e é **100% read-only** (não escreve um byte no repo, nem
`.harness/`).

```
/harness-creator:preflight
```

Ele avalia 4 categorias de pré-requisitos e devolve, para cada uma, um status
`[PASS]` / `[WARNING]` / `[FAIL]` — cada achado não-PASS já vem com um
**Actionable Fix** concreto:

| Categoria | O que checa | Por que importa |
|---|---|---|
| Controle de Versão (Git) | binário `git`, repo iniciado, commit de baseline, working tree limpa, `.gitignore` | sem git não há baseline/diff/rollback — o harness precisa disso para o raio de impacto |
| Manifestos de Projeto | um manifest reconhecível (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.csproj`) | é do manifest que o `analyze` extrai os fatos da stack |
| Verificação/TDD | runner de teste declarado + arquivos de teste na convenção | é o `verify_cmd` que transforma "pronto" em prova executável |
| Qualidade Estática/Linting | linter configurado (`[tool.ruff]`, eslint, ...) | alimenta o quality gate |

**Como interpretar o laudo** (o veredito no topo):

- **`READY`** — 4 categorias PASS. Pode seguir para `/harness-creator:init` (e,
  na hora da demanda, `/harness-creator:plan`) sem ressalvas.
- **`READY_WITH_WARNINGS`** — nenhum FAIL, mas há WARNINGs (ex.: sem
  `.gitignore`, sem linter, sem arquivos de teste ainda). Não bloqueia o fluxo,
  mas vale endereçar antes.
- **`NOT_READY`** — há pelo menos um FAIL bloqueante (ex.: não é repo git, ou
  nenhum manifest reconhecível). A skill oferece aplicar os fixes **um a um,
  só com sua confirmação explícita** (nunca em lote, nunca sozinha), e re-roda
  o preflight para confirmar que o veredito melhorou.

**Quando rodar**: em qualquer repositório ainda não avaliado — tipicamente a
primeira coisa que você faz num projeto novo, antes do `/init`; e, mais tarde,
como cheque rápido antes de abrir uma demanda com `/harness-creator:plan`.
Equivalente no CLI: `harness preflight --dir .` (JSON no stdout; exit `0`
READY/READY_WITH_WARNINGS, `1` NOT_READY, `2` erro de uso).

Detalhe completo (tabela de checks, contrato do JSON, decisões de arquitetura,
garantia read-only, evidência E2E): [docs/preflight.md](docs/preflight.md).

## A.4 Rodar `/harness-creator:init`

Na sessão, digite:

```
/harness-creator:init
```

A skill analisa o projeto e faz uma entrevista curta, já sugerindo defaults
detectados. Para o nosso exemplo FastAPI, uma entrevista típica:

```
1. Política de aprovação?
   → balanced   (recomendado: leitura livre, edição/execução pedem aprovação)
     paranoid   (tudo pede aprovação, até leitura — repositório sensível)
     auto       (edição/execução liberadas; rede e edição de teste continuam gateadas)

2. Comando de teste?
   → python -m pytest tests/ -v

3. Glob dos arquivos de teste?
   → tests/**/*.py

4. Disciplina TDD? (bloquear edição de teste / execução direta da suíte sem aprovação)
   → sim
```

Ao final, a skill escreve `.harness/harness.yaml` — algo assim:

```yaml
governance:
  approval_policy: balanced
verification:
  enforce_tdd: true
  test_command: "python -m pytest tests/ -v"
  test_glob: "tests/**/*.py"
```

— e compila. O que aparece no disco:

- **`.claude/settings.json`** — regras `allow`/`ask` de permissions.
- **`.harness/hooks/guard_tests.py`** e **`guard_test_runner.py`** — hooks
  PreToolUse da disciplina TDD.
- **`AGENTS.md`** — bloco gerenciado com as instruções operacionais.

## A.5 Reabrir a sessão (obrigatório)

**Feche e reabra o Claude Code nesse projeto.** O `settings.json` só é lido
na inicialização — a sessão que rodou o `/init` não aplica as regras nela
mesma.

```powershell
# na próxima abertura, o --plugin-dir já não é necessário para TRABALHAR —
# a governança está compilada no próprio projeto:
cd C:\Projetos\projeto-exemplo
claude
```

## A.6 Conferir que está tudo consistente

A qualquer momento (e sempre depois de editar `settings.json`/`AGENTS.md` à
mão):

```
/harness-creator:audit
```

Devolve um score 0–100 e findings — em particular **drift** (alguém editou um
artefato compilado à mão e ele divergiu do que o `harness.yaml` geraria) com
sugestão de recompilar.

Se você mudar de ideia sobre a política, edite `approval_policy` no
`.harness/harness.yaml` e rode `/harness-creator:compile` (mostra o diff do
`settings.json`) — e reabra a sessão de novo.

### O que já muda no dia a dia, mesmo sem contrato

Depois da Parte A, qualquer sessão normal do Claude Code nesse projeto já
opera sob a política. Com `balanced`:

| Você pede | O que acontece |
|---|---|
| Ler/buscar código | Roda direto, sem prompt |
| Editar `backend/main.py` | Prompt de aprovação (`ask`) |
| Editar `tests/test_basic.py` | Prompt **com motivo específico**: "edição de teste exige aprovação humana — regra TDD" |
| Rodar `pytest` direto | Prompt com motivo TDD (incentiva red-green supervisionado) |
| `curl`/`WebFetch` | Prompt **sempre**, em qualquer política |

Isso é útil, mas ainda é o modo "aprovar cada passo". O ganho grande vem na
Parte B: **trabalhar por contrato**.

---

# Parte B — Implementar uma demanda num repo que já tem harness

Cenário: o `projeto-exemplo` já passou pela Parte A. Chega a demanda:

> *"O endpoint `GET /leaderboard` aceita `?limit=` sem validação — `limit=-1`
> vira `LIMIT -1` no SQLite e devolve a tabela inteira. Validar o parâmetro:
> mínimo 1, máximo 100, default 10. Cobrir com teste."*

## B.1 `/harness-creator:plan` — transformar a demanda em contrato

Abra a sessão no projeto (com `--plugin-dir`, porque vamos usar uma skill):

```powershell
cd C:\Projetos\projeto-exemplo
claude --plugin-dir C:\Projetos\Harness-creator
```

```
/harness-creator:plan
```

Descreva a demanda em linguagem natural. A skill lê (ou gera) o
`repo-profile.json` — o retrato do projeto: linguagem, package manager,
comando de teste, comandos de lint/build — faz perguntas mínimas e escreve o
**contrato** em `.harness/work/leaderboard-limit/`:

**`spec.md`** — o **quê** (escopo, critérios executáveis, unknowns, stop
conditions):

```markdown
---
slug: leaderboard-limit
approved_by:
approved_at:
stop_conditions:
  - "3 falhas seguidas da mesma suíte de teste → parar e reportar diagnóstico"
---

# Spec — validar limit do leaderboard

## Escopo
Validar o query param `limit` de `GET /leaderboard` em `backend/main.py`:
inteiro, ge=1, le=100, default 10.

## Critérios de aceitação (executáveis)
- `GET /leaderboard?limit=-1` → HTTP 422
- `GET /leaderboard?limit=101` → HTTP 422
- `GET /leaderboard?limit=5` → 200 com no máximo 5 linhas
- `GET /leaderboard` (sem param) → 200 com no máximo 10 linhas
- Suíte: `python -m pytest tests/ -v` verde

## Fora do escopo
- Outros endpoints; paginação; mudanças no frontend.
```

> As `stop_conditions` ficam no **frontmatter**, não no corpo — é de lá que
> o loop de auto-verificação (seção B.4) lê o disjuntor. Numa seção de corpo
> elas nunca seriam lidas.

**`Plans.md`** — o **como** (tarefas, arquivos afetados, verificador de cada
uma):

```markdown
## [T-01] validar limit com Query(ge/le)
- files: backend/main.py, tests/test_leaderboard.py
- verify: python -m pytest tests/ -v
```

> O ID da tarefa vai **entre colchetes** no cabeçalho (`## [T-01] ...`) e o
> campo de verificação chama-se `verify:`, não `verify_cmd:` — é o que o
> parser do contrato realmente reconhece.

### O papel do humano aqui (o ponto central)

No mundo real, **a IA escreve o rascunho do contrato e você revisa**. Leia o
`spec.md`: os critérios são os que você quer? o escopo é esse mesmo? Peça
ajustes até estar certo. Aí aprove — preenchendo o frontmatter:

```yaml
approved_by: daniel
approved_at: 2026-07-16T15:00:00-03:00
```

**A skill nunca aprova sozinha.** Esse preenchimento é um ato explícito seu,
e é o gate duro do pipeline:

```powershell
harness compile-contract --dir . --slug leaderboard-limit
```

- Sem `approved_by`/`approved_at` → **erro, nada é gerado**.
- Com aprovação → gera `.harness/feature_list.json`:

```json
{
  "contract": "leaderboard-limit",
  "compiled_at": "2026-07-16T18:00:00+00:00",
  "compiled_with_version": "0.15.8",
  "features": [
    {
      "id": "T-01",
      "desc": "validar limit com Query(ge/le)",
      "files": ["backend/main.py", "tests/test_leaderboard.py"],
      "verify_cmd": "python -m pytest tests/ -v",
      "depends": [],
      "passes": false
    }
  ]
}
```

## B.2 `harness compile-session` — compilar o raio de impacto

```powershell
harness compile-session --dir .
```

Isso pega o contrato aprovado e compila a **sessão autônoma**:

- **Permissions enumeradas** — `allow` para exatamente: `Edit`/`Write` nos
  `files[]` das tarefas (`backend/main.py`, `tests/test_leaderboard.py`),
  os `verify_cmd`, lint/build do profile, e git local do ritual
  (`status/log/diff/add/commit`). Nada genérico, nada de wildcard.
- **`boundary_guard.py`** — um único hook PreToolUse que cobre Edit/Write/
  Bash. Decide `allow`/`deny` a partir da superfície do contrato ativo:
  - arquivo fora dos `files[]` da tarefa ativa → `deny` com a razão;
  - comando composto não escapa: em `pytest tests/ -v && curl evil.com`,
    **cada segmento** entre `;`/`&&`/`||`/`|` precisa prefixar um comando
    aprovado — o `curl` derruba o comando inteiro;
  - command substitution (`$(...)` ou crase) → `deny` direto;
  - **feature-lock**: editar `feature_list.json` para `passes: true` sem
    evidência fresca → `deny` ("rode harness verify primeiro"). Vale
    inclusive para `replace_all` — o guard simula a transição completa,
    então uma feature sem evidência não pega carona numa edição em massa.
- **Runtime floor** (sempre, inegociável): segredos, `curl`/`wget`,
  `npm publish`/`pip upload`/`twine upload`/`gh release` e `git push` nunca
  entram na superfície liberada.
- **Lifecycle de 16 passos** no `AGENTS.md` — o ritual que toda sessão segue
  (ler AGENTS.md → init → ler progresso → escolher UMA feature → implementar
  → verificar → autocorrigir → registrar evidência → commit retomável →
  working tree limpa).
- **Hook SessionStart** — a próxima sessão nasce sabendo onde parou: resumo
  do progresso, feature ativa, `git log` recente injetados no início.

**Reabra a sessão** para as permissions valerem.

## B.3 Trabalhar — a sessão autônoma no raio de impacto

Agora abra a sessão normal (sem `--plugin-dir`) e peça:

```powershell
cd C:\Projetos\projeto-exemplo
claude
```

> "Implementa a T-01 do contrato ativo."

O que acontece, na prática:

1. O hook SessionStart já injetou o estado: contrato `leaderboard-limit`,
   T-01 pendente.
2. O agente edita `backend/main.py`:

   ```python
   # antes
   @app.get("/leaderboard")
   def leaderboard(limit: int = 10):

   # depois
   from fastapi import Query

   @app.get("/leaderboard")
   def leaderboard(limit: int = Query(10, ge=1, le=100)):
   ```

   → **allow silencioso** (arquivo está nos `files[]` da T-01). Sem prompt.
3. Escreve `tests/test_leaderboard.py` com os 4 casos dos critérios
   → **allow** (também declarado).
4. Roda `python -m pytest tests/ -v` → **allow** (é o `verify_cmd`).
5. Se tentasse qualquer coisa fora — editar `frontend/app.js`, rodar
   `pytest ... && echo pwned > x.txt`, dar `git push` — o `boundary_guard`
   nega e devolve a razão **ao agente**, que se corrige. Você não é
   interrompido; o limite trabalha sozinho.

## B.4 `harness verify` — o "pronto" com prova

Implementou? A tarefa **não fecha por alegação**. O agente (ou você) roda:

```powershell
harness verify T-01 --dir .
```

Isso executa o `verify_cmd` **real** da tarefa, no diretório do projeto.
Duas saídas possíveis:

- **Passou (exit 0)** → grava `.harness/evidence/T-01.json` (timestamp,
  comando, hash). Essa evidência é o que destrava marcar `passes: true` no
  `feature_list.json`.
- **Falhou** → nenhuma evidência. O agente diagnostica, corrige e roda de
  novo — **sem envolver você** — até passar ou bater na stop condition do
  spec (N falhas seguidas), caso em que ele para, registra o estado no
  `claude-progress.md` e devolve com diagnóstico.

O hook **Stop** reforça o ritual: se ao encerrar houver uma feature com
`passes:false`, trabalho não commitado tocando os `files[]` dela e evidência
ausente ou desatualizada, ele **injeta um lembrete** (via `additionalContext`)
apontando para rodar `harness verify <id>` antes de fechar. Ele **não bloqueia**
o encerramento — devolve a razão ao agente para que a próxima ação seja retomar
a verificação ou fazer o handoff.

Auditoria dos artefatos que mudam a cada sessão:

```powershell
harness audit-runtime --dir .
# schema, frescor e invariantes: 1 feature in_progress por vez;
# todo passes:true com evidência válida
```

## B.5 O ciclo completo da demanda, resumido

```
demanda em linguagem natural
        │
        ▼
/harness-creator:plan ──► spec.md + Plans.md   (IA rascunha)
        │
        ▼
VOCÊ revisa e aprova (approved_by/approved_at)   ◄── único gate humano
        │
        ▼
harness compile-contract ──► feature_list.json
        │
        ▼
harness compile-session ──► permissions do raio de impacto + boundary_guard
        │                    + lifecycle + SessionStart      (reabrir sessão)
        ▼
sessão trabalha sozinha dentro do raio ──► implementa ──► harness verify
        │                                                  (prova executável)
        ▼
evidência gravada ──► passes: true destravado ──► commit em estado retomável
```

## B.6 (Opcional) Fase 4 — time de agentes com revisão independente

Para demandas maiores, em vez de uma sessão só:

```
/harness-creator:team
```

1. `harness team design` analisa o domínio e **recomenda um padrão** do
   catálogo (`producer-reviewer`, `supervisor`, `pipeline`, `expert-pool`,
   `fan-out-fan-in`, `hierarchical-delegation`) com justificativa — dry-run,
   nada gravado.
2. Você **aprova a arquitetura** (único toque humano da fase, uma vez por
   projeto).
3. `harness team generate` grava `.claude/agents/`, `.claude/skills/`,
   bloco de time no `AGENTS.md` e `.harness/team/manifest.json`.
4. `harness audit-team` valida (papel órfão, revisor com `Edit`/`Write` —
   nunca deveria —, drift).

Com `producer-reviewer` compilado, o feature-lock **aperta**: `passes: true`
passa a exigir evidência fresca **e** aprovação do revisor mais recente que a
evidência (`harness review T-01 approve --dir . --note "..."`). Rejeição
devolve ao produtor; estourou o teto de iterações (default 3) sem aprovação,
**escala a você** — nunca aprova sozinho. `harness supervise` devolve a
próxima feature pronta respeitando `depends[]`.

---

## Erros comuns

| Sintoma | Causa | Correção |
|---|---|---|
| Regras não estão sendo aplicadas | Sessão aberta antes do compile | Feche e reabra o Claude Code — `settings.json` só é lido na inicialização |
| `compile-contract` falha com erro de aprovação | `approved_by`/`approved_at` vazios no frontmatter do `spec.md` | Revisar e preencher — é intencional, o gate é você |
| `harness analyze` não detecta Python | Projeto só tem `requirements.txt` | Detecção exige `pyproject.toml` ou `setup.py` — adicione um `pyproject.toml` mínimo |
| Edição em `feature_list.json` negada | Tentativa de `passes: true` sem evidência fresca | Rode `harness verify <id>` primeiro — é o feature-lock funcionando |
| Edição de teste negada | Arquivo de teste não está nos `files[]` da tarefa ativa | Se for legítimo, ajuste o contrato (Plans.md) e recompile; se não, é a proteção anti-enfraquecimento agindo |
| Comando aprovado + `&&` negado | Segmento extra não prefixa comando da superfície | Declare o comando extra no contrato ou rode separado com aprovação |
| Score baixo no `/harness-creator:audit` | Drift — artefato compilado editado à mão | Edite o `harness.yaml` (fonte de verdade) e recompile |

## Referências

- [README.md](README.md) — o que o plugin é e como está estruturado
- [GUIDE.md](GUIDE.md) — referência completa do dia a dia, seção por seção
- [CHANGELOG.md](CHANGELOG.md) — histórico de versões
- `tests/e2e/evidence/` — evidências dos dogfoods reais que provam cada
  mecanismo descrito aqui em sessão `claude -p` de verdade
