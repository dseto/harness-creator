# Guia de uso — harness-creator

Este guia cobre o **dia a dia**: depois do plugin instalado, como você de fato
usa o harness para fazer uma alteração num projeto.

Para o que o plugin é e como está estruturado, veja o [README](../../README.md).

## 1. Instalar o plugin (uma vez, por máquina)

### Opção A: Local (desenvolvimento)

```powershell
cd C:\Projetos\Harness-creator
pip install -e .
claude --plugin-dir C:\Projetos\Harness-creator
```

### Opção B: GitHub (remoto)

```bash
pip install git+https://github.com/dseto/harness-creator
python -c "from pathlib import Path; import harness; print(Path(harness.__file__).parent)"
claude --plugin-dir <path-acima>
```

Ambas abrem uma sessão do Claude Code com as 7 skills disponíveis:
`/harness-creator:preflight`, `/harness-creator:init`,
`/harness-creator:assess`, `/harness-creator:audit`,
`/harness-creator:compile`, `/harness-creator:plan`, `/harness-creator:team`.

> Repita `claude --plugin-dir ...` toda vez que abrir o Claude Code para
> trabalhar com harness — não é uma instalação permanente do Claude Code em
> si, é um flag de sessão. (Se preferir permanente, ver seção 12.)

## 2. Criar o harness no projeto-alvo (uma vez, por repositório)

Abra a sessão **dentro do repositório que você quer governar**:

```powershell
cd C:\MeuProjeto
claude --plugin-dir C:\Projetos\Harness-creator
```

Na sessão, rode:

```
/harness-creator:init
```

A skill pergunta (com defaults sugeridos a partir do seu projeto):
- política de aprovação: `balanced` (recomendado), `paranoid` ou `auto`
- comando de teste (`pytest`, `npm test`, `go test`...)
- glob dos arquivos de teste (`tests/**/*.py`, `**/*.test.ts`,
  `**/*.spec.ts`...)
- se quer disciplina TDD (bloquear edição de teste / execução direta da suíte)

Ao final ela escreve `.harness/harness.yaml`, compila, e mostra o que foi
gerado:
- `.claude/settings.local.json` — regras de permissão (`allow`/`ask`).
  Machine-local: leva o path absoluto desta máquina no comando do hook, por
  isso nasce ignorado (`.claude/.gitignore`) e um clone precisa rodar
  `harness compile` antes da primeira sessão
- `.harness/hooks/guard_tests.py` e `guard_test_runner.py`
- bloco gerenciado em `AGENTS.md`

