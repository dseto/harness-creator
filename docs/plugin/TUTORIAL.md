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
.harness/harness.yaml  ──harness compile──►  .claude/settings.local.json  (permissions allow/ask/deny)
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

O essencial, em oito linhas:

| Artefato | O que é | Versionar? |
|---|---|---|
| `.harness/harness.yaml` | A spec de governança — fonte de verdade | **sim** |
| `.harness/work/<slug>/spec.md` + `Plans.md` | O contrato de uma demanda: o quê e o como, aprovados por você | **sim** |
| `.harness/feature_list.json` | As tarefas do contrato, com estado `passes` protegido por lock | **sim** |
| `.harness/evidence/<contrato>/<id>.json` | Prova executável de cada tarefa verificada | **sim** |
| `AGENTS.md` (bloco gerenciado) | Instruções operacionais que toda sessão lê | **sim** |
| `.claude/settings.local.json` | Permissions e hooks compilados que o Claude Code aplica sozinho | não — machine-local |
| `.harness/hooks/*.py` | Guards PreToolUse (disciplina TDD, boundary do contrato) | não — machine-local |
| `.harness/compiled-state*.json` | Registro do que a compilação gerencia, para o merge não-destrutivo | não — machine-local |

E o fluxo de trabalho vira: **você aprova o contrato uma vez, o agente
trabalha sozinho dentro do raio de impacto declarado, e cada "pronto" vem com
prova**.

**Na raiz do seu projeto entra um único arquivo: `AGENTS.md`.** Todo o resto
mora em `.harness/` ou `.claude/`. É deliberado — `AGENTS.md` é convenção que
agentes externos leem da raiz, e `.claude/` é exigência do Claude Code;
nenhum outro artefato tem motivo para disputar espaço com o seu código.

#### Por que metade não vai para o git

O comando de hook compilado leva o **caminho absoluto desta máquina** (o
`cmd.exe` do Windows não expande variável de ambiente nesse ponto). Se esse
arquivo viajasse no git, um clone em outro caminho carregaria um `PreToolUse`
apontando para um diretório que não existe: **o repositório pareceria
governado e nenhum guard rodaria** — falha silenciosa, sem erro visível.

Por isso o harness grava a compilação em `.claude/settings.local.json` (o
arquivo que o Claude Code já trata como pessoal, com precedência sobre o
`settings.json` do time) e escreve ele mesmo as regras de ignore em
`.claude/.gitignore` e `.harness/.gitignore`. O `.gitignore` da raiz do seu
projeto nunca é tocado.

**Consequência prática: depois de clonar o repositório, rode `harness compile`
uma vez** (e `harness compile-session` quando houver contrato ativo) para
gerar a governança na sua máquina. Quem cobra isso é o `harness doctor` (ver
A.6): ele acusa o repositório que tem `harness.yaml` versionado e nenhum
`settings.local.json`, e também o repositório que mudou de lugar no disco
(comando de hook apontando para um caminho que não existe mais).

#### Inventário completo — os 33 artefatos

