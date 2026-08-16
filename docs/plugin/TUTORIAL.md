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
  comando de verificação de verdade e só grava evidência se passar. No
  vermelho não sai prova — sai **rastro**: a tentativa vai para
  `.harness/attempts/`, com o erro cru, e é o que o disjuntor conta depois
  (seção B.5b).
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

#### Inventário completo — os 37 artefatos

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
| 6b | `.harness/hooks/statusline.py` | Comando de `statusLine` do Claude Code: uma linha na barra com demanda, progresso, tarefa, tentativa e veredito da última prova | `harness compile-session` — registra a entrada `statusLine` no `settings.local.json`; se você já tinha uma statusline configurada, ela **não** é sobrescrita | não |
| 7 | `.harness/compiled-state.json` | Registro do que `compile` gerencia (merge não-destrutivo) | `harness compile` | não — estado de máquina |
| 8 | `.harness/compiled-state-session.json` | Idem, para os hooks de sessão | `harness compile-session` | não — estado de máquina |
| 9 | `.harness/.gitignore` | As regras de ignore do que é machine-local | `compile` / `compile-session` | **sim** — é a própria regra |
| 10 | `.harness/scratch/` | Área de artefato temporário de verificação | `compile` e `compile-session` | não |
| 11 | `.harness/scratch/.gitignore` | Auto-ignora o conteúdo do scratch (`*` + `!.gitignore`) | `compile` e `compile-session` | **sim** |
| 11b | `.harness/scratch/blind-package.md` | O pacote do verificador cego (camada 3): `desc`, `files[]` e `verify_cmd` de cada tarefa, sem nada do raciocínio de quem implementou | `harness blind package` | não — mora no scratch, que se auto-ignora |
| 12 | `.harness/repo-profile.json` | Perfil detectado do repo (linguagem, package manager, test command) | `harness analyze` | **sim** |
| 13 | `.harness/work/` | Container dos contratos | skill `plan` | n/a |
| 14 | `.harness/work/<slug>/spec.md` | O contrato: escopo, critérios, o que fica de fora | nunca — autorado e aprovado por você | **sim** |
| 15 | `.harness/work/<slug>/Plans.md` | As tarefas do contrato, uma por seção `## [T-xx]` | nunca (só patch cirúrgico de `harness task`) | **sim** |
| 16 | `.harness/feature_list.json` | As tarefas compiladas, com `passes` protegido por feature-lock | `harness compile-contract` | **sim** |
| 17 | `.harness/evidence/<contrato>/<id>.json` | Prova de execução: contrato, comando, exit code, hash dos arquivos, timestamp — escopada por contrato porque todo contrato tem um `T-01` | `harness verify` | **sim** |
| 17b | `.harness/attempts/<contrato>/<id>.jsonl` | Rastro de tentativas: uma linha por passada do `verify_cmd`, verde ou vermelha, com o erro cru e a assinatura da falha. É o que o disjuntor conta | `harness verify` | **sim** |
| 17c | `.harness/blind-review/<contrato>.json` | Veredito da camada 3, preso ao hash do código que julgou. Append — veredito novo não apaga o anterior | `harness blind verdict` | **sim** |
| 18 | `.harness/review/<id>.json` | Estado da revisão produtor-revisor — **Fase 4, dormente** (nenhum projeto tem time compilado; ver B.9) | `harness review` | **sim**, se existir |
| 19 | `.harness/LIFECYCLE.md` | Detalhe dos 17 passos do lifecycle | `harness compile-session` | **sim** |
| 20 | `.harness/TEAM.md` | Detalhe do time de agentes — **Fase 4, dormente** | `harness team generate` | **sim**, se existir |
| 21 | `.harness/team/manifest.json` | Papéis, gates e política de revisão do time — **Fase 4, dormente**; sem este arquivo o veto do revisor no `boundary_guard` é no-op | `harness team generate` | **sim**, se existir |
| 22 | `.harness/harness.disabled` | Sentinela do kill-switch | `harness disable` / `enable` | não — estado de máquina |
| 23 | `.harness/metrics.json` | Contagem de ciclos `disable`/`enable`/`compile-session` — o número que o gate de decisão do backlog de fricção precisa | `disable`, `enable`, `compile-session`; lido por `harness status` | não — conta operações desta máquina |
| 24 | `.harness/progress.md` | Bookkeeping da sessão: o que foi feito, o que quebrou, onde parou. Vida = a demanda (reescrito no fecho) | `compile-session` só se ausente ou se o contrato divergiu — **nunca sobrescreve progresso**; `verify` mantém a região `### Tentativas — <id>` enquanto a fatia está vermelha | **sim** |
| 24b | `.harness/decisions.md` | Spine: por que decidimos assim. Append-only, vida = o projeto | `harness decide` | **sim** |
| 24c | `.harness/lessons.md` | Spine: o que atrapalhou. Append-only, vida = o projeto | `harness lesson` | **sim** |
| 25 | `.harness/init.sh` | Bootstrap: instala deps + health check, derivado do profile | `compile-session` — **exceto** se você editou o arquivo (some o marcador, o harness preserva) | **sim** |
| 26 | `.harness/init.ps1` | Idem, para PowerShell | idem | **sim** |
| 27 | `.claude/settings.local.json` | Permissions + hooks compilados que o Claude Code aplica | `compile` e `compile-session` | não — **carrega path absoluto desta máquina** |
| 28 | `.claude/.gitignore` | Ignora o `settings.local.json` | `compile` / `compile-session` | **sim** |
| 29 | `.claude/agents/<role>.md` | Definição de um agente do time — **Fase 4, dormente** | `harness team generate` | **sim**, se existir |
| 30 | `.claude/skills/<role>/SKILL.md` | Skill de um papel do time — **Fase 4, dormente** | `harness team generate` | **sim**, se existir |
| 31 | **`AGENTS.md`** (raiz) | Híbrido: três blocos gerenciados + a sua prosa, que nunca é tocada | `compile` (bloco de governança), `compile-session` (lifecycle), `team generate` (time) | **sim** |