O que de tudo isso entra no git segue uma regra única — *especificação,
contrato e prova são versionados; saída de compilação que carrega dado de
máquina é machine-local* —, cuja fonte canônica é a **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`. O
inventário artefato a artefato está em `docs/plugin/TUTORIAL.md`; `harness
doctor` denuncia o clone que ainda não compilou.

**Importante: feche e reabra a sessão do Claude Code nesse projeto.**
o settings só é lido na inicialização — a sessão que rodou o `/init` não
aplica as regras nela mesma.

## 3. Fazer uma alteração no projeto (o fluxo do dia a dia)

Depois do passo 2, **você não usa mais skill nenhuma para trabalhar** — usa o
Claude Code normalmente. O harness age em segundo plano via permissions/hooks.
Exemplo com política `balanced`:

```powershell
cd C:\MeuProjeto
claude    # sessão normal, SEM --plugin-dir — governança já está no projeto
```

Peça a alteração como sempre: *"corrige o bug de paginação em `list.py`"*.

O que muda na prática:

| Você pede | O que acontece | Por quê |
|---|---|---|
| Ler/buscar código (Read/Grep/Glob) | Roda direto, sem prompt | `balanced` libera leitura |
| Editar arquivo-fonte (`list.py`) | Prompt de aprovação (`ask`) | toda edição pede confirmação em `balanced` |
| Editar arquivo de teste (`tests/test_list.py`) | Prompt de aprovação **com motivo específico**: "edição de teste exige aprovação humana — regra TDD do harness" | hook `guard_tests.py` — impede alterar o teste pra fazer ele passar |
| Rodar a suíte inteira (`pytest`) direto | Prompt de aprovação com motivo TDD | hook `guard_test_runner.py` — incentiva ciclo red-green-refactor supervisionado |
| Rodar outro comando (`git status`, `ls`) | Prompt de aprovação (`ask`, política de execução) | `balanced` gateia todo `Bash` |
| Acessar rede (`curl`, `WebFetch`) | Prompt de aprovação **sempre**, em qualquer política incl. `auto` | classe network é sempre gateada, de propósito |

Você aprova ou nega cada prompt como qualquer prompt nativo do Claude Code —
não tem UI própria do harness, é o mecanismo padrão de permissions.

### Política `auto`

Libera edição e execução sem prompt (exceto rede e edição de teste, que
continuam gateadas). Use só se você quer o Claude Code trabalhando sem parar
pra confirmar cada edição — **não é read-only**, ele muda arquivos e roda
comandos sozinho.

### Política `paranoid`

Pede aprovação até para leitura. Use em repositório sensível ou primeira
sessão com um agente novo, quando você quer ver cada passo antes de deixar
rodar mais solto.

## 4. Mudou de ideia sobre a política? Edite o yaml e recompile

```
/harness-creator:compile
```

(ou edite `.harness/harness.yaml` primeiro, se quiser trocar `approval_policy`,
`test_command`, `test_glob` ou `enforce_tdd`, e então rode o compile). Mostra
o diff do `settings.local.json` — o que entrou/saiu. **Reabra a sessão** de novo
para valer.

## 5. Trabalhar por contrato

Para uma demanda específica (uma feature, uma mudança maior), em vez de pedir
direto e aprovar cada edição uma por uma, use:

```
/harness-creator:plan
```

A skill lê (ou gera) o `repo-profile.json`, faz uma entrevista mínima sobre a
demanda e escreve um contrato em `.harness/work/<slug>/`:
- **`spec.md`** — o quê: escopo, critérios de aceitação executáveis,
  unknowns, stop conditions.
- **`Plans.md`** — o como: tarefas com arquivos afetados e comando de
  verificação de cada uma. Campo opcional `cwd` por tarefa: diretório
  relativo à raiz onde `verify_cmd` roda — necessário em monorepo
  (`backend/`+`frontend/`), onde um comando como `ng test` só resolve o
  binário de dentro do workspace do frontend; sem `cwd`, `verify_cmd` roda
  na raiz do repo.

Você revisa e aprova (ou pede ajuste) esse contrato. **O gate exige
`approved_by`/`approved_at` preenchidos no frontmatter do `spec.md` — a skill
nunca aprova sozinha**, aprovação é sempre um ato explícito seu. Só depois de
aprovado o contrato compila para `.harness/feature_list.json`:

```
harness compile-contract --dir <alvo> --slug <slug>
```

Sem aprovação, `compile-contract` sai com erro e nada é gerado.

## 6. Contrato aprovado → sessão autônoma no raio de impacto

Depois do contrato aprovado (seção anterior), rode:

```
harness compile-session --dir <alvo>
```

**Dois efeitos sobre o git que só este comando tem:** ele exige a working tree
limpa (aborta com exit 1 e não escreve nada se houver tracked modificado ou
staged) e **cria/troca para a branch `contract/<slug>`**. Um decorre do outro:
criar a branch de contrato com sujeira misturaria trabalho de outro contexto.
Desligue com `governance.branch_per_contract: false` no `.harness/harness.yaml`
se o seu fluxo não quer branch por contrato. Depois de uma reinstalação do
zero, commite antes — a reinstalação suja a árvore, e `LIFECYCLE.md` e
`feature_list.json` só voltam por `compile-session`/`compile-contract`.

Isso compila a **Fase 2** do roadmap (Execução Autônoma no Raio de Impacto):

- **Permissions da sessão** (`session_permissions.py`) — `allow` enumerado
  (nunca genérico) para exatamente a superfície que o contrato aprovado usa:
  `Edit`/`Write` nos `files[]` das tarefas, os `verify_cmd` e comandos de
  lint/build do profile, instalação de dependência do `package_manager`
  detectado, git local do ritual (`status/log/diff/add/commit`), e qualquer
  comando declarado em `governance.extra_allowed_commands` do
  `.harness/harness.yaml` (opcional — comandos permanentes que o dono do
  repo libera, ex.: o CLI do próprio produto).
- **`boundary_guard.py`** — hook `PreToolUse` único que substitui (e remove,
  quando presente) o hook antigo `guard_tests.py`: numa só passada cobre
  `Edit`, `Write`, `MultiEdit`, `NotebookEdit`, `PowerShell` e `Bash`, em vez
  de N guards por ação, decidindo `allow`/`deny` a partir da superfície do
  contrato ativo. O matcher registrado é `"*"` (toda tool call), com
  roteamento explícito por nome de tool — com um matcher restrito, qualquer
  tool de escrita fora do conjunto listado nunca invocaria o hook e o Claude
  Code aplicaria o allow implícito antes de o guard rodar. Traz proteção contra enfraquecimento de
  teste — só edita arquivo de teste se a tarefa ativa o declarar em
  `files[]`. Comando composto (`comando_aprovado && comando_qualquer`) não
  escapa: cada segmento entre `;`/`&&`/`||`/`|` precisa prefixar um comando
  da superfície liberada, e command substitution (`$(...)`/crase) é negada
  de cara — um agente não consegue colar uma ação arbitrária atrás de um
  `verify_cmd`/lint/git local aprovado. **Exceção de autoria de contrato**:
  `Write`/`Edit` sob `.harness/work/**` são sempre liberados (é onde o
  `spec.md`/`Plans.md` do PRÓXIMO contrato nascem, e eles nunca estão nos
  `files[]` do contrato ativo) — sem essa exceção, planejar a próxima feature
  esbarraria na superfície da feature corrente. O floor de segredo continua
  precedendo essa exceção. `files[]` aceita path exato, prefixo de diretório
  (termina em `/` — libera qualquer arquivo novo dentro, útil pra migrations)
  e glob (`*`/`?`) — o candidato é casado direto contra o padrão, nunca
  depende do arquivo já existir em disco.
- **Lifecycle de 17 passos** — bloco gerenciado adicional no `AGENTS.md`
  (ler AGENTS.md → rodar `init.*` → ler progresso → escolher UMA feature →
  implementar → verificar → autocorrigir → registrar evidência → commit em
  estado retomável → deixar a working tree limpa).
- **Templates de sessão** (`templates.py`) — `.harness/progress.md` (esqueleto
  runtime, gerado só se ainda não existir) e `.harness/init.sh`/`.harness/init.ps1`
  (determinísticos a partir do `repo-profile.json`).
- **Hook SessionStart** — injeta no início da sessão o resumo do progresso,
  a feature ativa e o `git log` recente, para a sessão nascer sabendo onde
  parou.

**O runtime floor nunca vira `allow`**, com ou sem contrato ativo: **escrita**
em arquivo de segredo (`.env`, `.pem`, `id_rsa`, `*credentials*`) — incluindo
redirecionamento de shell (`>`, `>>`, `tee`) — e rede/publicação não planejada
(`curl`, `wget`, `npm publish`, `pip upload`, `twine upload`, `gh release`)
continuam fora da superfície liberada, verificadas incondicionalmente antes de
qualquer outra checagem do `boundary_guard.py`. O floor avalia o comando bruto
**e** a forma normalizada (abaixo), então `.venv/Scripts/git.exe curl` é tão
negado quanto `curl`.

`git push` é o único item do floor com exceção, e ela é estreita: o push é
liberado **apenas** a partir da branch do contrato ativo (`contract/<slug>`,
a que `harness compile-session` cria), **apenas** para ela mesma, e **apenas**
com `-u`/`--set-upstream`. Tudo o mais segue negado — branch protegida,
qualquer outra branch, branch indeterminada (detached HEAD, worktree linkado:
aqui a postura é fail-**closed**, ao contrário do floor de commit), sem
contrato ativo, refspec explícito (`HEAD:main`), `--force`/`--force-with-lease`/
`--mirror`/`--delete`/`--all`/`--tags`, e push encadeado a outro comando. A
razão da exceção: depois de contrato aprovado e `verify` verde, empurrar a
branch que o próprio harness criou não é uma decisão nova — é o passo mecânico
de um ciclo já autorizado, e pará-lo obrigava um humano a rodar `git push` à
mão no fim de toda sessão autônoma. Abrir o PR continua sendo passo humano.

### Quando o guard atrapalha: três escapes, nenhum deles adivinhação

Todos os três nasceram do dogfood venv-Windows — uma API Python
com venv, no Windows, atrás de proxy corporativo, onde descobrir a grafia que o
guard aceitava consumiu cerca de treze ciclos de desligar e religar o harness.

**1. A forma de invocação não importa.** `pytest -q`, `python -m pytest -q`,
`.venv/Scripts/pytest.exe -q`, `.venv/bin/pytest -q` e `uv run pytest -q`
invocam o mesmo binário, então o guard reduz os dois lados da comparação à
mesma forma canônica antes de decidir. Não há grafia secreta a descobrir.
Continuam **fora**, por decisão explícita: `python -c` (executa string
arbitrária, não é invocação de binário), `uv run --with <pacote>` (instala da
rede antes de rodar, e rede sempre pede aprovação) e prefixo de diretório que
não seja de venv — `./scripts/deploy.sh` não vira `deploy.sh`, senão qualquer
script homônimo casaria a allowlist alheia.

**2. Comando novo e permanente: cole duas linhas no YAML.** Você não precisa
decorar nada — **a própria mensagem de deny já vem com o bloco pronto**, com o
comando preenchido. O agente só repassa. Se ele foi barrado em
`alembic upgrade head`, a razão do deny traz:

```yaml
  extra_allowed_commands:
    - alembic upgrade
```

Abra `.harness/harness.yaml` **no seu terminal** (fora do Claude Code — o agente
não escreve em `.harness/**`; é floor) e cole essas duas linhas dentro do bloco
`governance:` que já está lá. Se a chave já existir, acrescente só a linha do
`-`. **Vale na tool call seguinte**, sem recompilar nada.

Repare que o bloco **não** repete `governance:` — colar a chave duas vezes
quebra a leitura. E a lista casa por **prefixo**: `alembic upgrade` libera
`alembic upgrade head`, `--sql`, `+1` e o resto dos argumentos, então uma
entrada costuma bastar por ferramenta.

> Duas notas honestas. O parser que o hook usa para ler essa lista é mínimo e
> stdlib-only: entende lista de bloco (`- item`) e de fluxo (`[a, b]`), com ou
> sem aspas, e ignora comentário; qualquer outra sintaxe YAML faz a lista
> degradar para **vazia** — fecha, nunca abre. Se você escrever à mão e escapar
> disso, tanto `harness compile-session` quanto `harness doctor` acusam.
> Segunda: o `settings.json` continua compilado, então um comando adicionado sem
> recompilar passa no guard mas ainda pode gerar um prompt de permissão do
> Claude Code — atrito, não bloqueio; um `harness compile-session` na próxima
> parada natural silencia.

**Por que não existe um `harness allow-command`.** Foi avaliado e descartado:
com as formas de invocação já reconhecidas como equivalentes e a leitura em
runtime do YAML, a demanda restante é de uma entrada por ferramenta, uma vez —
pouco para justificar um subcomando permanente. O que importa aqui é que o
escape seja de dez segundos, e é por isso que o deny já vem com o bloco pronto:
um escape difícil não deixa o harness mais seguro, empurra para o kill-switch,
que desliga tudo.

**3. O profile inferido errou: `harness profile set`.** O `analyze` só infere,
e às vezes o ambiente contradiz o repositório — no caso real, o proxy derrubou
o TLS do `uv` e foi preciso usar `pip`, embora o lockfile continuasse apontando
`uv`:

```powershell
harness profile set package_manager pip --dir C:\Projetos\meu-projeto
harness compile-session --dir C:\Projetos\meu-projeto
```

As chaves ajustáveis são só as de **ambiente**: `package_manager`,
`test_command`, `lint_command`, `typecheck_command`, `build_command`. O valor
passa pelo mesmo runtime floor do resto. `test_glob` fica de fora de propósito
— ele decide o que conta como arquivo de teste protegido, o que é governança
(vive no `harness.yaml`, sob aprovação), não ambiente. E `profile` **não** é um
comando do agente: `test_command` alimenta a superfície de comando compilada,
então um agente capaz de gravar ali ampliaria a própria superfície. É comando
seu, no seu terminal.

Se ainda assim sobrar fricção, `harness status` mostra quantos ciclos
`disable`/`enable` esta máquina já gastou — é o número que decide se o produto
precisa de mais alguma porta ou se estas três bastam.

**O floor de segredo é de escrita, não de leitura** — decisão explícita.
`Read .env` e `cat .env` são liberados (ler `.env.example` ou conferir uma
chave de config é rotina), mas o guard anexa um AVISO à razão da decisão,
porque o conteúdo entra no contexto da sessão. Se o seu repositório não pode
nem ser lido por um agente, isso é política de permissions
(`approval_policy: paranoid`), não do floor.

## 7. Verificar a implementação (Fase 3 — loop de auto-verificação)

Depois de implementar uma feature do contrato ativo, rode:

```
harness verify <feature-id> --dir <alvo>
```

Isso roda o `verify_cmd` **real** daquela tarefa — o mesmo comando que está no
contrato aprovado, não uma alegação do agente. O comando é conferido contra o
runtime floor antes de rodar (`verify: curl ...` ou `git push ...` sai com
erro e **nunca** é executado, mesmo vindo de um contrato compilado), mas não é
cruzado com o `repo-profile.json`: quem aprova o contrato é quem responde pelo
comando declarado ali. Só se passar é que grava
`.harness/evidence/<contrato>/<feature-id>.json` (contrato, timestamp, comando,
hash). É o passo
11 do lifecycle ("registra a prova").

Marcar `passes: true` no `feature_list.json` **sem** evidência fresca (mais
nova que o último commit) é negado pelo `boundary_guard.py` — feature-lock:
o guard nega a edição e devolve a razão ao agente ("rode harness verify
primeiro"). Não dá pra declarar vitória editando a lista de tarefas na mão.
Isso vale mesmo quando a edição usa `replace_all` (troca todas as
ocorrências de `"passes": false` de uma vez) — o guard simula a transição
completa, não só a primeira, então uma feature sem evidência não passa de
carona numa edição em massa que aprova outra.

Se `verify` falhar, o próprio agente corrige e roda de novo — sem envolver
você — até passar ou até bater numa stop condition do `spec.md` (N falhas
seguidas da mesma suíte, sinal de impossibilidade), caso em que ele para,
registra o estado no `.harness/progress.md` e devolve com diagnóstico.

O hook **Stop** fecha o loop da sessão: se o agente tentar encerrar com uma
feature `in_progress` cuja verificação nunca rodou ou está falhando, o
encerramento devolve essa razão a ele — que retoma o ciclo ou executa o
ritual de handoff. De novo, quem é avisado é o agente, não você.

```
harness audit-runtime --dir <alvo>
```

Audita os artefatos runtime-mutáveis (`.harness/progress.md`,
`feature_list.json`, `evidence/`): schema, frescor e invariantes (1 feature
`in_progress` por vez; todo `passes:true` com evidência válida). É uma
máquina distinta do `/harness-creator:audit` (seção 9) — aquele faz diff
byte-exato dos artefatos **compilados** (settings/hooks/blocos gerenciados);
este confere os artefatos que mudam a cada sessão de trabalho.

## 8. Montar um time de agentes com revisão independente (Fase 4)

Depois do contrato aprovado (seção 5) e, opcionalmente, da sessão autônoma
compilada (seção 6), você pode ir além de uma sessão só e montar um **time
de agentes** para trabalhar o contrato — com revisão de qualidade
independente já embutida. Rode:

```
/harness-creator:team
```

A skill segue este fluxo:

1. **Design (dry-run)** — `harness team design --dir <alvo> --description
   "<descrição da demanda>"` analisa o domínio (`repo-profile.json`) e
   recomenda um padrão do catálogo (`producer-reviewer`, `supervisor`,
   `pipeline`, `expert-pool`, `fan-out-fan-in`, `hierarchical-delegation`)
   com justificativa. Não grava nada em disco.
2. **Apresentação** — a skill mostra o padrão recomendado, a justificativa e
   os papéis do time. Se você discordar, pode pedir outro padrão
   explicitamente.
3. **Aprovação explícita (o único toque humano da Fase 4, uma vez por
   projeto)** — a skill apresenta padrão + papéis + modo de execução (`mode`,
   padrão `subagents`) e pede sua aprovação clara antes de gerar qualquer
   arquivo. Sem aprovação explícita, nada é escrito — mesma regra dura da
   seção 5 para o contrato.
4. **Geração** — só depois da aprovação, `harness team generate --dir <alvo>
   --pattern <nome>` grava `.claude/agents/<papel>.md`,
   `.claude/skills/<papel>/SKILL.md`, o bloco de time em `AGENTS.md` +
   `.harness/TEAM.md` (detalhe) e o manifesto
   `.harness/team/manifest.json`.
5. **Validação** — `harness audit-team --dir <alvo>` confere papel órfão,
   papel do padrão sem agente gerado, ferramenta além do mínimo do catálogo
   (um `reviewer`/`supervisor` nunca deveria ganhar `Edit`/`Write`) e drift
   do bloco gerenciado. Finding crítico bloqueia considerar o time
   operacional.

A partir daí, o **ciclo operacional roda sem novo toque humano**: o produtor
implementa a feature; `harness verify <feature-id> --dir <alvo>` (seção 7)
grava evidência fresca e já aciona automaticamente a submissão para revisão
— não precisa rodar `review ... submit` manualmente. Com o padrão
`producer-reviewer` compilado, o **feature-lock** do `boundary_guard.py`
passa a exigir, além da evidência fresca, aprovação do revisor
(`.harness/review/<feature-id>.json` com `status: approved`) **mais recente
que a última evidência gravada** — uma aprovação antiga em relação a uma
evidência regravada depois dela é considerada obsoleta e bloqueada de novo.
O revisor decide com:

```
harness review <feature-id> approve --dir <alvo> --note "..."
harness review <feature-id> reject --dir <alvo> --note "..."
```

Rejeição devolve a tarefa ao produtor; o ciclo repete até aprovação **ou**
até o teto de iterações (`max_review_iterations`, default 3) estourar sem
aprovação — o que **nunca** força aprovação automática, apenas escala a
decisão a você. Com o padrão `supervisor` compilado,

```
harness supervise --dir <alvo>
```

devolve a próxima feature pronta a trabalhar, respeitando `depends[]` do
contrato — sem executar nada por conta própria (é uma leitura de estado
síncrona, não um daemon).

Sem time compilado (sem `.harness/team/manifest.json`), o feature-lock e o
`harness verify` continuam se comportando exatamente como na Fase 3 — zero
regressão.

## 9. Verificar se está tudo consistente

São dois cheques diferentes, e a confusão entre eles é comum.

**O conteúdo dos artefatos:**

```
/harness-creator:audit
```

Score 0–100. Rode depois de qualquer edição manual em `settings.local.json`,
`AGENTS.md` ou nos hooks — ele detecta *drift* (alguém editou à mão e
divergiu do que o `harness.yaml` geraria) e sugere recompilar. O mecanismo é
dogfooding: ele **recompila em memória e faz diff byte-exato** contra o disco,
em vez de reimplementar as regras. Regra nova no compilador passa a ser
auditada de graça.

**A saúde da instalação:**

```bash
harness doctor --dir .
```

Cobre três famílias de problema, todas **silenciosas** — nada falha, o Claude
Code simplesmente roda menos governança do que o repositório aparenta ter:

1. **Divergência de versão entre as 3 camadas de distribuição** — pacote pip,
   `.harness/` compilado e cache de plugin do Claude Code têm ciclos de
   atualização independentes. Atualizar só uma deixa as outras presas na
   versão antiga, e o comportamento observado reflete a mais atrasada.
2. **Compilação ausente ou apontando para o lugar errado** — o clone novo
   (que tem `harness.yaml` versionado e nenhum `settings.local.json`: parece
   instalado, nenhum hook roda) e o repositório que mudou de lugar no disco
   (o comando de hook leva path absoluto).
3. **Hook registrado que não roda** — interpretador irresolúvel. É a falha
   mais perigosa que este comando diagnostica: pela semântica de exit code de
   hook do Claude Code, só `exit 2` bloqueia, então um hook que morre antes de
   iniciar deixa a tool call **passar sem gate nenhum**. Por isso o comando
   registrado leva `|| exit 2`.

Exit 0 se tudo bate, 1 com a lista de issues e o comando exato de correção.
Vale rodar depois de todo `pip install --upgrade`, `claude plugin update` ou
`git clone`.

## 10. Encerrar a demanda

Quando `harness supervise --dir <alvo>` devolve `next: null`, todas as tarefas
passaram. O ciclo tem um fim explícito:

```
harness finish --dir <alvo>
```

Duas metades, nesta ordem:

1. **`audit_closure` — só leitura.** Devolve os bloqueadores do fecho. Nunca
   escreve, nunca executa `verify_cmd`. Os `kind` possíveis:
   `killswitch_active` (a demanda inteira rodou sem governança), `no_contract`,
   `feature_not_passed`, `evidence_missing` (marcação à mão — o passo 13 do
   lifecycle proíbe), `evidence_stale` (o `files_hash` não bate: o código
   mudou depois da prova) e `tree_residue` (tracked sujo fora dos `files[]`).
2. **`sweep_disposables` — só com a auditoria limpa.** Reescreve o
   `.harness/progress.md` como demanda encerrada e esvazia o
   `.harness/scratch/`.

Reprovado, o comando reporta e sai com código 1 **sem varrer nada** — limpar
por cima de um fecho quebrado apagaria o rastro necessário para consertá-lo.

`.harness/work/`, `.harness/evidence/` e o `feature_list.json` ficam intactos:
são o registro auditável. E o comando **nunca toca git** — `git commit`,
`git push` e `gh pr create` estão fora de propósito, porque uma ação
irreversível dentro de um subcomando que está na allowlist do agente
transformaria o próprio `finish` num bypass do runtime floor.

Efeito colateral que importa: o `progress.md` reescrito é o que **destrava o
contrato seguinte**. Sem ele, a sessão nova herdava o estado da demanda
anterior.

## 11. Kill-switch — desligar tudo

Se nada dos escapes da seção 6 resolver, o kill-switch desliga **todos** os
hooks de uma vez. É um comando **seu**, no **seu** terminal:

```powershell
harness disable --dir <alvo> --note "motivo"
harness status  --dir <alvo>
harness enable  --dir <alvo>
```

O estado é o arquivo-sentinela `.harness/harness.disabled` (machine-local,
gitignored). Presente, cada hook gerado — `boundary_guard`, `session_start`,
`stop_hook`, `guard_tests`, `guard_test_runner` — faz no-op no topo do
`main()`.

**O agente não pode se auto-desativar.** Enquanto o harness está ativo, o
`boundary_guard` nega por regra de *floor* tanto criar o sentinel quanto rodar
`harness disable`. Não há paradoxo: a checagem do kill-switch precede tudo,
inclusive o floor, e o floor anti-auto-desativação só roda enquanto o harness
está **ativo**. Você, no terminal próprio, não passa por hook nenhum — o hook
só existe dentro da sessão do Claude Code.

> **Cuidado.** Um kill-switch ligado é **invisível** na sessão: nada avisa,
> nada muda de aparência. Neste repositório o guard ficou em no-op por quatro
> dias sem ninguém notar, e tudo que passou nesse período rodou sem
> governança. **Só `harness status` conta a verdade** — rode antes de tratar
> qualquer sessão como evidência de que a governança valeu. É por isso que
> `harness finish` trata `killswitch_active` como bloqueador de fecho.

`harness status` também devolve a contagem de ciclos `disable`/`enable` desta
máquina — o número que diz se o produto ainda precisa de mais alguma porta de
escape ou se as que existem bastam.

## 12. Deixar o plugin sempre disponível (opcional)

Em vez de repetir `--plugin-dir` toda sessão — e é o ÚNICO jeito de usar o
plugin fora do terminal, ex. no app desktop, que não aceita flags de CLI —
registre um marketplace local apontando pro diretório do plugin.

1. O repo do plugin precisa de um `.claude-plugin/marketplace.json`
   auto-referenciando-se (já existe neste repo — ver
   [`.claude-plugin/marketplace.json`](../../.claude-plugin/marketplace.json)):
   ```json
   {
     "name": "harness-creator-local",
     "owner": { "name": "<seu nome>" },
     "plugins": [
       { "name": "harness-creator", "source": "./", "version": "0.26.0" }
     ]
   }
   ```
2. No `~/.claude/settings.json` do seu usuário (não do projeto), registre o
   marketplace (`extraKnownMarketplaces`, fonte `directory`) e habilite o
   plugin (`enabledPlugins`, formato `plugin@marketplace`):
   ```json
   {
     "extraKnownMarketplaces": {
       "harness-creator-local": {
         "source": { "source": "directory", "path": "C:\\Projetos\\Harness-creator" }
       }
     },
     "enabledPlugins": {
       "harness-creator@harness-creator-local": true
     }
   }
   ```
3. Reinicie o Claude Code (CLI ou app desktop) para carregar o marketplace
   novo — mudança no settings não é recarregada em sessão já aberta.

(Confira a sintaxe atual — `enabledPlugins`/`extraKnownMarketplaces` — no
schema de settings da sua versão; o formato já mudou uma vez antes e pode
mudar de novo entre releases.)

## Resumo do ciclo completo

```
instalar plugin (1x)
        │
        ▼
/harness-creator:preflight  ──► o repo está pronto? READY / NOT_READY
        │
        ▼
/harness-creator:init  no repo-alvo  ──► gera harness.yaml + settings.local.json + hooks + AGENTS.md
        │
        ▼
reabrir sessão do Claude Code nesse repo
        │
        ▼
trabalhar normal — prompts de aprovação aparecem sozinhos conforme a política
        │
        ├─ mudou o yaml? ──► /harness-creator:compile ──► reabrir sessão
        │
        ├─ demanda específica? ──► /harness-creator:plan ──► aprovar contrato ──► compile-contract
        │                                                           │
        │                                                           ▼
        │                                            compile-session (Fase 2: branch
        │                                            contract/<slug> + permissions do raio de
        │                                            impacto + boundary_guard + lifecycle
        │                                            + templates + SessionStart/Stop)
        │                                                           │
        │                                                           ▼
        │                                            harness verify <id> (Fase 3: roda o
        │                                            verify_cmd real, grava evidência e marca
        │                                            passes:true — padrão desde a v0.23.0)
        │                                                           │
        │                                                           ▼
        │                                            /harness-creator:team (Fase 4, opcional:
        │                                            aprovar arquitetura do time 1x →
        │                                            produtor-revisor roda sem novo toque)
        │                                                           │
        │                                                           ▼
        │                                            harness supervise ──► next: null
        │                                                           │
        │                                                           ▼
        │                                            harness finish (audita o fecho, varre
        │                                            descartáveis, destrava o próximo contrato)
        │
        ├─ quer conferir? ──► /harness-creator:audit (conteúdo)
        │                     harness doctor        (instalação)
        │                     harness audit-runtime (artefatos mutáveis)
        │
        └─ guard atrapalhou? ──► extra_allowed_commands · harness profile set ·
                                 harness task add-file  ·  (último caso) harness disable
```

## Referências

- [README.md](../../README.md) — o que o plugin é, CLI completa, instalação
- [TUTORIAL.md](TUTORIAL.md) — do zero à demanda implementada, passo a passo
- [ARCHITECTURE.md](ARCHITECTURE.md) — como o produto é construído por dentro
- [arquitetura-visual.html](arquitetura-visual.html) — diagramas interativos e
  simulador da cascata de decisão do `boundary_guard`
- [CHANGELOG.md](../reference/CHANGELOG.md) — histórico de versões
