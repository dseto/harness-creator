# Guia de uso — harness-creator

Este guia cobre o **dia a dia**: depois do plugin instalado, como você de fato
usa o harness para fazer uma alteração num projeto.

Para o que o plugin é e como está estruturado, veja o [README](../../README.md).

## 1. Instalar o plugin (uma vez, por máquina)

O `--plugin-dir` sempre aponta para a **raiz de um clone do repositório** — as
duas opções abaixo só diferem em como você obtém esse clone.

### Opção A: você já tem o repositório

```powershell
cd C:\Projetos\Harness-creator
pip install -e .
claude --plugin-dir C:\Projetos\Harness-creator
```

### Opção B: clonar do GitHub

```powershell
git clone https://github.com/dseto/harness-creator C:\Projetos\Harness-creator
cd C:\Projetos\Harness-creator
pip install -e .
claude --plugin-dir C:\Projetos\Harness-creator
```

> **Não existe atalho por `pip install git+https://...` sozinho.** O wheel
> empacota só `src/harness` (`pyproject.toml`,
> `[tool.hatch.build.targets.wheel]`), então esse comando instala a CLI
> `harness` e mais nada: as skills vivem em `skills/` e o manifesto em
> `.claude-plugin/plugin.json`, ambos na **raiz do repositório**, que o pacote
> não carrega. Apontar `--plugin-dir` para o diretório do pacote instalado
> (`site-packages/harness`) abre uma sessão sem skill nenhuma — e sem erro
> visível, que é o pior modo de falhar. Se você quer só a CLI no terminal (o
> caso de `harness disable`, `harness profile set`, `harness status`), o `pip
> install` remoto basta e o `--plugin-dir` não se aplica.

Ambas abrem uma sessão do Claude Code com as 7 skills disponíveis:
`/harness-creator:preflight`, `/harness-creator:init`,
`/harness-creator:assess`, `/harness-creator:audit`,
`/harness-creator:compile`, `/harness-creator:plan` e
`/harness-creator:team` — esta última dormente (seção 8).

> Repita `claude --plugin-dir ...` toda vez que abrir o Claude Code para
> trabalhar com harness — não é uma instalação permanente do Claude Code em
> si, é um flag de sessão. (Se preferir permanente, ver seção 12.)

> **Se um comando `python -m harness.cli ...` (chamado por alguma skill) der
> `ModuleNotFoundError`**: falta `PYTHONPATH` apontando pro plugin. Em
> PowerShell:
>
> ```powershell
> $env:PYTHONPATH = "$env:CLAUDE_PLUGIN_ROOT\src"
> ```
>
> e repita o mesmo comando. **É `$env:NOME`, não `${NOME}`**: em PowerShell
> `${CLAUDE_PLUGIN_ROOT}` é a sintaxe de variável de *sessão*, não de
> ambiente — ela resolve para vazio e o `PYTHONPATH` acaba valendo `\src`,
> sem nenhum aviso. Não vale a pena rodar essa checagem à parte antes: o
> comando real já falha com o mesmo sinal, e uma checagem separada custaria
> um `Bash` a mais pedindo aprovação sem necessidade.

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
- se quer disciplina TDD (bloquear edição de teste — a execução da suíte
  nunca é gateada, rodar `pytest` quantas vezes for preciso não pede
  aprovação)

Ao final ela escreve `.harness/harness.yaml`, compila, e mostra o que foi
gerado:
- `.claude/settings.local.json` — regras de permissão (`allow`/`ask`).
  Machine-local: leva o path absoluto desta máquina no comando do hook, por
  isso nasce ignorado (`.claude/.gitignore`) e um clone precisa rodar
  `harness compile` antes da primeira sessão
- `.harness/hooks/boundary_guard.py` — instalado por `install_boundary_guard`
  logo depois de `compile_project`, no mesmo comando: a disciplina TDD
  gateia a escrita do teste, não a execução repetida da suíte, por decisão
  por-tarefa (o mecanismo antigo `guard_tests.py`, sempre-`ask`, não é mais
  gerado; e um segundo hook dedicado a `Bash`, `guard_test_runner.py`,
  sempre-`allow`, foi aposentado por medir ~125ms por chamada sem mudar
  nenhuma decisão)
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

> **Antes de qualquer coisa, um contrato.** Desde a v0.22.0 a escrita é
> **default-deny sem contrato ativo**: recém-compilado e sem
> `.harness/feature_list.json`, o `boundary_guard` nega toda edição e libera
> só uma superfície mínima de comando — `git status`/`log`/`diff`/`add`/
> `commit`/`branch --show-current`, os subcomandos do próprio `harness`, e
> utilitários read-only (`cat`, `ls`, `grep`, …). É de propósito: o raio de
> impacto é definido pelo contrato, e sem contrato não há raio. A tabela
> abaixo descreve o dia a dia **com** um contrato ativo (seção 5).

O que muda na prática:

| Você pede | O que acontece | Por quê |
|---|---|---|
| Ler/buscar código (Read/Grep/Glob) | Roda direto, sem prompt | `balanced` libera leitura |
| Editar arquivo declarado em `files[]` da tarefa | Passa (`allow`) | está dentro do raio de impacto aprovado |
| Editar arquivo **fora** de `files[]` | **Bloqueado** (`deny`), com o comando de escape na mensagem (`harness task add-file`) | o raio de impacto é o contrato, não a boa intenção da sessão |
| Editar arquivo de teste (`tests/test_list.py`) | **Bloqueado** (`deny`) enquanto nenhuma tarefa declarar esse arquivo; declarado, passa | hook `boundary_guard.py` — impede alterar o teste pra fazer ele passar, e a autorização é por-tarefa, não um prompt genérico |
| Rodar a suíte inteira (`pytest`) direto | Passa (`allow`), sem prompt — em RED, GREEN, quantas vezes for | hook `boundary_guard.py`: o `verify_cmd` da tarefa está na superfície compilada do contrato — a disciplina TDD gateia a escrita do teste, não sua execução repetida, e pedir aprovação a cada `pytest` seria fricção sem sinal depois que o teste já foi aprovado na escrita |
| Rodar comando de leitura (`git status`, `ls`) | Passa direto | superfície read-only fixa, vale com ou sem contrato |
| Rodar comando não declarado no contrato | **Bloqueado** (`deny`), com as três rotas de escape na mensagem | a superfície de execução também é enumerada do contrato |
| Rede por **shell** (`curl`, `wget`, `npm publish`), escrever em segredo, `git push` fora da branch do contrato | **Bloqueado** (`deny`) sempre, em qualquer política incl. `auto` | runtime floor — não é política, é piso |
| Rede por **tool** (`WebFetch`, `WebSearch`) | **Pede aprovação** (`ask`) sempre, em qualquer política incl. `auto` | não é floor: o `boundary_guard` deixa essas duas tools passarem sem análise, e quem gateia é a classe de risco `network` das `permissions` compiladas — prompt nativo, que você aprova ou nega |

O `boundary_guard` decide `allow`/`deny`, nunca `ask`: a decisão é por-tarefa e
sai da leitura do contrato, então não há o que perguntar — cobre escrita de
teste E execução de comando, num único hook. O `ask` que você vê vem só das
`permissions` compiladas — e você aprova ou nega como qualquer prompt nativo
do Claude Code, sem UI própria do harness.

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
direto e aprovar cada edição uma por uma, o fluxo é `assess` → `plan`.

### 5.1 Avaliar a demanda antes de planejar

```
/harness-creator:assess
```

Emite um laudo **read-only** da demanda contra as quatro fontes de verdade do
projeto: código, documentação, histórico do git e contratos anteriores em
`.harness/work/`. Quatro dimensões — pertinência, coerência, precedente e
executabilidade —, cada achado com `arquivo:linha` ou hash de commit.

| Veredito | Sinal | O que acontece |
|---|---|---|
| `COERENTE` | ✅ OK | segue para o `plan` |
| `PRECISA_ESCLARECER` | ⚠️ WARNING | **segue** — as perguntas viram `unknowns` do `spec.md` |
| `CONFLITANTE` | ⚠️ WARNING | **segue** — o conflito vira decisão registrada no `spec.md` |
| `FORA_DE_ESCOPO` | ⛔ BLOQUEIA | para — não há o que planejar |

**Só `FORA_DE_ESCOPO` barra.** Os outros dois são demandas legítimas com
trabalho pendente, e quem decide se esse trabalho vale a pena é você, no gate
do `plan`. Um deny fácil demais treina o leitor a ignorar o laudo.

Para que serve, concretamente: o `plan` formaliza o que chega e confia no gate
humano — ele não confere se a demanda pertence ao projeto, se já foi feita, ou
se contradiz uma decisão registrada. Sem o `assess`, uma demanda colada por
engano (ou vinda de um ticket de outro sistema) compila num contrato bem
formatado, e o formato é justamente o que faz uma demanda errada parecer
legítima na hora de aprovar.

> **Rode em subagente.** A skill recomenda isso, com número medido: cada
> avaliação consome ~64k tokens de levantamento para produzir um laudo de
> ~1.2k. Inline, ~98% vira ruído na sessão. E o motivo mais forte não é
> contexto: a sessão que acabou de ouvir a demanda não é boa juíza dela — é o
> mesmo princípio de produtor ≠ revisor que a verificação cega da seção 7.6
> aplica no outro extremo do ciclo.

`assess` é read-only e **não substitui o gate de aprovação**: `COERENTE`
significa "não achei impedimento", nunca "deve ser feito".

### 5.2 Transformar a demanda em contrato

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
- **Lifecycle de 17 passos** — bloco gerenciado adicional no `AGENTS.md`, com
  o detalhe em `.harness/LIFECYCLE.md` (ler AGENTS.md → `harness health` →
  ler progresso → ler `feature_list.json` → `harness reconcile` → escolher
  UMA feature e colar o placar → planejar e registrar decisão → implementar →
  `verify_cmd` com re-prova → disjuntor no vermelho → registrar a prova →
  atualizar progresso → marcar concluída → anotar fricção → verificação cega
  e apresentação → commit e push na branch do contrato → deixar a working
  tree limpa). A seção 7 percorre isso em registro operacional.
- **Templates de sessão** (`templates.py`) — `.harness/progress.md` (esqueleto
  runtime, gerado só se ainda não existir) e `.harness/init.sh`/`.harness/init.ps1`
  (determinísticos a partir do `repo-profile.json`).
- **Hook SessionStart** — injeta no início da sessão, nesta ordem: aviso de
  plugin/artefato desatualizado, o veredito do `harness health`, o relatório
  do `harness reconcile`, o resumo do progresso, as decisões recentes do
  `.harness/decisions.md` e o `git log` recente — para a sessão nascer
  sabendo onde parou **e** se pode confiar no que está anotado (seção 7.1).

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
a que `harness compile-session` cria), **apenas** para ela mesma, e **no
máximo** com `-u`/`--set-upstream` — as flags formam uma whitelist do que
*pode* acompanhar o push, não uma exigência: `git push` pelado passa igual, e
qualquer flag fora dessas duas nasce negada. Tudo o mais segue negado — branch protegida,
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