Duas leituras que a tabela costuma surpreender:

- **`harness compile` não gera tudo.** Ele regenera quatro artefatos de
  governança: `boundary_guard.py` (via `install_boundary_guard`, chamado logo
  depois), as fatias gerenciadas do `settings.local.json`, o bloco de
  governança do `AGENTS.md` e o `compiled-state.json`. Junto vem o andaime
  que **todo** escritor de settings garante por tabela
  (`prepare_managed_settings`): os dois `.gitignore` tool-owned e a pasta
  `.harness/scratch/` com o seu — é por isso que as linhas 9, 10, 11 e 28
  também creditam o `compile`. Todo o resto pertence a `compile-session`,
  `compile-contract`, `analyze`, `verify`, `decide`, `lesson`, `blind`,
  `review`, `team generate` ou `disable`.
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
# deve listar 27 subcomandos: compile, audit, audit-runtime, analyze,
#   preflight, compile-contract, task, profile, compile-session, verify,
#   skips, decide, lesson, blind, health, team, review, supervise, budget,
#   reconcile, audit-team, finish, disable, enable, status, doctor, pr-draft
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
| `/harness-creator:team` | **Dormente.** Propõe padrão de time de agentes → você aprova a arquitetura → gera agentes/skills/manifesto. Existe e é testada, mas nenhum passo do lifecycle a aciona — ver B.9 |

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

**Este passo passou a ser obrigatório para trabalhar por contrato.**
`/harness-creator:plan`, `harness compile-contract` e `harness compile-session`
recusam-se a rodar (exit 1) sem `.harness/harness.yaml` no repositório, com a
mensagem apontando de volta para cá. Antes disso o mesmo cenário só avisava em
stderr e deixava o ciclo seguir sem TDD nem política de aprovação instalados
(v0.30.0) — revertido depois de um incidente real (`.harness/decisions.md`,
D-013). Comandos read-only (`analyze`, `status`, `doctor`, `health`, e o
preflight da seção A.3) continuam funcionando sem este passo.

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