A regra que decide cada linha é única, e vale para artefato futuro também:
**especificação, contrato e prova são versionados; saída de compilação que
carrega dado de máquina é machine-local e regenerada por `compile`.** A
íntegra da política — incluindo o critério de decisão e os trade-offs
aceitos — é a **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`, que é a
fonte canônica: quando esta tabela e aquela seção divergirem, a seção vence.

| # | Caminho | O que é | Gerado/regenerado por | Versionar? |
|---|---|---|---|---|
| 1 | `.harness/` | Container de tudo que é do harness | qualquer comando | n/a |
| 2 | `.harness/harness.yaml` | A spec de governança, escrita na entrevista do `init` | nunca — é a **entrada** de `compile` | **sim** |
| 3 | `.harness/hooks/` | Container dos guards | `compile` / `compile-session` | não |
| 4 | `.harness/hooks/boundary_guard.py` | Guard do raio de impacto + runtime floor, cobre TODO `Bash`/`Edit`/`Write` num único processo | `harness compile` (via `install_boundary_guard`) e `harness compile-session` | não |
| 5 | `.harness/hooks/session_start.py` | Hook que injeta o estado da sessão anterior | `harness compile-session` | não |
| 6 | `.harness/hooks/stop_hook.py` | Hook de fim de sessão | `harness compile-session` | não |
| 7 | `.harness/compiled-state.json` | Registro do que `compile` gerencia (merge não-destrutivo) | `harness compile` | não — estado de máquina |
| 8 | `.harness/compiled-state-session.json` | Idem, para os hooks de sessão | `harness compile-session` | não — estado de máquina |
| 9 | `.harness/.gitignore` | As regras de ignore do que é machine-local | `compile` / `compile-session` | **sim** — é a própria regra |
| 10 | `.harness/scratch/` | Área de artefato temporário de verificação | `compile` e `compile-session` | não |
| 11 | `.harness/scratch/.gitignore` | Auto-ignora o conteúdo do scratch (`*` + `!.gitignore`) | `compile` e `compile-session` | **sim** |
| 12 | `.harness/repo-profile.json` | Perfil detectado do repo (linguagem, package manager, test command) | `harness analyze` | **sim** |
| 13 | `.harness/work/` | Container dos contratos | skill `plan` | n/a |
| 14 | `.harness/work/<slug>/spec.md` | O contrato: escopo, critérios, o que fica de fora | nunca — autorado e aprovado por você | **sim** |
| 15 | `.harness/work/<slug>/Plans.md` | As tarefas do contrato, uma por seção `## [T-xx]` | nunca (só patch cirúrgico de `harness task`) | **sim** |
| 16 | `.harness/feature_list.json` | As tarefas compiladas, com `passes` protegido por feature-lock | `harness compile-contract` | **sim** |
| 17 | `.harness/evidence/<contrato>/<id>.json` | Prova de execução: contrato, comando, exit code, hash dos arquivos, timestamp — escopada por contrato porque todo contrato tem um `T-01` | `harness verify` | **sim** |
| 18 | `.harness/review/<id>.json` | Estado da revisão produtor-revisor (Fase 4) | `harness review` | **sim** |
| 19 | `.harness/LIFECYCLE.md` | Detalhe dos 17 passos do lifecycle | `harness compile-session` | **sim** |
| 20 | `.harness/TEAM.md` | Detalhe do time de agentes | `harness team generate` | **sim** |
| 21 | `.harness/team/manifest.json` | Papéis, gates e política de revisão do time | `harness team generate` | **sim** |
| 22 | `.harness/harness.disabled` | Sentinela do kill-switch | `harness disable` / `enable` | não — estado de máquina |
| 23 | `.harness/metrics.json` | Contagem de ciclos `disable`/`enable`/`compile-session` — o número que o gate de decisão do backlog de fricção precisa | `disable`, `enable`, `compile-session`; lido por `harness status` | não — conta operações desta máquina |
| 24 | `.harness/progress.md` | Bookkeeping da sessão: o que foi feito, o que quebrou, onde parou | `compile-session` só se ausente ou se o contrato divergiu — **nunca sobrescreve progresso** | **sim** |
| 25 | `.harness/init.sh` | Bootstrap: instala deps + health check, derivado do profile | `compile-session` — **exceto** se você editou o arquivo (some o marcador, o harness preserva) | **sim** |
| 26 | `.harness/init.ps1` | Idem, para PowerShell | idem | **sim** |
| 27 | `.claude/settings.local.json` | Permissions + hooks compilados que o Claude Code aplica | `compile` e `compile-session` | não — **carrega path absoluto desta máquina** |
| 28 | `.claude/.gitignore` | Ignora o `settings.local.json` | `compile` / `compile-session` | **sim** |
| 29 | `.claude/agents/<role>.md` | Definição de um agente do time | `harness team generate` | **sim** |
| 30 | `.claude/skills/<role>/SKILL.md` | Skill de um papel do time | `harness team generate` | **sim** |
| 31 | **`AGENTS.md`** (raiz) | Híbrido: três blocos gerenciados + a sua prosa, que nunca é tocada | `compile` (bloco de governança), `compile-session` (lifecycle), `team generate` (time) | **sim** |

Duas leituras que a tabela costuma surpreender:

- **`harness compile` não gera tudo.** Ele regenera quatro coisas:
  `boundary_guard.py` (via `install_boundary_guard`, chamado logo depois),
  as fatias gerenciadas do `settings.local.json`, o bloco de governança do
  `AGENTS.md` e o `compiled-state.json`. Todo o resto pertence a
  `compile-session`, `compile-contract`, `analyze`, `verify`, `review`,
  `team generate` ou `disable`.
- **O harness nunca toca no `.gitignore` da raiz do seu projeto**, nem cria ou
  edita `CLAUDE.md` (só lê). As regras de ignore que ele precisa ficam nos
  arquivos que ele mesmo é dono: `.harness/.gitignore` e `.claude/.gitignore`.

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
   nunca libera: **escrita** em arquivo de segredo (`.env`, `.pem`, `id_rsa`,
   `*credentials*`), inclusive por redirecionamento (`>`, `>>`, `tee`); rede
   não planejada (`curl`, `wget`); publicação (`npm publish`, `pip upload`,
   `twine upload`, `gh release`) — sempre fora da superfície automática.
   `git push` tem uma exceção estreita: só da branch do contrato ativo
   (`contract/<slug>`) para ela mesma, sem `--force` nem refspec explícito;
   qualquer outra forma segue negada. **Leitura** de segredo não é bloqueada (ler `.env.example` é
   rotina): o guard libera e anexa um aviso à razão, porque o conteúdo entra
   no contexto da sessão.
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
# deve listar 19 subcomandos: compile, audit, audit-runtime, analyze,
#   preflight, compile-contract, task, profile, compile-session, verify,
#   team, review, supervise, audit-team, finish, disable, enable, status,
#   doctor
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
> `~/.claude/settings.json`; ver GUIDE.md seção 12.)

Na sessão, as 7 skills ficam disponíveis:

| Skill | Faz |
|---|---|
| `/harness-creator:preflight` | Laudo de prontidão de um repo cru (READY/NOT_READY) ANTES de instalar o harness — read-only |
| `/harness-creator:init` | Entrevista curta → gera `.harness/harness.yaml` → compila |
| `/harness-creator:assess` | Laudo de aderência de uma **demanda** contra docs, código, git e contratos anteriores (COERENTE/PRECISA_ESCLARECER/CONFLITANTE/FORA_DE_ESCOPO) — read-only, antes do `plan` |
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
garantia read-only, evidência E2E): [docs/preflight.md](../preflight.md).

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

4. Disciplina TDD? (bloquear edição de teste — a execução da suíte nunca é
   gateada)
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

- **`.claude/settings.local.json`** — regras `allow`/`ask` de permissions
  (machine-local, ignorado pelo git: leva o path absoluto desta máquina).
- **`.harness/hooks/boundary_guard.py`** — único hook `PreToolUse`
  (matcher `*`) que cobre `Edit`/`Write`/`Bash`: gateia a ESCRITA do teste,
  não a execução repetida da suíte (rodar `pytest` em RED e GREEN não pede
  aprovação duas vezes). O mecanismo antigo (**`guard_tests.py`**,
  sempre-`ask`) não é mais gerado, e um segundo hook dedicado a `Bash`
  (**`guard_test_runner.py`**, sempre-`allow`) foi aposentado por medir
  ~125ms por chamada sem mudar nenhuma decisão.
- **`AGENTS.md`** — bloco gerenciado com as instruções operacionais.

## A.5 Reabrir a sessão (obrigatório)

**Feche e reabra o Claude Code nesse projeto.** O settings só é lido
na inicialização — a sessão que rodou o `/init` não aplica as regras nela
mesma.

```powershell
# na próxima abertura, o --plugin-dir já não é necessário para TRABALHAR —
# a governança está compilada no próprio projeto:
cd C:\Projetos\projeto-exemplo
claude
```

## A.6 Conferir que está tudo consistente

A qualquer momento (e sempre depois de editar `settings.local.json`/`AGENTS.md` à
mão):

```
/harness-creator:audit
```

Devolve um score 0–100 e findings — em particular **drift** (alguém editou um
artefato compilado à mão e ele divergiu do que o `harness.yaml` geraria) com
sugestão de recompilar.

O `audit` olha o conteúdo dos artefatos. Para a saúde da *instalação* —
divergência de versão entre pip, `.harness/` compilado e cache de plugin do
Claude Code, e os dois casos de compilação ausente descritos acima (clone
novo, repositório movido de lugar) — o comando é:

```bash
harness doctor --dir .
```

Sai com código 0 quando está tudo consistente e 1 com a lista de issues e o
comando exato de correção. Vale rodar depois de todo `pip install --upgrade`,
`claude plugin update` ou `git clone`.

Se você mudar de ideia sobre a política, edite `approval_policy` no
`.harness/harness.yaml` e rode `/harness-creator:compile` (mostra o diff do
`settings.local.json`) — e reabra a sessão de novo.

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

## B.1 `/harness-creator:assess` — a demanda faz sentido aqui?

Abra a sessão no projeto (com `--plugin-dir`, porque vamos usar skills):

```powershell
cd C:\Projetos\projeto-exemplo
claude --plugin-dir C:\Projetos\Harness-creator
```

Antes de formalizar qualquer coisa:

```
/harness-creator:assess
```

Cole a demanda como ela chegou — sem limpar, sem reescrever. A skill avalia
contra as **quatro fontes de verdade** do projeto e devolve um laudo
**read-only** (não escreve um byte, não cria contrato):

| # | Dimensão | Pergunta | Fonte |
|---|---|---|---|
| D1 | Pertinência | A demanda fala deste sistema? Os símbolos existem? | código + docs |
| D2 | Coerência | Contradiz alguma regra ou decisão documentada? | `AGENTS.md` + docs |
| D3 | Precedente | Já foi feita, tentada ou descartada por decisão? | git + `.harness/work/` |
| D4 | Executabilidade | Dá para escrever critério com comando de prova? | perfil + testes |

| Veredito | Sinal | O que fazer |
|---|---|---|
| `COERENTE` | ✅ OK | siga para B.2 |
| `PRECISA_ESCLARECER` | ⚠️ WARNING | **siga** — as perguntas viram `unknowns` do `spec.md` |
| `CONFLITANTE` | ⚠️ WARNING | **siga** — registre a decisão no `spec.md` |
| `FORA_DE_ESCOPO` | ⛔ BLOQUEIA | pare — a demanda não é sobre este repositório |

**Por que este passo existe.** O `plan` do B.2 formaliza o que você descrever e
confia no gate de aprovação que vem no fim dele — nenhum dos dois confere se a
demanda pertence ao projeto. Uma receita de bolo colada por engano como user story **compila**: o
parser aceita `## [T-01] bater as claras`, `files[]` não toca o disco (path
inexistente passa, porque arquivo novo é legítimo) e o único detector
automático (`--dry-run-verify`) é explicitamente ensinado a ser ignorado, já
que tarefa TDD recém-planejada também falha rápido por natureza.

O resultado seria um contrato **bem formatado** sobre um sistema que não
existe — e o formato é justamente o que faz uma demanda errada parecer legítima
na hora de aprovar.

Três coisas que o `assess` nunca faz, por regra:

- **Não reescreve a demanda.** Se está ambígua, o produto é a pergunta. Uma
  versão "consertada" pela skill seria escopo que você não pediu, e você
  aprovaria achando que era o seu.
- **Não afirma sem fonte.** Todo achado cita `arquivo:linha` ou hash de commit;
  impressão sem evidência vira pergunta, não veredito.
- **Não substitui o gate.** `COERENTE` significa "não achei impedimento", nunca
  "deve ser feito".

> **Dica de operação:** peça para rodar em subagente. Cada avaliação consome
> ~64k tokens de leitura para produzir um laudo de ~1.2k — inline, isso tudo
> fica na sua sessão. E um avaliador que acabou de ouvir você descrever a
> demanda com entusiasmo é pior juiz dela que um subagente frio.

## B.2 `/harness-creator:plan` — transformar a demanda em contrato