Abra `.harness/harness.yaml` **no seu terminal** (fora do Claude Code — o
`boundary_guard` barra o agente de escrever nesse arquivo: plano de controle
não se auto-amplia) e cole essas duas linhas dentro do bloco `governance:` que
já está lá. Se a chave já existir, acrescente só a linha do `-`. **Vale na
tool call seguinte**, sem recompilar nada.

O bloco que o deny imprime é **condicional, e você deve colar exatamente o que
ele imprimiu**: num repo que já rodou `/harness-creator:init` ele omite o
cabeçalho `governance:`, porque colar a chave duas vezes degrada a lista
inteira para vazia no parser mínimo do hook; num repo que ainda não tem essa
chave (ou nem tem o `harness.yaml`), ele inclui o cabeçalho, senão apontaria
para dentro de um bloco inexistente. E a lista casa por **prefixo**:
`alembic upgrade` libera `alembic upgrade head`, `--sql`, `+1` e o resto dos
argumentos, então uma entrada costuma bastar por ferramenta.

> O floor de escrita em `.harness/**` não é total, e a diferença importa: o
> guard libera `.harness/work/**` (autoria do próximo contrato),
> `.harness/scratch/**` e `.harness/progress.md`, e libera os verbos
> `harness decide`/`lesson`/`blind` justamente porque `.harness/decisions.md`,
> `.harness/lessons.md` e `.harness/blind-review/` não podem ser escritos por
> edição direta. O que é fechado ao agente é o `harness.yaml` e o resto do
> plano de controle.

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

## 7. A sessão de trabalho: abertura → fatia → prova → disjuntor → verificação cega

A seção 6 instalou a **superfície**: o que o agente pode tocar. Esta seção é o
que acontece **dentro** dela — o arco de uma sessão de trabalho, do primeiro
comando ao veredito que libera o commit.

A fonte de verdade é o `.harness/LIFECYCLE.md` (17 passos), escrito para o
agente. O que está abaixo é o mesmo ciclo em registro operacional: o que você
vê acontecer, e o que fazer quando aparece. Quase tudo é automático ou é
comando do agente — o que chega até você são três coisas, e só elas: um
`harness health` vermelho (7.1), uma escalada do disjuntor (7.4) e as lições
em aberto no fecho (7.5).

> **Por que tudo isto virou comando em vez de instrução.** Cada mecanismo
> abaixo substituiu uma frase em prosa que dependia de o agente lembrar —
> "respeite as stop conditions", "confira se o progresso ainda vale", "mostre
> o trabalho a alguém". Instrução que depende de memória não é controle, e o
> modo de falha era sempre o mesmo: silencioso, e visível só no fecho.

### 7.1 Abertura: o ambiente responde? o que está escrito é verdade?

Dois cheques de leitura, passos 2 e 5 do lifecycle. Numa sessão iniciada pelo
Claude Code eles **chegam sozinhos** — o hook `SessionStart` injeta o resultado
antes de tudo, e não injeta nada quando não há o que dizer. Rode à mão quando
o aviso não chegou (sessão retomada, execução fora do Claude Code, hook
desinstalado):

```powershell
harness health    --dir <alvo>
harness reconcile --dir <alvo>
```

**`harness health`** pergunta, numa passada só, se este projeto está em
condições de trabalhar: o executável de cada `verify_cmd` do contrato resolve?
a governança compilada está viva (hook com interpretador válido, settings
presente, `.harness/` na mesma versão)? a proteção está ligada? Exit 0 é
seguir; **exit 2 é parada**. Ambiente quebrado é falha de *infraestrutura*, e
a resposta dela é o oposto da falha de código: não se autocorrige, não melhora
tentando de novo, e **o loop não conserta o próprio harness**. Dependência que
falta se instala com `.harness/init.sh`/`.harness/init.ps1`; problema de
governança ou de proteção **é seu**, no seu terminal. O health check constata
que faltou, nunca resolve.

**`harness reconcile`** compara o que o repositório DECLARA com o que ele TEM.
Exit 0 íntegro, 2 há divergência, 1 não foi possível checar. As divergências e
o que resolve cada uma:

| Divergência | O que significa | O que fazer |
|---|---|---|
| `evidence_stale` | o `files_hash` da prova não bate com o código atual — a tarefa está marcada como feita, mas o código mudou depois | `harness verify <id>` de novo |
| `evidence_missing` | `passes: true` sem arquivo de evidência: alguém marcou à mão | `harness verify <id>` |
| `progress_contract_mismatch` | o `.harness/progress.md` descreve um contrato diferente do `feature_list.json` | `harness compile-session` para regenerá-lo |
| `tree_residue` | sobra tracked de outro contexto na working tree | commitar ou limpar antes de escolher fatia |
| `killswitch_active` | o harness está em no-op | `harness status`, e ver a seção 11 |

`feature_not_passed` e `no_contract` **não** contam como divergência de
abertura, de propósito: tarefa pendente é o estado normal de quem está
começando, e repo sem contrato é bootstrap. Um aviso que aparece em toda
sessão é um aviso que ensina a ignorar avisos.

**Divergência não é ruído a registrar, é trabalho a fazer antes de escolher
uma fatia.** Seguir em cima de anotação errada é exatamente como o trabalho da
sessão anterior se perde — na v0.25.0 o `SessionStart` chegou a injetar
"nenhuma feature pendente" numa sessão com seis tarefas a fazer.

### 7.2 A fatia e o placar

