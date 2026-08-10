# harness-creator

**v0.34.0** · [CHANGELOG](docs/reference/CHANGELOG.md) · [Arquitetura visual (HTML interativo)](docs/plugin/arquitetura-visual.html)

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
com ciclo de atualização próprio. A camada dos artefatos do repo-alvo se
atualiza sozinha; as outras duas continuam manuais:

```bash
# 1. pacote Python (lib + CLI `harness`) — o único passo obrigatório
pip install --upgrade harness-creator            # ou: pip install -e . (checkout local)

# 2. plugin instalado no Claude Code (skills, comandos) — reiniciar a sessão depois
claude plugin update harness-creator@<marketplace>

# 3. confirma que as 3 camadas batem — aponta o que ficou pra trás
harness doctor --dir <repo-alvo>
```

**Os artefatos compilados do repo-alvo (hooks, permissions, `AGENTS.md`) não
precisam de comando.** Quando eles estão atrás do pacote instalado, o próprio
harness os regenera — ao rodar qualquer comando `harness` naquele repositório,
ou ao abrir uma sessão do Claude Code nele. A recompilação avisa em uma linha
no stderr (`harness: artefatos recompilados 0.29.0 -> 0.30.0`) e **nunca cria
nem troca a branch de contrato**. Detalhes e limites em
[GUIDE.md](docs/plugin/GUIDE.md#atualização-transparente-dos-artefatos).

**O cache de plugin (passo 2) avisa, mas não bloqueia.** Ele não pode se
auto-atualizar — `claude plugin update` exige rede e as skills são carregadas
na inicialização da sessão. Quando fica atrás, a sessão do Claude Code começa
com um aviso em destaque trazendo o comando exato e o lembrete de reiniciar.
Nada é bloqueado: skill desatualizada não fura gate nenhum, porque o
enforcement vive nos hooks e na CLI. As razões de não bloquear estão em
[GUIDE.md](docs/plugin/GUIDE.md#a-camada-3-avisa-e-não-bloqueia).

`harness doctor` compara a versão do pacote pip instalado, a versão gravada
no último `harness compile` (`.harness/compiled-state.json`) e a versão no
cache de plugin do Claude Code (`~/.claude/plugins/installed_plugins.json`);
exit code 0 se tudo bate, 1 se alguma camada ficou atrasada — com o comando
exato para corrigir. É o único comando deliberadamente isento da atualização
automática: ele existe para mostrar o estado real, não para corrigi-lo.

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

## CLI — os 27 subcomandos

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
| `harness health` | Health check de abertura: as ferramentas dos `verify_cmd` respondem, a governança compilada está viva, a proteção está ligada. **Pergunta, nunca executa o `verify_cmd` nem conserta nada**; exit 2 quando o ambiente está quebrado |
| `harness reconcile` | Reconcilia estado declarado × real na abertura da sessão: prova velha, tarefa marcada sem prova, sobra na tree, progresso de outra demanda. Só leitura; exit 2 quando há divergência |
| `harness supervise` | Devolve a próxima feature pronta respeitando `depends[]`. Leitura síncrona, não daemon |
| `harness budget --feature <id>` | Disjuntor do loop: conta o rastro de tentativas e devolve `continue`/`stop_same_failure`/`stop_iterations`. Só leitura; exit 2 quando manda parar |
| `harness finish` | Encerra a demanda: audita o fecho e, só se aprovado, varre os descartáveis do `.harness/`. **Nunca toca git** |
| `harness blind package` | Camada 3 — monta `.harness/scratch/blind-package.md` (o que foi prometido, onde olhar, qual era a prova) **sem nada do raciocínio de quem implementou** |
| `harness blind verdict --pass\|--fail --evidence "..."` | Registra o veredito do verificador em `.harness/blind-review/<contrato>.json`. Append; exit 2 quando reprova |
| `harness pr-draft` | Monta o PR a partir do contrato: grava `.harness/scratch/pr-body.md` e imprime o `gh pr create` exato. **O agente nunca abre o PR** |

### Spine do projeto (§5.2 e §5.3)

| Comando | Faz |
|---|---|
| `harness decide "<título>" --decision "..." --why "..."` | Acrescenta uma decisão (com a alternativa descartada e o porquê) em `.harness/decisions.md`. Append-only, id sequencial, datada. As recentes voltam sozinhas no contexto da próxima sessão |
| `harness lesson "<fricção>" --fix "..."` | Acrescenta uma linha em `.harness/lessons.md`. **O agente anota, o humano compila** — as abertas aparecem no `harness finish` |

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
| `harness status --brief` | **Placar de andamento** em markdown, para o agente colar no chat |
| `harness status --panel [--watch N]` | O mesmo placar no terminal, com cor e re-render a cada N segundos |

`audit`, `audit-runtime` e `audit-team` saem com código 1 se houver qualquer
finding `critical` (ou score < 60) — servem como gate de CI.

## Placar de andamento

Durante a implementação passam dezenas de tool calls e nada responde as quatro
perguntas de quem está olhando: **onde estou**, **o que está sendo feito
agora**, **está indo bem** e **o que vem a seguir**. O placar responde as
quatro, em três renders da MESMA fonte de dados — nada é coletado a mais: tudo
sai do `feature_list.json`, do rastro de tentativas e da trajetória de métrica
que o loop já grava.

```powershell
harness status --brief --dir .          # bloco markdown para colar no chat
harness status --panel --dir .          # painel do terminal (cor só em TTY)
harness status --panel --watch 5 --dir . # re-render a cada 5s, estilo htop
```

- **`--brief`** — progresso `X/N`, lista de tarefas com estado, tarefa atual
  com `tentativa n/teto`, a última prova com a **primeira linha do erro** como
  o runner a imprimiu, a trajetória da métrica quando a tarefa tem `metric`, e
  o próximo passo derivado do estado. Sem ANSI: o chat renderiza markdown, não
  escape code. O lifecycle manda **colar** essa saída na abertura de cada
  iteração, na transição de fatia e em qualquer parada — e proíbe redigi-la de
  cabeça, porque placar auto-relatado é self-report.
- **`--panel`** — mesmo conteúdo para o seu terminal, com cor quando a saída é
  um TTY (em pipe sai texto puro). `--watch N` re-renderiza sozinho num
  segundo terminal; é um loop de render, não um daemon — morre com o terminal.
- **statusline** — `harness compile-session` instala
  `.harness/hooks/statusline.py` e registra a entrada `statusLine` no settings
  machine-local: uma linha sempre visível na barra do Claude Code com demanda,
  progresso, tarefa, tentativa, veredito da última prova e o custo da sessão
  (esse último quando o próprio CLI o entrega no stdin — campo ausente não
  quebra a linha). Statusline que **você** configurou não é sobrescrita.

`harness status` **sem flag** continua imprimindo o mesmo JSON estruturado de
sempre: é a fonte de verdade sobre o kill-switch e o que ferramenta consome.

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
   `evidence_stale` (o `files_hash` não bate — o código mudou depois da prova),
   `tree_residue` (tracked sujo fora dos `files[]` do contrato) e os três da
   camada 3: `blind_review_missing` (só quem implementou olhou a entrega),
   `blind_review_stale` (o veredito é anterior ao código) e
   `blind_review_failed` (o verificador independente reprovou).
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

### Disjuntor do loop de autocorreção

Antes, o passo 10 do lifecycle mandava autocorrigir "respeitando as stop
conditions" — frases livres no frontmatter do `spec.md`, contadas de cabeça
pelo agente e esquecidas na sessão seguinte. Um disjuntor que depende de
alguém lembrar de contar não é disjuntor.

- **Rastro de tentativas** (`src/harness/attempts.py`) — toda passada de
  `harness verify` deixa linha em `.harness/attempts/<contrato>/<id>.jsonl`:
  no vermelho, o erro CRU + `failure_signature` (sha da primeira linha do
  erro); no verde, o marcador que encerra a sequência. O arquivo nunca é
  apagado — o histórico é o produto, e é o que a próxima sessão lê para não
  repetir a tentativa 1 de boa fé. Evidência continua proibida no vermelho.
- **Contagem** (`harness budget --feature <id>`) — só leitura. `continue`
  enquanto há folga; `stop_same_failure` quando a MESMA assinatura se repetiu
  até o teto (a abordagem é que está errada, não a execução);
  `stop_iterations` quando as falhas desde o último verde estouraram o teto.
- **Tetos** — `stop_conditions:` do `spec.md` aceita forma TIPADA
  (`{type: consecutive_verify_failures, n: 3}`,
  `{type: same_failure_signature, n: 3}`), compilada para o
  `feature_list.json`; sem ela, vale
  `governance.budget.max_green_iterations` do `harness.yaml` — que deixou de
  ser texto de orientação e passou a ter consumidor. Condição em prosa
  continua valendo como advisory (é ela que cobre o sinal de
  impossibilidade). Tipo desconhecido não vira advisory mudo: **reprova a
  compilação**.
- **Rastro legível** — o `.harness/progress.md` ganha a região gerenciada
  `### Tentativas — <id>` enquanto a fatia está vermelha, e ela some sozinha
  no verde.

Base de projeto: [docs/reference/loop-engineering-design.md](docs/reference/loop-engineering-design.md),
§4.2 (budget mecânico), §5.1 (histórico de tentativas), §8.2 (padrão
repetido).

### Reconciliação na abertura

O harness sempre conferiu se o que está anotado como pronto ainda é verdade —
mas só no FECHO (`harness finish`), quando a sessão já gastou seu tempo
acreditando na anotação. `harness reconcile` faz a mesma conferência no INÍCIO,
e é o passo 5 do lifecycle.

- **Mesma regra, outro momento** (`src/harness/reconcile.py`) — chama
  `finish.audit_closure` em vez de reimplementar o julgamento: prova cujo
  `files_hash` não bate com o código atual (`evidence_stale`), tarefa marcada
  como passando sem arquivo de prova (`evidence_missing`), sobra tracked fora
  do contrato (`tree_residue`), harness em no-op (`killswitch_active`).
- **A tradução** — `feature_not_passed` e `no_contract` NÃO são divergência de
  abertura: tarefa pendente é o estado de quem está começando, e repo sem
  contrato é bootstrap. Um aviso que aparece em toda sessão é um aviso que
  ensina a ignorar avisos.
- **A divergência que só existe na abertura** — `progress_contract_mismatch`:
  o `.harness/progress.md` descrevendo um contrato diferente do
  `feature_list.json`. O `finish` não vê porque reescreve o arquivo logo em
  seguida; na abertura é a mentira mais cara que existe (v0.25.0: o
  `SessionStart` injetou "nenhuma feature pendente" numa sessão com seis
  tarefas a fazer).
- **Chega sozinha** — o hook `SessionStart` injeta a seção de aviso quando há
  divergência, e nada quando não há. Depender de o agente lembrar de rodar era
  o mesmo defeito das stop conditions em prosa.

Só leitura, como o `audit_closure`: não roda `verify_cmd`, não conserta, não
toca rede. Base: §7.4 do mesmo documento.

### Re-prova incremental

Verificar a fatia que acabou de ficar pronta é barato porque não olha para trás
— e o preço disso é que a fatia 5 quebra a fatia 2 sem ninguém perceber, até o
gate final, quando o diff suspeito já tem o tamanho da demanda inteira.
`harness verify` passou a fechar esse buraco sozinho (`src/harness/regression.py`).

- **A interseção, não a suíte** — ao fechar uma tarefa, re-roda o `verify_cmd`
  das tarefas já `passes: true` que compartilham algum caminho de `files[]` com
  ela. O custo fica proporcional ao acoplamento real; suíte completa a cada
  volta é a camada 3, que o design proíbe dentro do loop.
- **O acoplamento é o declarado** — `files[]`, não import nem histórico do git.
  Acoplamento não declarado é defeito do contrato, e `harness task add-file`
  existe para corrigi-lo.
- **Vermelho rebaixa** — a tarefa regredida volta a `passes: false`, com
  tentativa registrada: reentra na fila do `harness supervise`, conta no
  disjuntor do `harness budget` e bloqueia o `harness finish`. Avisar sem
  rebaixar deixaria o `feature_list.json` alegando pronto o que acabou de
  falhar. A evidência antiga não é apagada — vira `evidence_stale`, que é
  informação.
- **Falha de ambiente não rebaixa** — timeout ou prova no runtime floor saem
  como `SEM VEREDITO`: aparecem no relatório (proteção que falha em silêncio é
  indistinguível de proteção que passou), mas não derrubam registro válido.
- **Exit code 2** — mesma convenção de `budget` e `reconcile`: veredito de
  parada, não erro de execução. `--no-reproof` desliga.

Base: §6 do mesmo documento.

### A spine completa: progresso, decisões e lições

O design descreve TRÊS registros persistentes, com ciclos de vida diferentes. O
harness mecanizava só o primeiro:

| arquivo | responde | vida | escrito por |
|---|---|---|---|
| `.harness/progress.md` | onde estamos | a demanda | `verify`/`finish` (reescreve) |
| `.harness/decisions.md` | por que decidimos assim | o projeto | `harness decide` (append) |
| `.harness/lessons.md` | o que atrapalhou | o projeto | `harness lesson` (append) |

- **Append-only é a garantia** — decisão registrada não é editada nem apagada;
  mudou de ideia, registre outra que a supersede. Um arquivo reescrevível não
  prova que a razão gravada é a razão original, e essa prova é a única coisa
  que ele tem a oferecer.
- **Escrever é comando, não edição** — o `boundary_guard` barra escrita em
  `.harness/**` (plano de controle não se auto-amplia), então ou existe verbo
  ou estes arquivos nunca são escritos. O verbo também numera e data sem
  colisão.
- **As decisões chegam sozinhas** — o `SessionStart` injeta as mais recentes,
  com o porquê junto, depois do resumo de progresso: a hora de saber o que não
  re-tentar é ao escolher a próxima fatia. Sem isso, a sessão de daqui a duas
  semanas "descobre" a alternativa que esta descartou por bom motivo.
- **As lições NÃO chegam** — §5.3 é explícito: elas não bloqueiam retomada.
  Aparecem no `harness finish` (`open_lessons`) para o humano. O agente anota;
  **o agente não aplica**. Auto-modificação do harness pelo próprio agente é a
  camada mais perigosa do design.

Base: §5.2 e §5.3 do mesmo documento.

### Camada 3: o olho que não implementou

As camadas 1 e 2 provam que o teste passa — e o teste foi escrito pela mesma
cabeça que escreveu o código. Nenhuma das duas pergunta se o que foi entregue é
o que a demanda prometia. O §9.1 chama UM ponto de independência de mínimo
obrigatório, e é este (`src/harness/blind.py`):

```powershell
harness blind package --dir .    # monta .harness/scratch/blind-package.md
harness blind verdict --pass --evidence "conferi src/x.py:42 contra T-01"
harness blind verdict --fail --evidence "T-01 nao cobre o caso vazio"
```

- **O pacote é montado por código** — sai do `feature_list.json`, que já é a
  projeção limpa do contrato: `desc` (o que foi prometido), `files[]` (onde
  olhar), `verify_cmd` (a prova). Um prompt redigido por quem acabou de
  implementar vaza a justificativa por construção, sem má-fé nenhuma — e o
  §9.1 é explícito que uma avaliação assim já nasce contaminada.
- **O que fica de fora é a entrega** — `spec.md`, `.harness/progress.md`
  (histórico de tentativas), `.harness/decisions.md`, `.harness/lessons.md` e
  as mensagens de commit. O pacote os nomeia com o motivo, porque "não leia"
  sem motivo é a instrução que mais se ignora.
- **O veredito prende o hash do que julgou** — mesma mecânica da evidência de
  camada 2. Código mudou depois → `blind_review_stale`, e o fecho cobra outro.
  Sem isso, um "aprovado" de vinte commits atrás fecharia a demanda de hoje.
- **Veredito novo não apaga o anterior** — reprovação que some é reprovação que
  se re-litiga. Append, como `decisions.md`.
- **Exit code 2 para reprovado** — veredito legítimo de parada. Gate que só
  sabe aprovar não é gate.
- **Quem verificou não conserta** — o veredito volta ao loop, que decide.
  Fundir os papéis economiza uma chamada e custa a independência inteira.

Limite declarado: o harness não prova que o subagente recebeu SÓ o pacote. Ele
garante que o pacote existe em disco, foi derivado por código, e que o veredito
está preso ao estado que julgou; a disciplina do despacho é o passo 15 do
lifecycle. Mecanismo onde dá, prosa onde não dá.

Base: §6 (camada 3) e §9.1 do mesmo documento.

## Estrutura do repo

```
harness-creator/
├── .claude-plugin/
│   ├── plugin.json              # manifesto do plugin
│   └── marketplace.json         # auto-referência p/ instalar como marketplace local
├── AGENTS.md                    # 3 blocos gerenciados + prosa humana
├── skills/                      # preflight, init, plan, compile, audit, team
├── src/harness/                 # 44 módulos, uma responsabilidade cada
│   ├── cli.py                   # dispatch dos 27 subcomandos
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
│   ├── autoupdate.py            # decide e dispara a recompilação de artefato atrasado
│   │
│   │                            # -- enforcement em runtime (hooks gerados) --
│   ├── boundary_guard.py        # dispatcher único: raio de impacto + runtime floor
│   ├── session_start.py         # injeta o estado da sessão anterior
│   ├── stop_hook.py             # avisa (sem bloquear) sobre trabalho não verificado
│   ├── statusline.py            # uma linha de placar na barra do Claude Code
│   │
│   │                            # -- prova e controle --
│   ├── verify.py                # roda verify_cmd e grava a evidência
│   ├── skips.py                 # skip nunca silencioso: parser, baseline, delta, INFRA
│   ├── attempts.py              # rastro de tentativas: erro cru + assinatura da falha
│   ├── convergence.py           # §4.3: trajetória de métrica opt-in — piora/platô
│   ├── regression.py            # re-prova incremental: fatia nova × fatias já provadas
│   ├── spine.py                 # decisões e lições: append-only, vida = o projeto
│   ├── blind.py                 # camada 3: pacote sem o racional + veredito com hash
│   ├── budget.py                # disjuntor do loop: continue / stop_* por contagem
│   ├── escalation.py            # bloco de escalada do §8, 6 partes, pronto pro humano
│   ├── health.py                # ambiente responde? (§7.2) — pergunta, não executa
│   ├── reconcile.py             # declarado × real na ABERTURA (reusa audit_closure)
│   ├── review.py                # state machine do revisor (teto duro de iterações)
│   ├── supervisor.py            # próxima feature pronta, respeitando depends[]
│   ├── teams.py                 # catálogo de 6 padrões + análise de domínio
│   ├── finish.py                # encerra a demanda: audita o fecho e varre
│   ├── pr_draft.py              # contrato + evidência -> corpo do PR e comando gh
│   ├── panel.py                 # placar do loop: uma fonte, três renders (status/panel/statusline)
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
└── tests/                       # 1480 casos (sem Docker/API para compile/audit)
```

Quem decide o que entra no git é a **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md` — política
canônica, uma frase: *especificação, contrato e prova são versionados; saída
de compilação que carrega dado de máquina é machine-local e regenerada por
`compile`*. O inventário artefato a artefato está em `docs/plugin/TUTORIAL.md`.

## Testes

```powershell
$env:PYTHONPATH = "src"
python -m pytest tests -q          # unit + E2E — 1480 casos
```

A suíte E2E (`tests/e2e/`) roda inteira sobre repos sintéticos criados em
`tmp_path` (Node, Python, YAML) — compile, audit, hooks via stdin, drift e
merge, tudo em subprocess como na vida real, sem depender de nenhum projeto
externo ao plugin.

**Convenção da suíte (v0.26.0):** um teste = uma REGRA, com tabela de casos
(`Case` + `_expect`), nunca um `def` por caso. A suíte tinha chegado a 1008
casos e caiu para 724 sem perder uma asserção — o que sobrou é o piso
mecânico, não gordura restante. O crescimento desde então — hoje 1480 casos —
é regra nova coberta, não a gordura voltando.

Achado que a suíte documenta (via `harness.cli` chamado com
`--output-format json`, mesmo padrão usado pelo `claude -p` real): uma ação
negada nunca precisa travar a sessão — o hook responde `deny` e quem chama
decide o que fazer. Pra detectar o bloqueio num script, não dá pra confiar no
exit code isolado: tem que checar o campo estruturado da decisão
(`permissionDecision`/`permission_denials`).