Com o laudo em mãos (e as perguntas dele respondidas, se houver):

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
> o loop de auto-verificação (seção B.5) lê o disjuntor. Numa seção de corpo
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
  "compiled_at": "2026-07-29T18:00:00+00:00",
  "compiled_with_version": "0.27.0",
  "features": [
    {
      "id": "T-01",
      "desc": "validar limit com Query(ge/le)",
      "files": ["backend/main.py", "tests/test_leaderboard.py"],
      "verify_cmd": "python -m pytest tests/ -v",
      "depends": [],
      "cwd": null,
      "passes": false
    }
  ]
}
```

## B.3 `harness compile-session` — compilar o raio de impacto

```powershell
harness compile-session --dir .
```

**Antes de qualquer coisa, dois efeitos que este comando tem sobre o seu git —
e que nenhum outro comando do harness tem:**

- **Ele exige a working tree limpa.** Com arquivo modificado ou staged, ele
  aborta com exit 1 sem escrever nada: `erro: working tree suja (tracked
  modificado/staged) — commit ou stash antes de compilar a sessão`. Commite
  ou dê stash primeiro.
- **Ele cria e troca para a branch `contract/<slug>`** (`git switch -c`).
  Cada contrato ganha a própria branch, e é por isso que a árvore precisa
  estar limpa: criar a branch com sujeira misturaria trabalho de outro
  contexto. Se você não quer esse comportamento, desligue com
  `governance.branch_per_contract: false` no `.harness/harness.yaml`.

> **Depois de reinstalar o harness do zero, a ordem importa.** A reinstalação
> necessariamente suja a árvore (apaga artefatos antigos, reescreve o bloco do
> `AGENTS.md`, regrava o `repo-profile.json`), e `.harness/LIFECYCLE.md` e
> `.harness/feature_list.json` são versionados mas **não** são regenerados por
> `harness compile` — quem os gera é `compile-session` e `compile-contract`.
> Sem commitar antes, você fica num estado que não destrava sozinho. A ordem
> que funciona: `analyze` → `compile` → **commit** → `compile-contract` →
> `compile-session`.

Isso pega o contrato aprovado e compila a **sessão autônoma**:

- **Permissions enumeradas** — `allow` para exatamente: `Edit`/`Write` nos
  `files[]` das tarefas (`backend/main.py`, `tests/test_leaderboard.py`),
  os `verify_cmd`, lint/build do profile, git local do ritual
  (`status/log/diff/add/commit`), e qualquer comando declarado à mão em
  `governance.extra_allowed_commands` do `.harness/harness.yaml` — opcional,
  para comandos permanentes fora do ciclo de teste (ex.: o CLI do próprio
  produto do repo). Cada um sai em duas formas, a exata e a prefixada
  (`Bash(pytest -q)` e `Bash(pytest -q:*)`): sem a segunda, acrescentar um
  argumento ao comando aprovado vira prompt de permissão. Nada genérico,
  nada de wildcard aberto.
- **`boundary_guard.py`** — um único hook PreToolUse que cobre Edit/Write/
  Bash/PowerShell. Decide `allow`/`deny` a partir da superfície do contrato
  ativo:
  - arquivo fora dos `files[]` da tarefa ativa → `deny` com a razão;
  - comando composto não escapa: em `pytest tests/ -v && curl evil.com`,
    **cada segmento** entre `;`/`&&`/`||`/`|` precisa prefixar um comando
    aprovado — o `curl` derruba o comando inteiro;
  - **a FORMA de invocar não precisa ser adivinhada**: `pytest -q`,
    `python -m pytest -q`, `.venv/Scripts/pytest.exe -q` e `uv run pytest -q`
    valem a mesma coisa, porque o guard normaliza as duas pontas antes de
    comparar. Ficam de fora, deliberadamente: `python -c` (executa string
    arbitrária), `uv run --with <pkg>` (instala pacote da rede antes de
    rodar) e prefixo de diretório que não seja de venv (`./scripts/x.sh`);
  - em PowerShell, pipeline com cmdlet read-only passa
    (`pytest -q | Select-Object -First 5`). `ForEach-Object` não — executa
    scriptblock arbitrário —, nem atribuição a `$env:*`;
  - command substitution (`$(...)` ou crase) → `deny` direto;
  - **feature-lock**: editar `feature_list.json` para `passes: true` sem
    evidência fresca → `deny` ("rode harness verify primeiro"). Vale
    inclusive para `replace_all` — o guard simula a transição completa,
    então uma feature sem evidência não pega carona numa edição em massa.
- **Runtime floor** (sempre, inegociável): segredos, `curl`/`wget`,
  `npm publish`/`pip upload`/`twine upload`/`gh release` e `git push` nunca
  entram na superfície liberada.
- **Lifecycle de 17 passos** no `AGENTS.md` — o ritual que toda sessão segue
  (ler AGENTS.md → init → ler progresso → escolher UMA feature → implementar
  → verificar → autocorrigir → registrar evidência → commit retomável →
  working tree limpa).
- **Hook SessionStart** — a próxima sessão nasce sabendo onde parou: resumo
  do progresso, feature ativa, `git log` recente injetados no início.

**Reabra a sessão** para as permissions valerem.

## B.4 Trabalhar — a sessão autônoma no raio de impacto

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

## B.5 `harness verify` — o "pronto" com prova

Implementou? A tarefa **não fecha por alegação**. O agente (ou você) roda:

```powershell
harness verify T-01 --dir .
```

Isso executa o `verify_cmd` **real** da tarefa, no diretório do projeto.
Duas saídas possíveis:

- **Passou (exit 0)** → grava `.harness/evidence/<contrato>/T-01.json` (timestamp,
  comando, hash). Essa evidência é o que destrava marcar `passes: true` no
  `feature_list.json`.
- **Falhou** → nenhuma evidência. O agente diagnostica, corrige e roda de
  novo — **sem envolver você** — até passar ou bater na stop condition do
  spec (N falhas seguidas), caso em que ele para, registra o estado no
  `.harness/progress.md` e devolve com diagnóstico.

**Desde a v0.23.0, marcar é o padrão.** `harness verify` grava `passes:true`
no `feature_list.json` sozinho quando o `verify_cmd` sai com `exit_code == 0`,
e diz isso no stderr:

```
T-01: passes:true gravado em .harness/feature_list.json — tarefa fechada
```

Antes era opt-in via `--mark-passed`, e o efeito colateral aparecia no uso
real: o verify ficava verde, a tarefa continuava `passes:false`, e
`harness supervise` devolvia a mesma tarefa sem nada de onde deduzir o porquê.
A flag `--mark-passed` continua aceita como no-op, por compatibilidade.

Para desligar, use o **opt-out**:

```powershell
harness verify T-01 --dir . --no-mark-passed
```

Serve para fleets com múltiplos agentes escrevendo o mesmo
`feature_list.json` em paralelo — a escrita não tem lock entre processos. Uma
sessão orquestradora sequencial única não precisa disto.

Mais duas flags úteis quando a suíte é lenta:

```powershell
harness verify T-01 --dir . --timeout 1800   # default 600s; suíte legítima mais
                                             # lenta era morta pelo default