Passo 6: **uma** feature pendente por vez, nunca duas em paralelo na mesma
sessão. É o que mantém o raio de impacto do tamanho de uma revisão.

Nas três fronteiras — abertura de cada iteração, troca de fatia e qualquer
parada — o agente roda e **cola no chat, como saiu**:

```powershell
harness status --brief
```

É a sua janela para o andamento sem precisar ler tool call por tool call:
tarefa quantas de quantas, o que está sendo feito agora, tentativa n de
quantas, se a última prova passou, e o que vem a seguir. O lifecycle
**proíbe** o agente redigir esse bloco de cabeça: a saída é montada por código
a partir do `feature_list.json`, do rastro de tentativas e da evidência, e
placar auto-relatado é self-report — que é justamente o que o resto do harness
existe para não aceitar.

**O placar é opt-in por flag, e não substitui nada.** `harness status` **sem
flag** continua imprimindo o mesmo JSON estruturado de sempre, feito para ser
lido por ferramenta — e é esse JSON, não o placar, que é a fonte de verdade
sobre o kill-switch (seção 11). São perguntas diferentes: `--brief` responde
"onde este loop está?", o JSON responde "a governança está ligada?". Os outros
dois renders da mesma fonte de dados são seus, não do agente, e estão na
seção 11.1.

### 7.3 A prova: `harness verify`

Passos 9 e 11. Depois de implementar a fatia:

```powershell
harness verify <feature-id> --dir <alvo>
```

Isso roda o `verify_cmd` **real** daquela tarefa — o mesmo comando que está no
contrato aprovado, não uma alegação do agente. O comando é conferido contra o
runtime floor antes de rodar (`verify: curl ...` ou `git push ...` sai com
erro e **nunca** é executado, mesmo vindo de um contrato compilado), mas não é
cruzado com o `repo-profile.json`: quem aprova o contrato é quem responde pelo
comando declarado ali. Passando, grava
`.harness/evidence/<contrato>/<feature-id>.json` (contrato, timestamp, comando,
hash) **e já marca `passes: true`** no `feature_list.json` — marcar virou o
default na v0.23.0; `--no-mark-passed` grava só a evidência, e existe para
fleets com vários agentes escrevendo o mesmo arquivo em paralelo. Falhando,
nada de evidência: o vermelho vai para o rastro de tentativas (7.4).

Três flags que resolvem fricção real: `--timeout SEGUNDOS` (default 600 — para
suíte legitimamente lenta, em vez de picotar o `verify_cmd`), `--stream`
(espelha a saída no console em tempo real, para você distinguir suíte lenta de
suíte travada; é opt-in porque streaming sempre ligado jogaria a suíte inteira
no contexto do agente a cada volta) e `--no-reproof`, abaixo.

**Re-prova incremental.** Verde nesta tarefa não é verde no repositório: ela
pode ter quebrado uma fatia já concluída. Por isso o `verify` re-roda também o
`verify_cmd` das tarefas já `passes: true` que compartilham ARQUIVO com esta —
a interseção declarada em `files[]`, nunca a suíte inteira (suíte completa é o
gate final; dentro do loop ela só encarece a volta). Leia o exit code:

- **0** — nada acoplado regrediu.
- **2** — **regressão**: alguma tarefa concluída voltou a falhar. Ela já foi
  rebaixada para `passes: false`, com a tentativa registrada, e volta à fila
  do `harness supervise`. Conserte antes de escolher outra fatia: o diff
  suspeito ainda tem o tamanho de uma iteração, e é aqui que o conserto é
  barato.
- **1** — erro de execução do próprio comando.

Um item `SEM VEREDITO` na saída é falha de ambiente (timeout, prova barrada
pelo runtime floor), não regressão: ninguém é rebaixado, mas aquela prova
**não** foi confirmada — trate como falha de infraestrutura. `--no-reproof`
desliga a checagem, e desligar custa exatamente a detecção de regressão entre
fatias.

**Métrica opcional.** Uma tarefa pode declarar `metric` (e um `target`, ex.:
`>= 0.85`) no `Plans.md` quando "meio pronto" é mensurável por um número que
um comando imprime **e** uma iteração pode piorar o artefato sem o `verify_cmd`
mudar de veredito — fidelidade visual, contagem de erros de lint, migração
grande. Bugfix com teste de regressão não precisa. Presente, o `verify` mede
logo depois do `verify_cmd`, passe ou falhe, e grava a trajetória. **A métrica
guia o loop; quem decide "pronto" continua sendo só o `verify_cmd`** — bater o
alvo informa `target_met` e nunca vira `passes`.