> **Atualizar o harness é um passo só: `pip install --upgrade`.** Os artefatos
> compilados deste projeto se regeneram sozinhos quando ficam atrás do pacote
> instalado — basta rodar qualquer comando `harness` aqui, ou abrir uma sessão
> do Claude Code. Você vê uma linha (`harness: artefatos recompilados 0.33.0 ->
> 0.34.0`) e nada mais muda: a branch em que você está trabalhando não é
> tocada. Para desligar, `HARNESS_AUTO_UPDATE=0` no ambiente. O `doctor` é
> isento de propósito — ele mostra o estado real, não o corrige. Os limites
> completos estão em [GUIDE.md](GUIDE.md#atualização-transparente-dos-artefatos).

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
| Rodar `pytest` direto | Prompt genérico de execução — em `balanced` a classe `execute` inteira (`Bash`) é gateada. **Não** é a regra TDD: ela só age sobre *editar* arquivo de teste |
| `WebFetch`/`WebSearch` | Prompt **sempre**, em qualquer política — `network` está no conjunto sempre-gateado |
| `curl`/`wget` no Bash | **Negado**, não perguntado: o runtime floor do `boundary_guard` roda antes de olhar política ou contrato, e o guard já é instalado pelo próprio `harness compile` |

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

A skill começa pelo **Passo 0**, antes de qualquer entrevista: confere se
`.harness/harness.yaml` existe no repositório-alvo. Se não existir, ela para
e redireciona para `/harness-creator:init` (seção A.4) — sem governança
instalada, o contrato que ela compilaria no fim não seria aplicado por
ninguém. No nosso exemplo a Parte A já rodou o `init`, então este passo
apenas confirma e segue.

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
  - {type: consecutive_verify_failures, n: 3}
  - {type: same_failure_signature, n: 3}
  - "a dependência não existe no ecossistema → parar, não improvisar"
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

> **As `stop_conditions` têm duas formas, e só uma vira teto.** A forma
> **tipada** (`{type: ..., n: ...}`) é compilada para o `feature_list.json` e
> é o que `harness budget` conta (seção B.5b); os tipos aceitos são
> `consecutive_verify_failures` e `same_failure_signature`. A forma em
> **prosa** continua valendo como condição *advisory* — ela cobre o que
> nenhuma contagem pega, tipicamente o sinal de impossibilidade —, mas
> ninguém a conta: um contrato só com prosa **parece** ter disjuntor e não
> tem. Tipo desconhecido não é rebaixado a prosa em silêncio: reprova a
> compilação, de propósito.
>
> As duas ficam no **frontmatter**, nunca numa seção de corpo — de lá nada é
> lido. Na ausência de condição tipada, o teto vem de
> `governance.budget.max_green_iterations` do `.harness/harness.yaml`.

**`Plans.md`** — o **como** (tarefas, arquivos afetados, verificador de cada
uma):

```markdown
## [T-01] validar limit com Query(ge/le)
- files: backend/main.py, tests/test_leaderboard.py
- verify: python -m pytest tests/ -v
```

> O ID da tarefa vai **entre colchetes** no cabeçalho (`## [T-01] ...`) e o
> campo de verificação chama-se `verify:`, não `verify_cmd:` — é o que o
> parser do contrato realmente reconhece. Os bullets aceitos são `files:`,
> `verify:`, `depends:`, `cwd:`, `metric:` e `target:`.

> **`metric:` e `target:` são opt-in, e quase sempre você não quer.** Esse par
> só existe para a tarefa em que as DUAS condições valem: (a) "meio pronto" é
> um número que algum comando imprime — similaridade visual, contagem de erros
> de lint, testes passando numa migração grande; e (b) uma iteração pode
> **piorar** o artefato sem que o `verify_cmd` mude de veredito (segue
> vermelho, só que mais longe do alvo). Falhou qualquer uma das duas, a tarefa
> fica binária como sempre foi — bugfix com teste de regressão não precisa de
> `metric`, fidelidade visual precisa. Quando o par está presente,
> `harness verify` roda o comando de medida logo depois do `verify_cmd`, passe
> ou falhe, e grava o valor na trajetória; isso destrava dois vereditos a mais
> no disjuntor (B.5b). **A métrica guia o loop; quem decide "pronto" continua
> sendo só o `verify_cmd`** — bater o alvo nunca vira `passes`.
>
> ```markdown
> ## [T-04] aproximar o componente do mockup
> - files: frontend/src/app/card.component.scss
> - verify: ng test --include=**/card.component.spec.ts
> - metric: python tools/visual_diff.py card
> - target: ">= 0.85"
> ```

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
  "compiled_at": "2026-08-11T18:00:00+00:00",
  "compiled_with_version": "0.34.0",
  "stop_conditions": {
    "typed": [
      {"type": "consecutive_verify_failures", "n": 3},
      {"type": "same_failure_signature", "n": 3}
    ],
    "advisory": [
      "a dependência não existe no ecossistema → parar, não improvisar"
    ]
  },
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

**Antes de qualquer coisa, um pré-requisito e dois efeitos que este comando
tem sobre o seu git — e que nenhum outro comando do harness tem:**

- **Ele exige `.harness/harness.yaml`.** Sem esse arquivo (repositório que
  nunca rodou `/harness-creator:init`), recusa com o mesmo erro didático da
  seção A.4, checado antes de tocar branch, settings ou hooks — nenhum
  artefato fica gravado num repo recusado.

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
- **Lifecycle de 17 passos** no `AGENTS.md` (detalhe em
  `.harness/LIFECYCLE.md`) — o ritual que toda sessão segue, na ordem: ler
  `AGENTS.md` → `harness health` → ler o progresso → ler o `feature_list.json`
  → `harness reconcile` → escolher UMA feature e colar o placar → planejar
  (e `harness decide` o que não for óbvio) → implementar → rodar o
  `verify_cmd` → no vermelho, obedecer o `harness budget` → registrar a prova
  → atualizar o progresso → marcar a feature → documentar o que quebrou e
  `harness lesson` a fricção → verificação cega + apresentação ao humano →
  commit e push na branch do contrato → working tree limpa.
- **Hook SessionStart** — a próxima sessão nasce sabendo onde parou: veredito
  do `health`, divergências do `reconcile`, resumo do progresso, feature
  ativa, decisões recentes e `git log` injetados no início.

**Reabra a sessão** para as permissions valerem.

## B.4 Trabalhar — a sessão autônoma no raio de impacto

Agora abra a sessão normal (sem `--plugin-dir`) e peça:

```powershell
cd C:\Projetos\projeto-exemplo
claude
```

### A abertura: o ambiente responde? o que está escrito é verdade?

Antes de escolher uma fatia, a sessão faz duas perguntas que não são sobre o
código. **As duas chegam sozinhas** — o hook `SessionStart` injeta o veredito
no início —, e você só as roda à mão quando o aviso não chegou: sessão
retomada, execução fora do Claude Code, hook desinstalado.

```powershell
harness health --dir .      # o ambiente responde?
harness reconcile --dir .   # o que está anotado ainda é verdade?
```

**`harness health`** pergunta, numa passada só, se o executável de cada
`verify_cmd` do contrato resolve, se a governança compilada está viva (hook
com interpretador irresolúvel, `settings.local.json` ausente, `.harness/` de
outra versão) e se a proteção está ligada (kill-switch). **Ele nunca executa o
`verify_cmd`** — um check caro vira opcional na prática, e um check opcional
não pega o modo de falha que ele existe para pegar. Exit 2 é **parada**:
ambiente quebrado é falha de infraestrutura, não se autocorrige, e o loop não
conserta o próprio harness. Sem essa pergunta, ferramenta ausente entra no
loop disfarçada de teste vermelho, e o agente passa a hora seguinte
"consertando" código que está certo.

**`harness reconcile`** é a conferência do fecho trazida para o início: prova
cujo `files_hash` não bate mais com o código (`evidence_stale`), tarefa
marcada como passando sem arquivo de prova (`evidence_missing`), sobra tracked
de outro contexto (`tree_residue`), harness em no-op (`killswitch_active`) — e
uma que só existe na abertura, `progress_contract_mismatch`: o
`.harness/progress.md` descrevendo um contrato diferente do
`feature_list.json`. Essa é a mentira mais cara do lote, porque é o resumo em
que a sessão acabou de acreditar. Só leitura; exit 0 íntegro, 2 divergência,
1 não foi possível checar.

Duas ausências deliberadas: `feature_not_passed` e `no_contract` **não** contam
como divergência de abertura. Tarefa pendente é o estado normal de quem está
começando, e repo sem contrato é bootstrap — um aviso que aparece em toda
sessão é um aviso que ensina a ignorar avisos.

### O trabalho

> "Implementa a T-01 do contrato ativo."

O que acontece, na prática:

1. O hook SessionStart já injetou o estado: `health` verde, `reconcile` sem
   divergência, contrato `leaderboard-limit`, T-01 pendente.
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

Isso executa o `verify_cmd` **real** da tarefa, no diretório do projeto, e
devolve **três** exit codes — não dois:

| Exit | O que aconteceu | O que fazer |
|---|---|---|
| `0` | O `verify_cmd` passou **e** nada acoplado regrediu. Grava `.harness/evidence/<contrato>/T-01.json` (timestamp, comando, hash dos `files[]`) | Seguir. A evidência é o que destrava `passes: true` |
| `2` | **Regressão**: o `verify_cmd` desta tarefa passou, mas uma tarefa já concluída que compartilha arquivo com ela voltou a falhar | Consertar antes de escolher outra fatia — ver "re-prova incremental" abaixo |
| `1` | Erro de execução do próprio comando — a tarefa está vermelha | Ir para B.5b, o caminho do vermelho |

Vermelho **não** gera evidência: prova é só de sucesso, e isso não mudou. O
que o vermelho gera é rastro (B.5b).

**Exit 1 também sai antes do `verify_cmd` sequer rodar** quando há contrato
ativo mas o enforcement não está instalado nesta máquina — hooks ausentes do
settings gerenciado (clone novo/segunda máquina) ou kill-switch ligado. A
mensagem distingue os dois casos do vermelho comum: nomeia o que falta
(`harness compile-session` ou `harness enable`) em vez de apontar para B.5b —
não há `verify_cmd` executado para investigar. `harness supervise` recusa da
mesma forma antes de devolver a próxima fatia. Repositório sem
`.harness/harness.yaml` não entra aqui — é outro gate, na compilação
(A.4/B.3).

#### Re-prova incremental — a fatia 5 não quebra a fatia 2 em silêncio

Verde nesta tarefa não é verde no repositório. Verificar só a fatia que acabou
de ficar pronta é barato porque não olha para trás, e o preço disso é que a
regressão aparece no gate final, quando o diff suspeito já tem o tamanho da
demanda inteira. Por isso, ao fechar uma tarefa, `harness verify` **re-roda o
`verify_cmd` das tarefas já `passes: true` que compartilham algum caminho de
`files[]`** com ela.

- **A interseção declarada, nunca a suíte inteira.** O custo fica proporcional
  ao acoplamento real. Suíte completa a cada volta é o gate final, e dentro do
  loop ela só encarece a ida e a volta.
- **O acoplamento é o que o contrato declara** — `files[]`, não import nem
  histórico do git. Acoplamento não declarado é defeito do contrato, e
  `harness task add-file` é o conserto.
- **Vermelho rebaixa.** A tarefa regredida volta a `passes: false`, com a
  tentativa registrada: reentra na fila do `harness supervise`, conta no
  disjuntor e bloqueia o `harness finish`. Avisar sem rebaixar deixaria o
  contrato alegando pronto o que acabou de falhar. A evidência antiga não é
  apagada — vira `evidence_stale`, que é informação.
- **Falha de ambiente não rebaixa.** Timeout, ou prova barrada pelo runtime
  floor, saem como `SEM VEREDITO` no relatório: aquela prova não foi
  confirmada (proteção que falha em silêncio é indistinguível de proteção que
  passou), mas ninguém é rebaixado. Trate como falha de infraestrutura.
- `--no-reproof` desliga. O que se perde, exatamente, é a detecção de
  regressão entre fatias.

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

## B.5b `harness budget` — o caminho do vermelho

A tarefa falhou. O agente conserta e roda de novo, sem envolver você — mas
**não indefinidamente, e não por julgamento próprio sobre quando desistir**.
Antes, o lifecycle mandava "respeitar as stop conditions", que eram frases
livres no frontmatter, contadas de cabeça pelo agente e esquecidas na sessão
seguinte. Um disjuntor que depende de alguém lembrar de contar não é
disjuntor. Hoje são três peças mecânicas.

**1. O retry automático, antes de qualquer contagem.** Um `verify_cmd` que
falha com sinal reconhecidamente **transiente** (timeout de aplicação, erro de
rede ou conexão) é repetido até 3× pelo próprio `harness verify`, com pausa
curta, sem envolver você e **sem gravar nada enquanto houver tentativa
sobrando** — retry não é correção, é repetição. Se algum passar, a falha nem
chega a existir no rastro.

**2. O rastro.** Toda falha TERMINAL — estrutural de primeira, ou transiente
que esgotou os retries — grava uma linha em
`.harness/attempts/<contrato>/<id>.jsonl`: o erro **cru**, o exit code, a
`failure_signature` (o sha da primeira linha do erro) e a classificação. O
verde grava o marcador que encerra a sequência. **O arquivo nunca é apagado**:
o histórico é o produto, e é o que a próxima sessão lê para não repetir de boa
fé a tentativa 1. Enquanto a fatia está vermelha, o `.harness/progress.md`
ganha a região gerenciada `### Tentativas — <id>`, que some sozinha no verde.

**3. A contagem.** A cada vermelho, rode — é leitura pura, não executa nada:

```powershell
harness budget --feature T-01 --dir .
```

E obedeça o `verdict`:

| Veredito | Quando | O que fazer |
|---|---|---|
| `continue` | ainda há folga | corrigir e re-rodar o `verify_cmd` |
| `stop_same_failure` | a **mesma** assinatura se repetiu até o teto | o errado é a abordagem, não a execução: **mude de estratégia** (e diga qual, e por quê) ou escale. Insistir aqui é queimar budget repetindo o que já não funcionou |
| `stop_iterations` | as falhas desde o último verde estouraram o teto | parar, registrar o estado no `.harness/progress.md`, devolver o controle |
| `stop_transient_exhausted` | o mesmo erro **transiente** esgotou os retries | **vence todos os outros vereditos.** Não é bug de lógica: é falha de ambiente se disfarçando de falha de código. Parar e escalar — nunca "corrigir" um `Connection refused` editando código |
| `stop_worsening` | só com `metric`: as 2 últimas medições pioraram frente ao melhor valor já registrado | retomar do melhor estado, que o veredito nomeia (valor e commit). O harness **não** reverte nada sozinho |
| `stop_plateau` | só com `metric`: 3 medições sem bater um novo recorde (oscilar sem superar o pico cai aqui) | trocar de abordagem ou escalar, com a curva registrada |

Os tetos vêm, nesta ordem: das `stop_conditions` **tipadas** do `spec.md`
ativo; na ausência delas, de `governance.budget.max_green_iterations` do
`.harness/harness.yaml` — que deixou de ser texto de orientação e passou a ter
consumidor. `stop_transient_exhausted` não usa teto nenhum: a primeira vez que
acontece já é a resposta.

> **Em qualquer parada, não redija a escalada à mão.** A saída de
> `harness budget` traz o campo `escalation` já montado com as seis partes que
> o design exige, na ordem que ele exige: o que estava sendo tentado, o que
> foi tentado, o último erro cru, a classificação, o estado da spine e a
> sugestão de próximo passo. É `null` quando o veredito é `continue`, e texto
> pronto para copiar em qualquer outro.

As `stop_conditions` em **prosa** continuam valendo em paralelo, como condição
adicional interpretada por você — elas cobrem o que nenhuma contagem pega,
tipicamente o sinal de impossibilidade ("a dependência não existe", "o
requisito é contraditório"). Parar por uma delas é acerto, não desistência, e
não precisa esperar teto nenhum.

> **Skip não é verde.** Se a suíte da tarefa pula testes, o conjunto conhecido
> de skips é declarado **por você**, uma vez, com
> `harness skips baseline T-01 --dir .`: ele roda o `verify_cmd`, mostra o que
> pulou e grava a lista. `harness verify` nunca escreve esse baseline sozinho
> — um skip novo que aparecesse silenciosamente seria cobertura evaporando sem
> ninguém ver.

## B.5c `harness decide` e `harness lesson` — a spine do projeto

O `progress.md` responde "onde estamos" e morre com a demanda. Faltavam dois
registros com outro ciclo de vida — a vida deles é o **projeto**:

| Arquivo | Responde | Vida | Escrito por |
|---|---|---|---|
| `.harness/progress.md` | onde estamos | a demanda | `verify`/`finish` — reescreve |
| `.harness/decisions.md` | por que decidimos assim | o projeto | `harness decide` — append |
| `.harness/lessons.md` | o que atrapalhou | o projeto | `harness lesson` — append |

Descartou uma alternativa por razão **não óbvia**, ou tomou uma decisão que
restringe as iterações seguintes? Três linhas bastam — não é ADR, e decisão
óbvia não precisa de registro nenhum:

```powershell
harness decide "cache do leaderboard fica fora" `
  --decision "validar limit sem tocar em cache" `
  --why "cache exigiria invalidar por torneio; descartado por escopo, ver spec.md Fora do escopo" --dir .
```

Bateu numa fricção — regra que barrou demais, critério ambíguo, mensagem de
erro que não ajudou, o mesmo erro pela terceira vez? Anote no momento em que
aconteceu, uma linha, sem interromper o trabalho:

```powershell
harness lesson "o deny do guard não disse qual tarefa declara o arquivo" `
  --fix "incluir o T-id na razão do deny" --dir .
```

Três propriedades que explicam o desenho:

- **Append-only é a garantia.** Decisão registrada não é editada nem apagada;
  mudou de ideia, registre outra que a supersede. Um arquivo reescrevível não
  prova que a razão gravada é a razão original — e essa prova é a única coisa
  que ele tem a oferecer.
- **Escrever é comando, não edição.** O `boundary_guard` barra escrita em
  `.harness/**` (plano de controle não se auto-amplia): ou existe verbo, ou
  estes arquivos nunca são escritos. O verbo ainda numera e data sem colisão.
- **As decisões chegam sozinhas; as lições não.** O `SessionStart` injeta as
  decisões recentes, com o porquê junto — a hora de saber o que não re-tentar é
  ao escolher a próxima fatia. As lições ficam fora de propósito: não bloqueiam
  retomada, e aparecem no `harness finish` (campo `open_lessons`) para o
  humano. **O agente anota; o agente não aplica** — auto-modificação do harness
  pelo próprio agente é a camada mais perigosa do design.

## B.5d `harness blind` — o olho que não implementou

O `verify_cmd` prova que o teste passa. O teste foi escrito pela mesma cabeça
que escreveu o código, e nenhuma das duas coisas pergunta se o que foi
entregue é o que a demanda prometia. Antes de fechar, a entrega é olhada por
quem não a produziu — e isto **não é opcional**: sem veredito, o
`harness finish` bloqueia.

```powershell
harness blind package --dir .
# monta .harness/scratch/blind-package.md
```

Despache **esse arquivo, como está**, para um subagente novo — um verificador
com contexto limpo. NÃO resuma a conversa, NÃO explique o que você fez, NÃO
mande `spec.md`, `progress.md`, `decisions.md`, `lessons.md` nem o `git log`:
são o raciocínio de quem implementou, e o verificador que os lê valida as
mesmas suposições que produziram o erro. O pacote é montado **por código** — a
partir do `feature_list.json`, que já é a projeção limpa do contrato: `desc`
(o que foi prometido), `files[]` (onde olhar), `verify_cmd` (qual era a prova)
— exatamente para você não precisar redigir esse prompt.

O veredito volta assim:

```powershell
harness blind verdict --pass --evidence "conferi backend/main.py:87 contra o critério de T-01" --dir .
harness blind verdict --fail --evidence "T-01 não cobre limit=0" --dir .
```

- `--evidence` é obrigatório e pede **o quê e ONDE** (`arquivo:linha`).
  Veredito sem evidência gera re-tentativa cega.
- **Exit 2 é reprovação** — resultado legítimo do passo, não erro de execução.
  Gate que só sabe aprovar não é gate.
- **O verificador não conserta.** O veredito volta ao loop, que decide; quem
  corrige é quem implementa, e depois disso um veredito novo é registrado.
- **Veredito novo não apaga o anterior** (append, como as decisões):
  reprovação que some é reprovação que se re-litiga.
- **O veredito prende o hash do que julgou.** Código mudou depois → o fecho
  cobra outro. Sem isso, um "aprovado" de vinte commits atrás fecharia a
  demanda de hoje.

> **Limite declarado:** o harness não prova que o subagente recebeu SÓ o
> pacote. Ele garante que o pacote existe em disco, foi derivado por código, e
> que o veredito está preso ao estado que julgou. A disciplina do despacho é
> sua. Mecanismo onde dá, prosa onde não dá.

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
| `blind_review_missing` | Nenhum veredito da camada 3 — só quem implementou olhou a entrega. Rode `harness blind package`, despache, registre o veredito (B.5d) |
| `blind_review_stale` | O veredito independente é anterior ao código atual: os `files[]` mudaram depois do julgamento, então ele não fala mais desta entrega |
| `blind_review_failed` | O verificador independente **reprovou**. Corrija o que o veredito aponta e registre um novo — o verificador não conserta, e a demanda não fecha reprovada |

Os três últimos são estados diferentes de propósito, e cada um manda fazer
coisa diferente: confundir "ninguém julgou" com "julgaram e reprovaram" faz o
loop consertar o que ninguém chegou a olhar.

Além dos bloqueadores, o relatório traz `open_lessons` — as fricções que o
agente anotou com `harness lesson` e ninguém compilou ainda. Não bloqueiam; é
onde a pessoa as encontra.

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

## B.7b Acompanhar o loop sem entender de harness engineering

Durante a implementação passam dezenas de tool calls e nenhuma delas responde
o que você quer saber: onde estou, o que está sendo feito agora, está indo bem
e o que vem a seguir. O **placar de andamento** responde as quatro. São três
renders do MESMO estado — nada é coletado a mais, tudo sai do contrato, do
rastro de tentativas e da trajetória de métrica que o loop já grava:

```powershell
harness status --brief --dir .            # bloco markdown; é o que o agente cola no chat
harness status --panel --dir .            # painel de terminal (cor só quando é TTY)
harness status --panel --watch 5 --dir .  # re-renderiza a cada 5s, estilo htop
```

O `--brief` traz progresso `X/N`, a lista de tarefas com estado, a tarefa atual
com `tentativa n/teto`, a **primeira linha do erro** da última prova como o
runner a imprimiu, e o próximo passo. O ciclo de trabalho manda o agente colar
essa saída na abertura de cada iteração, na transição de fatia e em qualquer
parada — e **proíbe** que ele escreva o placar de cabeça: placar auto-relatado
é o agente se avaliando, que é justamente o que o harness não aceita.

O terceiro render não precisa ser pedido: `harness compile-session` instala
`.harness/hooks/statusline.py` e registra a entrada `statusLine` no
`settings.local.json`, e a barra do Claude Code passa a mostrar demanda,
progresso, tarefa, tentativa, veredito — e o custo da sessão, quando o próprio
CLI o fornece. Se você já tinha uma statusline configurada, ela é preservada.

> `harness status` **sem flag** continua imprimindo o mesmo JSON de sempre: o
> placar é opt-in por flag, e a saída padrão continua sendo a fonte de verdade
> estruturada do kill-switch.

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
abertura: harness health + harness reconcile   (o SessionStart injeta sozinho)
        │   exit 2 no health = parada: ambiente quebrado não se autocorrige
        ▼
sessão trabalha sozinha dentro do raio ──► implementa ──► harness verify
        │                                   (harness decide     (prova + re-prova
        │                                    o que não é óbvio)  incremental)
        │                                                            │
        │        ┌── exit 1/2 (vermelho ou regressão) ───────────────┘
        │        ▼
        │   rastro em .harness/attempts/ ──► harness budget ──► continue?
        │        ▲                                │              corrige e volta
        │        └────────────────────────────────┘   stop_*? para e escala
        ▼
evidência gravada ──► passes: true ──► harness supervise devolve next: null
        │
        ▼
harness blind package ──► subagente com contexto limpo ──► blind verdict
        │                 (o único ponto de independência obrigatório)
        ▼
harness finish ──► audita o fecho + varre descartáveis   ◄── fim da demanda
        │          (blockers: [] é a pré-condição do commit;
        │           veredito cego ausente/velho/reprovado bloqueia)
        ▼
agente apresenta o diff ──► commit + push na branch do contrato
        │                   (descrição funcional + link file:line)
        ▼
harness pr-draft ──► corpo do PR + comando gh pr create
        │            ◄── o humano abre o PR (o agente nunca abre)
```

## B.9 (Dormente) Fase 4 — time de agentes com revisão independente

> **Esta seção descreve superfície DORMENTE.** `harness team design|generate`,
> `harness review`, `harness audit-team` e a skill `/harness-creator:team`
> existem na CLI e no plugin, e têm teste — mas **nada no ciclo de hoje os
> aciona**: nenhum projeto, nem este, tem time compilado; nenhum dos 17 passos
> do lifecycle os chama; e sem `.harness/team/manifest.json` o veto do revisor
> no `boundary_guard` é no-op, isto é, o comportamento é idêntico ao de não
> haver time. O que está escrito abaixo é o que aconteceria se você ativasse,
> não o que acontece na sua sessão. A independência que a Fase 4 prometia é
> hoje entregue pela camada 3 (B.5d), que roda sem time nenhum.

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
| `/harness-creator:plan`, `compile-contract` ou `compile-session` falham com "governança nunca instalada" | `.harness/harness.yaml` não existe — este repositório nunca rodou `/harness-creator:init` | Rode `/harness-creator:init` (uma vez por projeto) e tente de novo |
| `harness verify`/`harness supervise` falham nomeando hooks ausentes ou kill-switch | Contrato ativo, mas o enforcement não está instalado NESTA máquina (clone novo/segunda máquina) ou está desligado | Hooks ausentes: `harness compile-session`. Kill-switch: `harness enable` |
| `compile-contract` falha com erro de aprovação | `approved_by`/`approved_at` vazios no frontmatter do `spec.md` | Revisar e preencher — é intencional, o gate é você |
| `harness analyze` detecta Python, mas o comando de instalação não é `pip install -e .` | Projeto só tem `requirements.txt` | É o esperado: `requirements.txt` prova a **linguagem**, não que o repo seja um pacote instalável. Só `pyproject.toml` (com metadados) e `setup.py` valem para isso |
| Edição em `feature_list.json` negada | Tentativa de `passes: true` sem evidência fresca | Rode `harness verify <id>` primeiro — é o feature-lock funcionando |
| Edição de teste negada | Arquivo de teste não está nos `files[]` da tarefa ativa | Se for legítimo, ajuste o contrato (Plans.md) e recompile; se não, é a proteção anti-enfraquecimento agindo |
| Comando aprovado + `&&` negado | Segmento extra não prefixa comando da superfície | Declare o comando extra em `governance.extra_allowed_commands` (o próprio deny traz o bloco pronto) ou rode separado |
| Score baixo no `/harness-creator:audit` | Drift — artefato compilado editado à mão | Edite o `harness.yaml` (fonte de verdade) e recompile |
| Nada é bloqueado, nem o que deveria | Kill-switch ligado e esquecido — é **invisível** na sessão | `harness status --dir .`; se desativado, `harness enable`. Reveja o que passou nesse período |
| `harness verify` verde mas `supervise` devolve a mesma tarefa | `--no-mark-passed` em uso, ou o verify é anterior à v0.23.0 | Rode sem a flag — marcar virou o padrão. O stderr do verify diz em que estado a tarefa ficou |
| `harness finish` reprova com `evidence_stale` | O código mudou depois da prova — o `files_hash` não bate mais | Rode `harness verify <id>` de novo para regravar a evidência sobre o conteúdo atual |
| `harness finish` reprova com `tree_residue` | Tracked sujo fora dos `files[]` do contrato | Commite ou reverta o que sobrou; artefato temporário devia estar em `.harness/scratch/` |
| `compile-session` aborta com working tree suja | O comando exige árvore limpa para criar a branch do contrato | Commite ou dê stash. Depois de reinstalar do zero, a ordem é `analyze` → `compile` → **commit** → `compile-contract` → `compile-session` |
| `harness finish` reprova com `blind_review_missing` | A entrega não passou pela camada 3 — só quem implementou a olhou | `harness blind package`, despache o pacote para um subagente limpo, registre com `harness blind verdict` (B.5d) |
| `harness finish` reprova com `blind_review_stale` | O código mudou depois do julgamento cego | Refaça a verificação e registre um veredito novo — o anterior fica no histórico |
| `harness verify` sai com exit 2 e a tarefa está verde | Regressão: uma tarefa já concluída que compartilha `files[]` voltou a falhar e foi rebaixada | Conserte-a antes de escolher outra fatia; o diff suspeito ainda tem o tamanho de uma iteração |
| O agente insiste na mesma correção que já falhou 3× | Ele não consultou o disjuntor | `harness budget --feature <id> --dir .` — `stop_same_failure` significa mudar de abordagem, não tentar de novo |
| O contrato "tem" stop conditions e nada nunca para | As condições foram escritas só em prosa, que é *advisory* — ninguém conta | Acrescente a forma tipada (`{type: consecutive_verify_failures, n: 3}`) ao frontmatter e recompile o contrato |
| Hook aparece como `hook error` no transcript | Interpretador do hook irresolúvel (venv recriado, repo movido) | `harness doctor --dir .` — é a falha mais perigosa, porque a tool call passaria sem gate se não fosse o `\|\| exit 2`. `harness health` faz a mesma pergunta na abertura |

## Referências

- [README.md](../../README.md) — o que o plugin é, CLI completa, instalação
- [GUIDE.md](GUIDE.md) — referência completa do dia a dia, seção por seção
- [ARCHITECTURE.md](ARCHITECTURE.md) — como o produto é construído por dentro
- [arquitetura-visual.html](arquitetura-visual.html) — a arquitetura em
  diagramas interativos, com simulador da cascata de decisão
- [docs/preflight.md](../preflight.md) — detalhe do portão de entrada
- [loop-engineering-design.md](../reference/loop-engineering-design.md) — o
  design por trás de B.5b–B.5d: disjuntor, spine, re-prova e camada 3
- `.harness/LIFECYCLE.md` (no seu projeto) — os 17 passos, um a um
- [CHANGELOG.md](../reference/CHANGELOG.md) — histórico de versões
- `tests/e2e/evidence/` — evidências dos dogfoods reais que provam cada
  mecanismo descrito aqui em sessão `claude -p` de verdade