harness verify T-01 --dir . --stream         # espelha stdout/stderr em tempo real
```

`--stream` é opt-in de propósito: com streaming sempre ligado, toda a saída da
suíte entraria no contexto do agente a cada verify. Serve para o humano
distinguir suíte lenta de suíte travada.

Se, já implementando, uma tarefa precisar tocar um arquivo que não estava no
`files[]` original (ex.: descobriu que falta o `.scss` de um componente),
`harness task add-file` evita reabrir o `Plans.md` na mão:

```powershell
harness task add-file T-07 frontend/src/app/x/x.scss --dir . --slug <slug>
```

Faz append no `files[]` da tarefa e recompila — não reabre o gate de
aprovação nem toca em `approved_by`/`approved_at`.

> **Nota:** `task add-file` recompila o contrato (`feature_list.json`), mas
> não regenera o `permissions.allow` enumerado do `.claude/settings.local.json`
> (isso é trabalho do `compile-session`) — a lista enumerada fica
> desatualizada até a próxima recompilação de sessão. Isso não abre brecha
> nem bloqueia o path novo: o `boundary_guard.py` (hook `PreToolUse`,
> matcher `"*"`) sempre decide `allow`/`deny` explicitamente para
> `Edit`/`Write`/`Bash` a partir do `feature_list.json` **lido em tempo de
> execução**, a cada tool call — uma decisão explícita de hook sempre
> tem precedência sobre `permissions.allow` (nunca é só consultado como
> fallback). Rode `harness compile-session` de novo só se quiser o
> `settings.local.json` enumerado espelhando o estado atual do contrato (ex.:
> para inspeção humana) — não é necessário para o path novo ser editável.

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

## B.6 `harness finish` — encerrar a demanda

Quando `harness supervise --dir .` devolve `next: null`, todas as tarefas
passaram. O ciclo tem um fim explícito:

```powershell
harness finish --dir .
```

Antes desse comando existir, o ciclo tinha início bem definido e **nenhum
fim**: o repo simplesmente ficava como estava. Na prática isso acumulava sobra
a cada demanda — o `progress.md` descrevendo um contrato de duas versões
atrás, o `scratch/` guardando arquivos de semanas antes, e nenhuma conferência
de que as provas registradas ainda valiam para o código em disco.

São duas metades, nesta ordem e nada além disso.

**1. Auditoria do fecho — só leitura.** Nunca escreve, nunca executa
`verify_cmd`. Os bloqueadores possíveis:

| `kind` | O que significa |
|---|---|
| `killswitch_active` | O harness está desativado — o `boundary_guard` rodou em no-op, então a demanda inteira passou sem governança. Religue e reveja o que passou antes de encerrar |
| `no_contract` | `feature_list.json` ausente ou ilegível — não há contrato a fechar |
| `feature_not_passed` | Alguma feature ainda sem `passes: true` |
| `evidence_missing` | Feature com `passes: true` e nenhum arquivo de evidência — marcação à mão, o que o passo 13 do lifecycle proíbe |
| `evidence_stale` | O `files_hash` da evidência não bate com o conteúdo atual dos `files[]`: **o código mudou depois da prova** |
| `tree_residue` | Tracked sujo fora dos `files[]` do contrato e fora dos artefatos gerenciados pelo harness |

**2. Varredura dos descartáveis — só com a auditoria limpa.** Reescreve o
`.harness/progress.md` como demanda encerrada e esvazia o `.harness/scratch/`
(preservando o `.gitignore` da pasta).

Reprovado, o comando reporta os bloqueadores e sai com código 1 **sem varrer
nada** — limpar por cima de um fecho quebrado apagaria justamente o rastro
necessário para consertá-lo.

O que `finish` deliberadamente **não** faz:

- **`git commit` / `git push` / `gh pr create`.** Uma ação de rede irreversível
  dentro de um subcomando que está na allowlist do agente transformaria o
  próprio `finish` num bypass do runtime floor. É a mesma razão de
  `enable`/`disable` estarem fora da allowlist.
- **Gerar "sugestões de melhoria".** Isso é saída de modelo, não de CLI: aqui
  saem os fatos, e quem redige a mensagem de fecho é o agente.
- **Apagar histórico.** `.harness/work/`, `.harness/evidence/` e o
  `feature_list.json` ficam intactos — são o registro do que foi feito.

Um efeito colateral que importa: o `progress.md` reescrito é o que **destrava o
contrato seguinte**. Sem ele, a sessão nova herdava o estado da demanda
anterior e começava confusa.

## B.7 Kill-switch — desligar tudo (e por que só você pode)

Se o guard atrapalhar de um jeito que os três escapes do GUIDE não resolvem, o
kill-switch desliga **todos** os hooks de uma vez:

```powershell
harness disable --dir . --note "investigando o deny de X"
# ... mexe no que precisa ...
harness enable --dir .
```

O estado é o arquivo `.harness/harness.disabled` (machine-local, gitignored).
Presente, cada hook gerado faz no-op logo no topo.

**O agente não consegue fazer isso.** Enquanto o harness está ativo, o
`boundary_guard` nega, por regra de *floor*, tanto criar o sentinel
(`Edit`/`Write`/PowerShell/redirecionamento no Bash) quanto rodar
`harness disable`. Você, no seu terminal, não passa por hook nenhum — o hook só
existe dentro da sessão do Claude Code.

> **O aviso completo sobre o risco de esquecer o kill-switch ligado** — e por
> que `harness status` é a única fonte de verdade antes de tratar qualquer
> sessão como evidência — está em [GUIDE.md § 11](GUIDE.md).

## B.8 O ciclo completo da demanda, resumido

```
demanda em linguagem natural
        │
        ▼