**Feature-lock.** Marcar `passes: true` no `feature_list.json` **sem**
evidência fresca (mais nova que o último commit) é negado pelo
`boundary_guard.py`: o guard nega a edição e devolve a razão ao agente ("rode
harness verify primeiro"). Não dá pra declarar vitória editando a lista de
tarefas na mão. Vale mesmo quando a edição usa `replace_all` (troca todas as
ocorrências de `"passes": false` de uma vez) — o guard simula a transição
completa, não só a primeira, então uma feature sem evidência não pega carona
numa edição em massa que aprova outra.

**Hook Stop.** Se o agente tentar encerrar a sessão com uma feature
`in_progress` cuja verificação nunca rodou ou está falhando, o encerramento
devolve essa razão a ele — que retoma o ciclo ou executa o ritual de handoff.
Quem é avisado é o agente, não você.

### 7.4 O disjuntor: quando parar de tentar

Passo 10. No vermelho o agente corrige e roda de novo sem envolver você — mas
**não indefinidamente, e não por julgamento próprio sobre quando desistir**.

Antes de qualquer contagem, o `harness verify` já tenta sozinho: falha com
sinal reconhecidamente TRANSIENTE (timeout de aplicação, erro de rede ou de
conexão) é repetida até 3×, com pausa curta, sem gravar nada enquanto houver
tentativa sobrando — retry não é correção, é repetição. Se algum retry passar,
a falha nem chega a existir no rastro.

Toda falha **terminal** grava uma linha em
`.harness/attempts/<contrato>/<id>.jsonl`: erro cru, exit code, assinatura da
falha (sha da primeira linha) e classificação. O arquivo nunca é apagado — o
histórico é o produto, e é o que a próxima sessão lê para não repetir a
tentativa 1 de boa fé. A cada vermelho:

```powershell
harness budget --feature <feature-id> --dir <alvo>
```

Só leitura, exit 0 em `continue` e 2 em qualquer parada. Os vereditos:

| Veredito | Quando | O que o agente faz |
|---|---|---|
| `continue` | ainda há folga | corrige e re-roda o `verify_cmd` |
| `stop_same_failure` | a MESMA assinatura se repetiu até o teto | **muda de estratégia** (e diz qual, e por quê) ou escala — o errado é a abordagem, não a execução |
| `stop_iterations` | as falhas desde o último verde estouraram o teto | para, registra o estado no `.harness/progress.md`, devolve o controle |
| `stop_transient_exhausted` | o mesmo erro transiente sobreviveu ao retry automático | **vence todos os outros vereditos**: parada + escalada, nunca healing automático |
| `stop_worsening` | as 2 últimas medições pioraram frente ao melhor valor (só com `metric`) | retoma do melhor estado, que o veredito nomeia (valor e commit) |
| `stop_plateau` | as 3 últimas não bateram novo recorde, oscilação inclusa (só com `metric`) | troca de abordagem ou escala, com a curva registrada |

O transiente vence os demais porque não é o loop de correção batendo num
limite: é falha de ambiente se disfarçando de falha de código, e "corrigir" um
`Connection refused` editando código queima budget consertando o que está
certo.

Os tetos vêm, nesta ordem, das `stop_conditions:` **tipadas** do frontmatter do
`spec.md` (`{type: consecutive_verify_failures, n: 3}`,
`{type: same_failure_signature, n: 3}`) e, na ausência delas, de
`governance.budget.max_green_iterations` do `.harness/harness.yaml`. Tipo
desconhecido não vira advisory mudo: reprova a compilação do contrato. As
`stop_conditions:` escritas em **prosa** continuam valendo como condição
adicional — são elas que cobrem o que nenhuma contagem pega ("a dependência
não existe", "o requisito é contraditório"), e parar por uma delas é acerto,
não desistência.

Em qualquer parada, a saída do `budget` traz o campo `escalation` já
formatado com as seis partes que o design exige, na ordem que ele exige: o que
estava sendo tentado, o que foi tentado, o último erro cru, a classificação, o
estado da spine e a sugestão de próximo passo. É `null` em `continue`, e texto
pronto para colar em qualquer parada — **o agente não redige a escalada à
mão**. É o que chega até você quando o loop desiste.

### 7.5 A spine: decisões e lições

Dois registros append-only, com ciclos de vida diferentes do progresso — o
`.harness/progress.md` morre com a demanda, estes dois vivem com o projeto.
Nenhum dos dois é editável: o guard barra escrita direta, então ou existe
verbo, ou nunca são escritos.

```powershell
harness decide "<titulo curto>" --decision "<o que foi decidido>" --why "<a razao, incluindo a alternativa descartada>"
harness lesson "<a friccao observada>" --fix "<melhoria candidata>"
```

**`harness decide`** (passo 7) é para quando o agente descarta uma alternativa
por razão NÃO óbvia, ou toma uma decisão que restringe as iterações seguintes.
As decisões recentes chegam sozinhas no `SessionStart` da próxima sessão — a
hora de saber o que não re-tentar é ao escolher a fatia. Sem isso, a sessão de
daqui a duas semanas "descobre" e tenta de novo o caminho que esta descartou
por bom motivo. Não é ADR: três linhas bastam, e decisão óbvia não precisa de
registro.

**`harness lesson`** (passo 14) é para a fricção observada durante a sessão —
regra que barrou demais, critério ambíguo, mensagem de erro que não ajudou.
Uma linha, no momento em que acontece, sem interromper o trabalho. **O agente
anota; quem compila é você.** As lições em aberto **não** chegam na próxima
sessão de propósito (não bloqueiam retomada): elas aparecem no campo
`open_lessons` da saída do `harness finish`, e é ali que você as encontra. Um
agente que "aplica" a própria lição editando o harness é auto-modificação — a
camada mais perigosa do design, e a que não vale o risco.

### 7.6 A verificação cega (camada 3 do loop)

Passo 15(a), e o **único ponto de independência que o design chama de
obrigatório**. As camadas 1 e 2 provam que o teste passa; o teste foi escrito
pela mesma cabeça que escreveu o código, e nenhuma das duas pergunta se o que
foi entregue é o que a demanda prometia.

> Nada a ver com a "camada 3" da seção 9, que é a camada de *distribuição*
> (o cache de plugin do Claude Code). Homônimos vindos de dois documentos de
> design diferentes; esta aqui é a terceira camada de *verificação*.

Três passos:

```powershell
harness blind package --dir <alvo>
harness blind verdict --pass --evidence "conferi src/x.py:42 contra T-01" --dir <alvo>
harness blind verdict --fail --evidence "T-01 nao cobre o caso vazio"    --dir <alvo>
```

1. `harness blind package` monta `.harness/scratch/blind-package.md` a partir
   do contrato: `desc`, `files[]` e `verify_cmd` de cada tarefa, e nada mais.
2. O agente despacha **esse arquivo, como está**, para um subagente novo — um
   verificador de contexto limpo, que não implementou nada. Fora do pacote, de
   propósito: `spec.md`, `.harness/progress.md`, `.harness/decisions.md`,
   `.harness/lessons.md`, o `git log` e o resumo da conversa. São o raciocínio
   de quem implementou, e o verificador que os lê valida as mesmas suposições
   que produziram o erro. O pacote é montado por código exatamente para
   ninguém precisar redigir esse prompt.
3. O veredito volta por `harness blind verdict`. `--evidence` é obrigatório
   (o quê e ONDE, em `arquivo:linha`): veredito sem evidência gera
   re-tentativa cega. Exit 2 é reprovação — resultado legítimo do passo, não
   falha do comando. Gate que só sabe aprovar não é gate.

Reprovado, **o verificador não conserta**: o veredito volta ao loop, quem
corrige é quem implementa, e depois disso um veredito novo é registrado. O
anterior fica no histórico — reprovação que some é reprovação que se
re-litiga. O veredito prende o hash do que julgou, então código alterado
depois o torna obsoleto, e o fecho cobra outro.

Limite declarado: o harness **não** prova que o subagente recebeu só o pacote.
Ele garante que o pacote existe em disco, foi derivado por código, e que o
veredito está preso ao estado que julgou. A disciplina do despacho é do passo
15. Mecanismo onde dá, prosa onde não dá.

### 7.7 Auditar os artefatos que mudam a cada sessão

```
harness audit-runtime --dir <alvo>
```

Audita os artefatos runtime-mutáveis (`.harness/progress.md`,
`feature_list.json`, `evidence/`): schema, frescor e invariantes (1 feature
`in_progress` por vez; todo `passes:true` com evidência válida). É uma
máquina distinta do `/harness-creator:audit` (seção 9) — aquele faz diff
byte-exato dos artefatos **compilados** (settings/hooks/blocos gerenciados);
este confere os artefatos que mudam a cada sessão de trabalho.

## 8. Montar um time de agentes com revisão independente (Fase 4) — DORMENTE

> **Leia isto antes da seção inteira.** A Fase 4 **existe e é testada, mas não
> está em uso**: nenhum projeto conhecido tem `.harness/team/manifest.json`,
> nenhum dos 17 passos do `.harness/LIFECYCLE.md` aciona `team`, `review` ou
> `supervise`, e **sem manifesto o veto do revisor no `boundary_guard` é
> no-op** — `_manifest_requires_review` só devolve `True` quando o manifesto
> declara os papéis `producer` **e** `reviewer`, então na ausência dele o
> feature-lock se comporta exatamente como na Fase 3.
>
> **A independência que está em uso hoje é a verificação cega da seção 7.6**
> (`harness blind`), que é o ponto obrigatório do design de loop engineering e
> roda em toda sessão, sem time nenhum. Se você quer produtor ≠ revisor, é
> para lá que deve olhar primeiro.
>
> O que segue é a descrição de uma capacidade construída e pronta, e o
> caminho para ativá-la se você decidir que quer. Não é o fluxo padrão.

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

A partir daí — **e só a partir daí**, com o manifesto em disco — o ciclo
operacional roda sem novo toque humano: o produtor implementa a feature;
`harness verify <feature-id> --dir <alvo>` (seção 7.3) grava evidência fresca
e o subcomando aciona `supervisor.on_feature_verified`, que submete à revisão
sozinho — não precisa rodar `review ... submit` manualmente. Esse gancho é
chamado em toda passada do `verify`, com ou sem time, e sai calado no
primeiro `if` quando não há manifesto: hoje, portanto, ele nunca faz nada.
Com o padrão
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
regressão. **É esse o estado de todo projeto hoje**, e é por isso que a seção
inteira está marcada como dormente: `harness supervise` continua útil sozinho
(a fila que respeita `depends[]`, usada na seção 10), mas `team`, `review` e
`audit-team` só saem do papel depois do passo 4 acima.

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

```powershell
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

### Atualização transparente dos artefatos

Das 3 camadas acima, a do meio — o `.harness/` compilado do projeto — não
depende mais de ninguém lembrar de recompilar. Quando ela está atrás do
pacote pip instalado, o harness regenera os artefatos sozinho, por dois
gatilhos:

- **qualquer comando `harness` naquele repositório**, o que inclui as skills
  `/harness-creator:*` (elas chamam a CLI);
- **abrir uma sessão do Claude Code**, via hook `SessionStart`.

O que ele roda é `harness compile` e, se houver contrato ativo,
`harness compile-session --no-branch`. A saída é uma linha em stderr
(`harness: artefatos recompilados 0.29.0 -> 0.30.0`); pelo gatilho de sessão,
o aviso também entra no contexto injetado, porque atualização silenciosa é a
mesma classe de problema do kill-switch invisível.

Cinco limites, todos deliberados:

| Situação | Comportamento |
|---|---|
| `.harness/` **à frente** do pacote pip (outra máquina compilou) | Só avisa. Nunca regride artefato |
| Recompilação falha (venv recriado, disco em erro) | Aviso em stderr; o comando que a disparou segue normalmente |
| Kill-switch ligado (`.harness/harness.disabled`) | Não roda — o sentinel desliga o harness inteiro, inclusive isto |
| `harness doctor`, `status`, `enable`, `disable`, `compile`, `compile-session` | Isentos. Os dois primeiros grupos precisam do estado real; os dois últimos são o próprio alvo |
| `HARNESS_AUTO_UPDATE=0` no ambiente | Desliga o comportamento. É machine-local, e por isso variável de ambiente e não chave do `harness.yaml` |

Duas coisas que ele **não** faz. Não cria nem troca a branch de contrato: por
isso o `--no-branch`, e por isso quem está em `main` continua em `main`. E não
compila pela primeira vez um clone que nunca rodou `harness compile` nesta
máquina — esse caso continua sendo issue do `doctor`, com o comando exato.

Limitação assumida: a sessão que dispara a recompilação já carregou os hooks e
o `settings.local.json` anteriores. Os arquivos novos valem a partir da sessão
seguinte.

### A camada 3 avisa, e não bloqueia

O cache de plugin do Claude Code — as skills `/harness-creator:*` — não pode
se auto-atualizar: `claude plugin update` exige rede, e as skills são
carregadas na inicialização da sessão. O que o harness faz é **avisar na
abertura da sessão**, com tudo que a pessoa precisa para agir: o que está
velho, o comando exato numa linha própria para copiar, e o aviso de que é
preciso reiniciar.

Bloquear tool calls enquanto o cache estiver velho foi avaliado e
**descartado**. As quatro razões, registradas para a decisão não voltar como
sugestão a cada revisão:

1. **Auto-trava no release.** Bumpar o pacote torna o cache obsoleto no mesmo
   instante — o próprio commit de bump seria a última ação possível no
   repositório.
2. **Não existe superfície estreita para negar.** Skills são arquivos de
   prompt, não tool calls: não passam pelo `PreToolUse`. A escolha seria entre
   não bloquear nada e bloquear tudo.
3. **Não há conserto dentro da sessão.** O deny ficaria de pé até a sessão
   morrer, e empurraria a pessoa para `harness disable` — kill-switch é
   desproteção total, bem pior que uma skill velha.
4. **Skill desatualizada não fura gate nenhum.** O enforcement vive nos hooks
   (camada 2) e na CLI (camada 1), ambos correntes. A camada 3 é consultiva.

O aviso some quando o plugin está em dia, quando `installed_plugins.json` não
existe (normal em quem usa `--plugin-dir` ou só pip) e quando o plugin está à
frente do pacote — nesse caso o `doctor` emite uma nota, porque `claude plugin
update` não corrige cache adiantado. `HARNESS_AUTO_UPDATE=0` **não** silencia o
aviso: essa variável desliga o agir, não o informar.

## 10. Encerrar a demanda

Quando `harness supervise --dir <alvo>` devolve `next: null`, não há mais
fatia pronta a trabalhar. Isso normalmente significa que todas as tarefas
passaram, mas não só: `next: null` também sai quando o `feature_list.json`
está ausente ou ilegível, e quando toda tarefa pendente tem `depends[]`
insatisfeito (inclusive dependência para um id que não existe, que nunca fica
pronta). Quem confirma o fecho é o `finish`, abaixo, não o `supervise`. O
ciclo tem um fim explícito:

```
harness finish --dir <alvo>
```

Duas metades, nesta ordem:

1. **`audit_closure` — só leitura.** Devolve os bloqueadores do fecho. Nunca
   escreve, nunca executa `verify_cmd`. Os `kind` possíveis:
   `killswitch_active` (a demanda inteira rodou sem governança), `no_contract`,
   `feature_not_passed`, `evidence_missing` (marcação à mão — o passo 13 do
   lifecycle proíbe), `evidence_stale` (o `files_hash` não bate: o código
   mudou depois da prova), `tree_residue` (tracked sujo fora dos `files[]`) e
   os três da camada 3 (seção 7.6): `blind_review_missing` (nenhum veredito —
   só quem implementou olhou a entrega), `blind_review_stale` (o veredito é
   anterior ao código atual) e `blind_review_failed` (o verificador
   independente reprovou).
2. **`sweep_disposables` — só com a auditoria limpa.** Reescreve o
   `.harness/progress.md` como demanda encerrada e esvazia o
   `.harness/scratch/`.

A saída traz ainda o campo **`open_lessons`**: as fricções que o agente
registrou com `harness lesson` durante a demanda (seção 7.5) e que ninguém
compilou. Elas **não** bloqueiam o fecho — de propósito, porque melhoria de
harness não é pré-requisito de entrega — mas é aqui, e só aqui, que você as
encontra. Ler essa lista é o momento de decidir o que vira issue.

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

**Ordem obrigatória: rode isto ANTES do commit, ainda na branch do
contrato** — não depois do merge. `harness finish` não toca git, então
rodá-lo cedo não tem custo; rodá-lo tarde (pós-merge, em `main`) sempre
deixa a reescrita do `progress.md` como sobra não commitada numa branch
protegida, obrigando um commit manual só pra fechar o contrato. Resolva os
`blockers` ali mesmo (`harness verify <T-ID>` de novo se `evidence_stale`)
— o `progress.md` já reescrito entra no mesmo commit.

### Um gate humano, e o PR entregue pronto

O ciclo tinha três paradas humanas: aprovar o contrato, pedir a
implementação, aprovar o commit. Tem **uma**.

Aprovar o contrato já autoriza o trabalho que ele descreve. Verificar tarefa
a tarefa já prova o commit. O que substitui o antigo gate do commit é
`harness finish` com `blockers: []` — que só sai assim com toda tarefa em
`passes: true` e evidência cujo `files_hash` bate com o código atual. Sem
isso, o agente para e chama o humano.

Com a auditoria limpa, o agente commita e empurra a branch do contrato
sozinho. O runtime floor não foi afrouxado para isso: o push continua sendo
só de `contract/<slug>` para ela mesma, sem `--force`, e commit em branch
protegida segue barrado — o `chore` de versão e CHANGELOG continua sendo do
humano.

**Abrir o PR nunca é ação do agente.** O que ele entrega é o trabalho pronto
para isso:

```
harness pr-draft --dir <alvo>
```

O comando grava `.harness/scratch/pr-body.md` a partir do contrato — título
tirado do `# Spec:`, tabela de tarefas com `verify_cmd` e estado da
evidência — e imprime o `gh pr create` exato, com `--body-file` (nunca
`--body` inline: acentuação em linha de comando no PowerShell 5.1 corrompe
multi-byte). As seções marcadas `PREENCHER` ficam para o agente escrever: o
racional não é derivável do contrato, e é a parte que faz alguém entender o
PR.

## 11. Kill-switch — desligar tudo

Se nada dos escapes da seção 6 resolver, o kill-switch desliga **todos** os
hooks de uma vez. É um comando **seu**, no **seu** terminal:

```powershell
harness disable --dir <alvo> --note "motivo"
harness status  --dir <alvo>
harness enable  --dir <alvo>
```

O estado é o arquivo-sentinela `.harness/harness.disabled` (machine-local,
gitignored). Presente, **cada um dos quatro hooks gerados** —
`boundary_guard.py`, `session_start.py`, `stop_hook.py` e `statusline.py`
(seção 11.1) — faz no-op no topo do `main()`.

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

### 11.1 O mesmo comando, com o placar de andamento

`harness status` **sem flag** é o que está descrito acima: JSON estruturado,
fonte de verdade do kill-switch, feito para ser lido por ferramenta. Ele não
mudou e não muda.

O **placar de andamento** é opt-in por flag, e responde outra pergunta — não
"o harness está ligado?", mas "onde este loop está?":

```powershell
harness status --brief --dir <alvo>            # markdown, para o agente colar no chat
harness status --panel --dir <alvo>            # painel de terminal, cor só em TTY
harness status --panel --watch 5 --dir <alvo>  # re-render a cada 5s num segundo terminal
```

Os dois renders saem do mesmo estado: progresso `X/N`, tarefas com estado,
tarefa atual com `tentativa n/teto`, a primeira linha do erro da última prova,
a trajetória da métrica quando a tarefa tem uma, e o próximo passo. `--brief`
nunca emite ANSI (o chat mostraria os escape codes como lixo); `--panel` só
colore quando a saída é um TTY, então redirecionar para arquivo dá texto puro.
Pedir `--brief` e `--panel` juntos é erro de uso, e `--watch` é do painel.

O terceiro render é a statusline: `harness compile-session` instala
`.harness/hooks/statusline.py` e registra a entrada `statusLine` no settings
machine-local. Statusline que **você** configurou nunca é sobrescrita.

> Por que o placar não virou a saída padrão: quem consome `harness status` por
> script lê o JSON, e é esse JSON que responde se a governança estava ligada.
> Um painel bonito no lugar dele trocaria a fonte de verdade por estética.

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
       { "name": "harness-creator", "source": "./", "version": "0.34.0" }
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
        ├─ demanda específica? ──► /harness-creator:assess ──► laudo da demanda
        │                          (COERENTE / WARNING / ⛔ FORA_DE_ESCOPO barra)
        │                                   │
        │                                   ▼
        │                          /harness-creator:plan ──► aprovar contrato ──► compile-contract
        │                                                           │
        │                                                           ▼
        │                                            compile-session (Fase 2: branch
        │                                            contract/<slug> + permissions do raio de
        │                                            impacto + boundary_guard + lifecycle
        │                                            + templates + SessionStart/Stop)
        │                                                           │
        │                                                           ▼
        │                                            ┌── a sessão de trabalho (seção 7) ──┐
        │                                            │ harness health     (o ambiente     │
        │                                            │ harness reconcile   responde? o    │
        │                                            │                     escrito vale?) │
        │                                            │        │                           │
        │                                            │        ▼                           │
        │                                            │ escolher UMA fatia                 │
        │                                            │ harness status --brief             │
        │                                            │        │                           │
        │                                            │        ▼                           │
        │                                            │ implementar → harness verify <id>  │
        │                                            │ (verify_cmd real + re-prova das    │
        │                                            │  tarefas acopladas; grava evidência│
        │                                            │  e marca passes:true)              │
        │                                            │        │                           │
        │                                            │  vermelho? ──► harness budget      │
        │                                            │                --feature <id>      │
        │                                            │                continue / stop_*   │
        │                                            │        │                           │
        │                                            │        ▼                           │
        │                                            │ harness decide / harness lesson    │
        │                                            │        │                           │
        │                                            │        ▼                           │
        │                                            │ harness blind package → subagente  │
        │                                            │ harness blind verdict --pass|--fail│
        │                                            └────────────────────────────────────┘
        │                                                           │
        │                                                           ▼
        │                                            (Fase 4 DORMENTE, seção 8: time de
        │                                            agentes existe e é testado, nenhum
        │                                            projeto o ativou)
        │                                                           │
        │                                                           ▼
        │                                            harness supervise ──► next: null
        │                                                           │
        │                                                           ▼
        │                                            harness finish (audita o fecho, varre
        │                                            descartáveis, destrava o próximo contrato)
        │                                                           │
        │                                                           ▼
        │                                            commit + push da branch do contrato
        │                                            harness pr-draft ──► você abre o PR
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