/harness-creator:preflight   (opcional — o repo está pronto?)
        │
        ▼
/harness-creator:assess ──► laudo da demanda (read-only, 4 fontes)
        │                    ⛔ FORA_DE_ESCOPO barra aqui
        │                    ⚠️ WARNING segue, mas as perguntas/o conflito
        │                       precisam viajar junto para o spec.md
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
harness compile-session ──► branch contract/<slug> + permissions do raio de
        │                    impacto + boundary_guard + lifecycle + hooks
        ▼                    de sessão                       (reabrir sessão)
sessão trabalha sozinha dentro do raio ──► implementa ──► harness verify
        │                                                  (prova executável)
        ▼
evidência gravada ──► passes: true ──► aprovação humana do commit
        │                              (descrição funcional + link file:line)
        ▼
commit em estado retomável ──► harness supervise devolve next: null
        │
        ▼
harness finish ──► audita o fecho + varre descartáveis   ◄── fim da demanda
```

## B.9 (Opcional) Fase 4 — time de agentes com revisão independente

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
| Regras não estão sendo aplicadas | Sessão aberta antes do compile | Feche e reabra o Claude Code — o settings só é lido na inicialização |
| Clone novo sem governança | A compilação é machine-local e não viaja no git | Rode `harness compile` (e `harness compile-session` se houver contrato ativo) |
| `compile-contract` falha com erro de aprovação | `approved_by`/`approved_at` vazios no frontmatter do `spec.md` | Revisar e preencher — é intencional, o gate é você |
| `harness analyze` não detecta Python | Projeto só tem `requirements.txt` | Detecção exige `pyproject.toml` ou `setup.py` — adicione um `pyproject.toml` mínimo |
| Edição em `feature_list.json` negada | Tentativa de `passes: true` sem evidência fresca | Rode `harness verify <id>` primeiro — é o feature-lock funcionando |
| Edição de teste negada | Arquivo de teste não está nos `files[]` da tarefa ativa | Se for legítimo, ajuste o contrato (Plans.md) e recompile; se não, é a proteção anti-enfraquecimento agindo |
| Comando aprovado + `&&` negado | Segmento extra não prefixa comando da superfície | Declare o comando extra em `governance.extra_allowed_commands` (o próprio deny traz o bloco pronto) ou rode separado |
| Score baixo no `/harness-creator:audit` | Drift — artefato compilado editado à mão | Edite o `harness.yaml` (fonte de verdade) e recompile |
| Nada é bloqueado, nem o que deveria | Kill-switch ligado e esquecido — é **invisível** na sessão | `harness status --dir .`; se desativado, `harness enable`. Reveja o que passou nesse período |
| `harness verify` verde mas `supervise` devolve a mesma tarefa | `--no-mark-passed` em uso, ou o verify é anterior à v0.23.0 | Rode sem a flag — marcar virou o padrão. O stderr do verify diz em que estado a tarefa ficou |
| `harness finish` reprova com `evidence_stale` | O código mudou depois da prova — o `files_hash` não bate mais | Rode `harness verify <id>` de novo para regravar a evidência sobre o conteúdo atual |
| `harness finish` reprova com `tree_residue` | Tracked sujo fora dos `files[]` do contrato | Commite ou reverta o que sobrou; artefato temporário devia estar em `.harness/scratch/` |
| `compile-session` aborta com working tree suja | O comando exige árvore limpa para criar a branch do contrato | Commite ou dê stash. Depois de reinstalar do zero, a ordem é `analyze` → `compile` → **commit** → `compile-contract` → `compile-session` |
| Hook aparece como `hook error` no transcript | Interpretador do hook irresolúvel (venv recriado, repo movido) | `harness doctor --dir .` — é a falha mais perigosa, porque a tool call passaria sem gate se não fosse o `\|\| exit 2` |

## Referências

- [README.md](../../README.md) — o que o plugin é, CLI completa, instalação
- [GUIDE.md](GUIDE.md) — referência completa do dia a dia, seção por seção
- [ARCHITECTURE.md](ARCHITECTURE.md) — como o produto é construído por dentro
- [arquitetura-visual.html](arquitetura-visual.html) — a arquitetura em
  diagramas interativos, com simulador da cascata de decisão
- [docs/preflight.md](../preflight.md) — detalhe do portão de entrada
- [CHANGELOG.md](../reference/CHANGELOG.md) — histórico de versões
- `tests/e2e/evidence/` — evidências dos dogfoods reais que provam cada
  mecanismo descrito aqui em sessão `claude -p` de verdade
