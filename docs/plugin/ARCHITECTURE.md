# harness-creator — Arquitetura

> **Fórmula:** `Agente = Modelo + Harness`.
> O modelo fornece o raciocínio; o harness garante execução confiável,
> segurança e governança.

**v0.34.0** · versão navegável e interativa deste documento:
[`arquitetura-visual.html`](arquitetura-visual.html) (abre offline, com
diagramas clicáveis e um simulador da cascata de decisão do
`boundary_guard`).

---

## 1. A decisão fundadora: compilar, não executar

O produto é um **plugin do Claude Code** que cria, avalia e compila estrutura
de harness. A execução fica com o próprio Claude Code.

O desenho anterior — abandonado no pivot de 2026-07 — era um orquestrador
próprio: chamava a API, rodava o modelo em contêiner e aplicava política no
meio. Custava infraestrutura, chave de API, Docker e uma segunda
implementação de tudo que o host já faz.

O desenho atual não tem executor, não tem credencial e não tem runtime
paralelo:

```
.harness/harness.yaml  ──harness compile──►  .claude/settings.local.json  (permissions + hooks)
      (a spec)                               .harness/hooks/*.py          (guards standalone)
                                             AGENTS.md                    (blocos gerenciados)
```

A consequência que importa: o enforcement roda **no mesmo processo que faz as
tool calls**. Não existe caminho por fora.

### Três leis transversais

1. **O repositório é a fonte da verdade.** Todo estado vive em arquivo.
   Sessão fria + injeção no `SessionStart` vence conversa longa — contexto que
   só existe no chat some no primeiro compact.
2. **Prova executável é a única moeda de "pronto".** Não é uma afirmação do
   agente; é um `exit_code == 0` gravado com timestamp e hash do conteúdo
   verificado.
3. **O harness deve barrar o mínimo.** Um `deny` difícil demais empurra o
   operador para o kill-switch, e o kill-switch é desproteção total. Toda
   mensagem de recusa carrega o escape sancionado.

E um princípio que amarra os três: **sem teatro de enforcement**. O que não é
enforçável é declarado advisory. O orçamento de tokens, por exemplo, vira
orientação no `AGENTS.md` com a frase explícita de que o Claude Code não expõe
contagem de tokens a hooks.

---

## 2. Camadas

| Camada | Módulos | Responsabilidade | O que ela NÃO faz |
|---|---|---|---|
| **0 · Host** | Claude Code | Executa: lê `permissions`, dispara hooks, carrega skills e subagentes | — |
| **1a · Skills** | `skills/` (7) | Conduz a conversa com o humano | Não escreve nada direto — toda escrita passa pela CLI |
| **1b · CLI** | `cli.py` | Dispatch dos 29 subcomandos, validação de `--dir` | Não decide `allow`/`deny` em runtime |
| **2 · Compiladores** | `compiler`, `contract`, `analyzer`, `session_permissions`, `lifecycle`, `templates`, `branching`, `profile_edit`, `install_command`, `autoupdate` | Transformam entrada humana em artefato. Determinísticos, zero LLM, zero rede | Não rodam no caminho da tool call |
| **3 · Enforcement** | `boundary_guard`, `session_start`, `stop_hook`, `statusline` | Só o `boundary_guard` decide a cada tool call (`PreToolUse`); os outros três rodam nos eventos `SessionStart`, `Stop` e na chave `statusLine` | Não importam a biblioteca — stdlib puro. Nenhum emite `ask`: esse bucket é de `permissions`, compilado na camada 2 |
| **4 · Prova e controle** | `verify`, `attempts`, `budget`, `convergence`, `escalation`, `skips`, `reconcile`, `regression`, `blind`, `supervisor`, `finish`, `pr_draft`, `spine`, `panel`, `review`†, `teams`† | Produzem e consomem evidência; ordenam o trabalho | Nenhum chama git de escrita; `panel` também não escreve nada; `budget`/`escalation` não bloqueiam — respondem |
| **5 · Diagnóstico** | `preflight`, `audit`, `runtime_audit`, `team_audit`†, `doctor`, `health`, `metrics` | Emitem laudo + o comando exato de correção | Nunca corrigem sozinhos |
| **Base** | `config`, `governance/approval`, `patterns`, `findings`, `settings_paths`, `hook_launcher`, `killswitch` | Cada um é fonte **única** de uma verdade | — |

A tabela nomeia os 45 módulos de `src/harness/` (sem `__init__.py`), mais o
pacote `governance/`. Ela é o mapa completo, não uma seleção: módulo que não
aparece aqui é módulo que ninguém colocou numa camada, e essa é a forma de
dívida que este documento existe para não acumular.

† **Marcados como dormentes.** `teams`, `review` e `team_audit` são a Fase 4
(Produtor-Revisor). Existem, têm suíte, e **nenhum projeto os ativou**: sem
`.harness/team/manifest.json` o veto do revisor no `boundary_guard` é no-op por
construção, e nenhum dos 17 passos do `.harness/LIFECYCLE.md` chama `harness
team`, `harness review` ou `harness audit-team`. Ler as três linhas como
descrição do que roda hoje seria ler errado — ver §10.

### O placar: uma fonte, três renders

`panel.py` (camada 4) não coleta nada — ele lê o que o loop já grava
(`feature_list.json`, `attempts/`, a trajetória de métrica, o sentinel do
kill-switch) e devolve o estado em dados. Os três consumidores renderizam esse
mesmo estado para leitores diferentes: `harness status --brief` (markdown para
o chat, sem ANSI), `harness status --panel` (terminal, cor só em TTY, com
`--watch N`) e o hook de `statusline.py`, que imprime UMA linha para a barra do
Claude Code.

`harness status` **sem flag** continua devolvendo o JSON estruturado do
kill-switch: ele é a fonte de verdade que `session_start` aponta, e o placar
é opt-in por flag justamente para não substituí-la.

A statusline é o único dos três que vive na camada 3: como todo hook, ela roda
fora do pacote instalado, então não importa `panel` — repete uma leitura
deliberadamente magra do estado, sem replicar nenhuma regra de decisão.

### Por que a camada 3 é stdlib puro

Os hooks rodam num processo separado, lançado pelo Claude Code, **fora do
pacote instalado**. Um `import harness` ali quebraria assim que o venv mudasse.
Por isso o compilador **embute o código-fonte** dos guards — inclusive o regex
derivado do `test_glob` e o trecho que lê o contrato — em arquivos
autocontidos.

### Fonte única, nunca tabela duplicada

A duplicação de tabela entre camadas é exatamente o bug que este desenho
existe para prevenir:

- `_POLICY_MATRIX` / `_ALWAYS_GATED` (`governance/approval.py`) — quais classes
  de risco cada modo gateia. O `compiler` importa, não recria.
- `_glob_to_regex` (`patterns.py`) — matching de arquivo de teste, importado por
  `analyzer`, `audit` e `review`, e bakeado nos guards gerados (que não podem
  importar). O `compiler` **não** entra: ele só interpola o `test_glob` como
  texto no `AGENTS.md`, nunca o compila para regex.
- `Finding` / `Report` / `PENALTY` (`findings.py`) — a forma do achado e do
  laudo, compartilhada por `audit`, `runtime_audit` e `team_audit`. Os três
  mecanismos de auditoria são genuinamente distintos; só a estrutura do
  relatório era idêntica byte a byte nos três, e três cópias de um dataclass
  são três chances de as severidades deixarem de significar a mesma coisa.
- `is_floor_bash_command` / `is_floor_secret_path` (`boundary_guard.py`) —
  importados por `session_permissions.py`, para as duas camadas nunca
  divergirem sobre o que é floor.
- `DISABLED_CHECK_SRC` (`killswitch.py`) — o snippet `_harness_disabled()`
  embutido literalmente por cada render de hook.
- `hook_command()` (`hook_launcher.py`) — o único ponto que monta o `command`
  gravado em settings.

---

## 3. A falha aberta, e como ela foi fechada

É o achado de arquitetura mais importante do projeto, porque o modo de falha
era **silencioso e no sentido inseguro**.

Os hooks eram registrados como `python "<script>"` — interpretador **nu**,
resolvido pelo PATH do shell que executa o hook, no instante da tool call. Se
`python` não resolvesse ali (venv desativado, PATH divergente, ou o stub da
Microsoft Store no Windows, que sai com 9009), o processo morria **antes** de o
script rodar.

E a documentação do Claude Code é explícita: apenas `exit 2` bloqueia; qualquer
outro código não-zero é erro **não-bloqueante** e a execução continua.

> Interpretador irresolúvel ⇒ a tool call passa sem runtime floor, sem proteção
> de segredo, sem bloqueio de push, sem gate de evidência. **O guard falha
> aberto**, e a única pista é uma linha de `hook error` no transcript.

A correção não cabia no script: o `boundary_guard` gerado já é fail-closed por
dentro (qualquer exceção durante a avaliação vira `deny`), mas não há como
fechar de dentro do Python o caso em que o Python nunca inicia. A única
superfície de correção é o comando registrado:

```
"<interpretador absoluto>" -S -E "<script>" || exit 2
```

O caminho absoluto vem do `sys.executable` que rodou a compilação (`harness
compile` grava o `boundary_guard`; `harness compile-session` regrava os quatro).
O sufixo `|| exit 2` é sintaxe comum a `sh` e a `cmd.exe`, então o mesmo string
funciona nos dois shells que o Claude Code pode usar — sem gerar arquivo de
lançador, que teria o problema simétrico (`.cmd` não roda sob `sh`, `.sh` não
roda sob `cmd.exe`).

As duas flags não são higiene, são parte do contrato da camada 3. `-S` pula a
varredura de `site-packages`/`.pth`, que custa dezenas de milissegundos **por
tool call** numa máquina com outros projetos Python instalados; `-E` descarta o
`PYTHONPATH` herdado do ambiente que disparou a tool call, porque um hook que
consegue importar do repositório-alvo é um hook que o repositório-alvo pode
reescrever.

`harness doctor` diagnostica o resíduo desse problema: hook registrado cujo
interpretador não existe mais.

---

## 4. O `boundary_guard`: um hook, uma cascata

`boundary_guard.py` substitui o padrão de N guards por ação (um hook por
matcher) por **um único** hook `PreToolUse`, resolvendo a latência de N
subprocessos por tool call.

### Roteamento explícito

O matcher registrado é `"*"`, não `"Edit|Write|Bash"`. Com o matcher restrito,
qualquer tool de escrita fora daquele conjunto (`PowerShell`, `NotebookEdit`,
tools MCP de filesystem) **nunca invocava o hook** — o Claude Code aplicava o
allow implícito antes de o fallback do `main()` sequer rodar.

Alargar o matcher sozinho não bastaria; por isso `main()` roteia
explicitamente:

| Tool | Rota |
|---|---|
| `Edit`, `Write` | `_evaluate_file` (+ caso especial de feature-lock em `feature_list.json`) |
| `MultiEdit` | `_evaluate_file` sobre `tool_input.file_path`, sem o caso especial |
| `NotebookEdit` | `_evaluate_file` sobre `notebook_path`, com fallback para `file_path` |
| `PowerShell` | `_evaluate_powershell` |
| `Bash` | `_evaluate_bash` |
| `Read`, `Glob`, `Grep`, `Task`, `WebFetch`, `TodoWrite`, `TaskCreate`, `TaskGet`, `TaskList`, `TaskOutput`, `TaskStop`, `TaskUpdate` | allowlist fixa read-only/utilitária — passa sem análise |
| qualquer outra | nome com cara de escrita (`write`/`create`/`edit`) → `deny`; resto → **allow logado** |

A família `Task*` está enumerada na allowlist pela razão oposta ao risco
residual abaixo: são tools nativas de acompanhamento de tarefa, não escrevem no
repositório-alvo, e sem a entrada explícita `TaskCreate` cairia no fallback e
seria negada **só por conter `create` no nome**. Aconteceu numa sessão real
deste projeto. A regra por-nome é política mínima, e política mínima erra nas
duas direções — a allowlist é o que corrige o lado do falso-deny.

**Risco residual assumido, por escrito:** uma tool MCP de escrita cujo nome não
contenha `write`/`create`/`edit` (ex.: `mcp__foo__persist`) passa sem análise.
Aceitável no contexto de deploy single-user interno deste plugin; se o conjunto
de MCP servers conectados mudar para incluir ferramentas de terceiros não
confiáveis, esta política mínima deve ser revista.

### A ordem da cascata é a segurança

```
0 · kill-switch      sentinel presente → allow e encerra (precede TUDO, inclusive o floor)
1 · runtime floor    push / rede / segredo / plano de controle / auto-desativação
2 · superfícies      .harness/work · .harness/scratch · progress.md · docs/ · memória do Claude
3 · contrato         ausente → deny (escrita) / bootstrap mínimo (comando); concluído → allow
4 · raio de impacto  test_glob protegido; files[] do contrato ativo
```

**Por que o floor vem antes de tudo.** Se "sem contrato → allow" fosse avaliado
primeiro, qualquer repositório sem `feature_list.json` teria push, rede e
escrita em segredo liberados. Era uma falha real de segurança. O floor é
avaliado primeiro, sem exceção, com ou sem contrato ativo.

**A única exceção do floor** é estreita: `git push` da branch do contrato ativo
(`contract/<slug>`) para ela mesma. `-u`/`--set-upstream` são as únicas flags
**toleradas** — não são exigidas, e um push sem flag nenhuma passa igual; quem
lê "com `-u`" como requisito vai caçar a flag quando o deny vier de outro lugar
(já custou uma investigação inteira: a causa real era metacaractere de shell no
comando). Branch protegida, outra branch, branch indeterminada (detached HEAD,
worktree linkado — postura fail-**closed** aqui), refspec explícito,
`--force`/`--force-with-lease`/`--mirror`/`--delete`/`--all`/`--tags` e push
encadeado a outro comando seguem negados.

### Ancoragem da raiz

O guard não confia no `cwd` do payload — ele se ancora no próprio `__file__`,
que mora sempre em `<repo>/.harness/hooks/`. Um agente que fez `cd frontend/` e
não voltou não desloca a raiz sob a qual a superfície é avaliada. Um
`file_path` **relativo**, porém, é absolutizado contra o `cwd` original do
payload antes da checagem — senão a âncora produziria falso-deny.

### Limites declarados, não esquecidos

- **Floor de segredo** cobre redirecionamento (`>`, `>>`, `tee`) e cmdlets de
  escrita do PowerShell. **Não** persegue escrita indireta via interpretador
  (`python -c "open('.env','w')"`): é corrida armamentista de custo
  desproporcional para este mecanismo.
- Ofuscação do alvo do redirecionamento por concatenação de aspas adjacentes
  (`echo x > ".e"nv`) ou ANSI-C quoting escapa pelo mesmo motivo.
- **Floor de segredo é de escrita, não de leitura.** `cat .env` é liberado —
  ler `.env.example` é rotina — com um AVISO anexado à razão, porque o conteúdo
  entra no contexto da sessão. Repositório que não pode nem ser lido é política
  de permissions (`paranoid`), não de floor.

---

## 5. O contrato como único ponto de autoridade

### Os dois portões, antes do contrato

O ciclo tem duas avaliações read-only que precedem qualquer escrita, e é útil
não confundi-las — uma julga o **repositório**, a outra a **demanda**:

| | `preflight` | `assess` |
|---|---|---|
| Avalia | o repositório está pronto para o harness? | esta demanda é executável aqui? |
| Roda | uma vez por projeto, antes do `init` | uma vez por demanda, antes do `plan` |
| Fontes | git, manifesto, runner de teste, linter | código, docs, git, `.harness/work/` |
| Veredito | `READY` / `READY_WITH_WARNINGS` / `NOT_READY` | `COERENTE` / `PRECISA_ESCLARECER` / `CONFLITANTE` / `FORA_DE_ESCOPO` |
| Bloqueia? | `NOT_READY` | só `FORA_DE_ESCOPO` |
| Implementação | Python (`preflight.py`) — determinístico | prompt (`skills/assess/`) — semântico |

A assimetria de implementação é deliberada. Prontidão de repositório é
verificável por checagem objetiva; aderência de demanda não é. Um `files[]`
apontando arquivo inexistente é normal (arquivo novo); um `verify_cmd` que
falha é normal (TDD). **Todo sinal estático disponível é indistinguível do caso
legítimo** — daí o `assess` ser julgamento, não parser, e daí a Fase 5 propor
um juiz semântico para o contrato em vez de mais validação.

`assess` **não substitui o gate humano** — é insumo para ele. `COERENTE`
significa "não achei impedimento nas quatro dimensões", nunca "deve ser feito".

### O contrato

Toda autoridade humana se concentra em **um** artefato aprovável: o par
`spec.md` (o quê — escopo, critérios executáveis, `stop_conditions`) +
`Plans.md` (o como — tarefas, `files[]`, `verify:`).

```
.harness/work/<slug>/spec.md     frontmatter: slug, approved_by, approved_at, stop_conditions
.harness/work/<slug>/Plans.md    ## [T-01] descrição / - files: ... / - verify: ...
        │
        ▼  harness compile-contract --slug <slug>
.harness/feature_list.json       id, desc, files[], verify_cmd, depends[], cwd, passes
                                 + metric_cmd, metric_target  (opt-in, §4.3)
```

Os dois últimos campos são o único slot opt-in do contrato: tarefa que não
declara `metric` no `Plans.md` nunca os recebe, e o resto do harness se comporta
exatamente como antes. Eles existem para alimentar os vereditos de trajetória do
disjuntor, mais abaixo.

**O gate é enforçado no código, não por instrução.** `compile_contract` levanta
exceção e **não escreve um byte** se `approved_by`/`approved_at` estiverem
vazios.

Cuidado na recompilação: `passes: true` só é preservado se a **identidade** da
tarefa não mudou — a tripla (`id`, `verify_cmd`, `files`). Mudar só a descrição
não invalida evidência já registrada; mudar arquivos ou comando de verificação
invalida, porque a evidência antiga não prova mais nada sobre o novo escopo.

### Feature-lock

Marcar `passes: true` exige, para **cada** feature transicionada, evidência
válida em `.harness/evidence/<contrato>/<id>.json` com `recorded_at` **mais novo
que `git log -1 --format=%cI`**. Vale inclusive para `replace_all`: o guard
simula a transição completa, então uma feature sem evidência não pega carona
numa edição em massa.

Com time `producer`+`reviewer` compilado, o lock **aperta**: exige também
aprovação do revisor mais recente que a evidência. Aprovação obsoleta frente a
uma evidência regravada depois dela → `deny`. Este parágrafo descreve um caminho
**dormente**: a checagem só liga quando `.harness/team/manifest.json` declara os
dois papéis, e esse arquivo não existe em projeto nenhum — sem ele o guard pula
o veto inteiro, com comportamento idêntico ao da Fase 3.

### O disjuntor: a assimetria entre prova e tentativa

O `verify` tinha uma regra explícita — exit code ≠ 0 e **nada** é gravado em
disco. Ela é correta para *evidência*: prova é a moeda de "pronto", e gravar
qualquer coisa no vermelho é como uma fatia não-pronta passa por pronta.

Mas a regra estava sendo aplicada larga demais. Tentativa falha não é prova de
nada — é o *oposto* de uma prova — e jogá-la fora custava caro em dois lugares.
O passo 10 do lifecycle mandava autocorrigir "respeitando as stop conditions",
que eram frases livres no frontmatter: o agente contava de cabeça. Dentro de
uma sessão isso quase funcionava; na sessão seguinte o `progress.md` dizia
*onde* o trabalho parou e nunca *o que já tinha falhado*, e a tentativa 1
recomeçava de boa fé.

A separação agora é por natureza do dado, não por resultado do comando:

| | Vermelho | Verde |
|---|---|---|
| `.harness/evidence/` | nunca | prova, com `files_hash` |
| `.harness/attempts/` | erro cru + `failure_signature` | marcador que encerra a sequência |

`attempts` é append puro e o verde **não apaga** o histórico — ele só encerra a
sequência aberta. `budget` lê esse rastro e devolve **um** veredito entre seis:

| veredito | quando | vem de |
|---|---|---|
| `continue` | ainda há folga | `attempts` |
| `stop_same_failure` | a MESMA assinatura se repetiu até o teto | `attempts` |
| `stop_iterations` | as falhas desde o último verde estouraram o teto | `attempts` |
| `stop_transient_exhausted` | o mesmo erro **transiente** se repetiu até o teto | `attempts` |
| `stop_worsening` | duas medições piores que o melhor já registrado | `convergence` (opt-in) |
| `stop_plateau` | três medições sem superar o melhor | `convergence` (opt-in) |

Os dois vereditos estruturais respondem perguntas deliberadamente diferentes.
`stop_iterations` diz que *o tempo acabou*; `stop_same_failure` diz *o que
fazer* — trocar de abordagem, porque insistir já provou não levar a lugar
nenhum. Contá-los junto os apagaria: um teto atingido e uma abordagem falida
pedem coisas distintas de quem lê o veredito.

**`stop_transient_exhausted` vence qualquer outro veredito**, e a precedência é
a decisão de desenho da seção. Erro de ambiente que se repete não é o loop de
correção batendo num teto (§8.2): é o §8.3 entrando por outra porta. Se
`stop_same_failure` ganhasse a disputa, o loop gastaria o resto do orçamento
reescrevendo código que está correto, guiado por uma falha que nunca esteve no
código. Os dois diagnósticos exigem ações opostas, então o mais específico
precisa ganhar por regra, não por ordem de avaliação acidental.

Os dois vereditos de trajetória vêm de `convergence.py` e existem só quando a
tarefa declarou `metric`. Eles respondem a terceira pergunta do design — não
"chegou?" nem "esgotou?", mas *"está se aproximando ou se afastando?"* — e a
fronteira é estreita de propósito: `target` atingido informa `target_met` e
**não muda veredito nenhum**. A métrica guia; quem decide continua sendo o
`verify_cmd`. `convergence` também nunca executa o `metric_cmd`, nunca chama
git e nunca gera timestamp: recebe tudo pronto, exatamente como
`attempts.record_failure`, porque um módulo de leitura de trajetória que
consegue medir sozinho é um módulo que pode discordar da medição gravada.

A parada tem forma obrigatória, e ela mora em `escalation.py`. Um veredito de
parada com a razão em prosa livre é indistinguível de uma desistência: quem
recebe não sabe o que já foi tentado nem por onde continuar. O módulo renderiza
as seis partes que o §8 exige, na ordem que ele exige (o que se tentava, o que
foi tentado, o último erro cru, a classificação, o estado da spine, o próximo
passo), e as monta **só do que já está em disco** — contrato compilado, rastro
de `attempts`, `git status --porcelain` em leitura. Não decide veredito (isso é
`budget`) e não executa nada.

Duas escolhas de fronteira valem registro:

- **`budget` não bloqueia nada.** Ele responde; quem obedece é o lifecycle.
  Ligar enforcement (hook `Stop` bloqueante, Fase 6) fica sendo uma decisão de
  ativação, não uma reescrita da decisão — mesmo desenho do `supervisor`, que
  desde sempre é leitor síncrono e não daemon.
- **Teto ausente nunca vira "sem teto".** `harness.yaml` ilegível cai no
  default do schema, e condição tipada com `type` desconhecido **reprova a
  compilação** em vez de virar advisory mudo. Rebaixamento silencioso é o modo
  de falha perigoso aqui: o contrato pareceria ter disjuntor sem ter.

### O verde também mente: `skips`

Todo o desenho acima assume que o verde significa alguma coisa, e o exit code
sozinho não garante isso. pytest, `dotnet test` e jest saem **0** com dezenas de
testes pulados, e saem 0 quando não coletaram teste nenhum — o caso em que a
prova é literalmente vazia. Enquanto o `verify` decidia o verde só pelo exit
code, a moeda de "pronto" podia ser cunhada sem lastro.

`skips.py` é a leitura de texto que fecha isso, e é só isso: multi-runner por
padrão de saída (nunca presumindo pytest — há dogfood .NET), nunca executa
processo, nunca decide o que fazer com o resultado. Quem decide é o `verify`,
que já tem o stdout em mão. A separação importa porque a contagem e o motivo têm
disponibilidade diferente: pytest sempre imprime `N skipped`, mas só mostra o
motivo com `-rs`/`-ra`. "Motivo invisível" é um estado declarado
(`reasons_visible=False`), não um erro de parsing — e confundir os dois faria o
harness reportar ausência de motivo como defeito do teste.

O conjunto conhecido de skips é gravado por `harness skips baseline`, **nunca**
pelo `harness verify`. É deliberado: um baseline que o próprio loop pudesse
escrever seria um loop autorizado a normalizar o que acabou de pular.

### A mesma regra em dois momentos: fecho e abertura

`finish.audit_closure` compara estado declarado com estado real e sempre foi o
julgamento certo — no momento errado, sozinho. Rodando só no fecho, ele
encontra a prova vencida depois de a sessão ter passado o dia inteiro
acreditando nela. `reconcile` chama **a mesma função** na abertura; a decisão
que vale registro é a de não escrever um segundo julgamento, porque duas
implementações da mesma regra é exatamente como elas passam a discordar.

O que muda entre os dois momentos não é a regra, é o que conta como problema:

| `kind` | no fecho (`finish`) | na abertura (`reconcile`) |
|---|---|---|
| `evidence_stale` / `evidence_missing` | bloqueador | divergência |
| `tree_residue` / `killswitch_active` | bloqueador | divergência |
| `feature_not_passed` | bloqueador | **estado normal** — é o trabalho a fazer |
| `no_contract` | bloqueador | **bootstrap** — ainda não há o que reconciliar |
| `progress_contract_mismatch` | invisível (o `finish` reescreve o arquivo) | divergência |

As duas linhas em negrito são o desenho: um aviso que aparece em toda abertura
de sessão é um aviso que ensina a ignorar avisos, e `divergences: []` só
significa alguma coisa se não significar "sempre alguma coisa". A última linha é
o inverso — uma divergência que só existe aqui, porque o `finish` regenera o
`progress.md` logo depois de olhar para ele. Foi o defeito da v0.25.0: o
`SessionStart` injetou "nenhuma feature pendente" numa sessão com seis tarefas a
fazer, e nada no harness sabia contradizê-lo.

`reconcile` também não bloqueia — mesma postura do `budget`. A diferença é que
ele não depende de o agente lembrar: o hook `SessionStart` injeta a seção de
aviso antes do resumo de progresso, porque quando o estado declarado não bate,
o resumo logo abaixo é justamente o que não se pode acreditar. O texto do aviso
é renderizado em `harness/reconcile.py` e chega ao hook já pronto (campo
`section`) — o script gerado é stdlib puro (camada 3) e formatar lá dentro
poria a formatação fora do alcance da suíte.

### Re-prova incremental: o que a verificação barata não vê

A verificação de uma fatia é barata porque roda só a prova daquela fatia. O
preço é estrutural: ela não olha para trás, então a fatia 5 pode quebrar a fatia
2 e o `feature_list.json` segue alegando `passes: true` até o gate final — muitas
iterações depois, quando o suspeito já é a demanda inteira.

`regression.run_reproof` fecha o buraco pelo acoplamento DECLARADO: ao fechar uma
tarefa, re-roda o `verify_cmd` das tarefas já provadas cujo `files[]` intersecta o
dela. Não é a suíte completa — essa é a camada 3, e o design a proíbe dentro do
loop de iteração. Não é inferência de import nem de histórico do git: acoplamento
não declarado é defeito do contrato, e `harness task add-file` já o corrige.

Duas decisões carregam o custo:

- **O par (comando, `cwd`) é a unidade, não a tarefa.** Quem é verde ou vermelho é
  o comando; tarefas provadas pelo mesmo comando viram um alvo só, e o comando da
  tarefa atual não é repetido (acabou de rodar verde, na mesma árvore). Num
  contrato cujas tarefas dividem arquivo de teste — o caso comum — essa dedução é
  a maior parte da economia.
- **Vermelho rebaixa; erro de ambiente não.** Prova vermelha devolve
  `passes: false` com tentativa registrada (fila do `supervise`, disjuntor do
  `budget`, bloqueio do `finish`). Timeout ou prova no runtime floor viram `SEM
  VEREDITO`: aparecem no relatório, mas não derrubam registro válido — §8.3
  separa falha de infraestrutura de falha estrutural, e rebaixar por máquina lenta
  destruiria prova legítima.

A evidência antiga da tarefa rebaixada permanece em disco. Ela deixa de bater com
o código e vira `evidence_stale` na tabela acima — informação, não lixo; apagá-la
destruiria o registro do que um dia foi provado. O exit code 2 do `harness verify`
segue a convenção do `budget` e do `reconcile`: veredito de parada, distinto do
erro de execução.

### Spine: três registros, três ciclos de vida

O design pede três arquivos persistentes, e a razão de serem três — em vez de um
"histórico" só — é que morrem em momentos diferentes:

| arquivo | responde | vida | escrita |
|---|---|---|---|
| `progress.md` | onde estamos | a demanda | reescrito por `verify`/`finish`, regenerado a cada contrato |
| `decisions.md` | por que decidimos assim | o projeto | append por `harness decide` |
| `lessons.md` | o que atrapalhou | o projeto | append por `harness lesson` |

Por isso `progress.md` continua em `harness/templates` e os outros dois vivem em
`harness/spine`: juntá-los num módulo só faria um deles herdar a política de
regeneração do outro, e regenerar `decisions.md` a cada demanda nova apagaria
exatamente aquilo que ele existe para guardar.

**Append-only não é preferência de estilo.** Um registro de razões que pode ser
reescrito não prova que a razão gravada é a razão original — e essa prova é a
única coisa que ele tem a oferecer. Mudou de ideia: registra-se uma decisão nova
que supersede a anterior, e a anterior fica, com a data em que foi tomada.

**Quem escreve é o verbo, e isso é consequência do guard, não conveniência.** O
`boundary_guard` barra escrita em `.harness/**` fora de `work/` e `scratch/`
porque plano de controle não se auto-amplia. Logo não existia a opção "o agente
edita o markdown": ou entram `decide`/`lesson` em `_HARNESS_SUBCOMMANDS`, ou
esses dois arquivos nunca são escritos por ninguém. A superfície que os verbos
abrem é estreita — só acrescentam linha no fim.

**Assimetria deliberada na injeção.** As decisões entram no contexto de abertura
(depois do progresso: a hora de saber o que não re-tentar é ao escolher a
próxima fatia). As lições **não** entram. §5.3 é explícito que elas não bloqueiam
retomada, e a razão é mais dura que economia de contexto: uma lista de fricções
no contexto do agente é um backlog que ele tentaria resolver — auto-modificação
do harness pelo próprio agente, a camada que o design manda não construir. Elas
saem no `harness finish`, para o humano.

### Camada 3: o que se mecaniza é a ausência

A escada de verificação do §6 tem três degraus, e os dois primeiros compartilham
um ponto cego: quem escreveu o código escreveu o teste, e é quem declara pronto.

| camada | quando | quem executa | módulo |
|---|---|---|---|
| 1 · sinal rápido | toda iteração | o agente | prosa do lifecycle |
| 2 · prova da fatia | ao fechar a fatia | `harness verify` | `verify` + `regression` |
| 3 · review profundo | uma vez, antes da entrega | um verificador que não implementou | `blind` |

O julgamento da camada 3 é de quem julga — o harness não tem como mecanizá-lo.
O que ele mecaniza é o que o verificador **não** recebe:

- **O pacote é derivado do `feature_list.json`, não redigido.** Aquele arquivo já
  é a projeção limpa do contrato (`desc`, `files[]`, `verify_cmd`); nada do
  `spec.md` chega até ele. Um prompt escrito pelo implementador vaza a
  justificativa por construção, e o §9.1 é explícito que a avaliação nasce
  contaminada nesse caso. O tipo `PackageTask` é a fronteira em código: não tem
  campo para racional, então não há por onde um passar.
- **A lista de "não abra" vem com motivo.** O verificador é um agente com acesso
  ao repositório — os arquivos do racional continuam no disco, e a única defesa
  possível é nomeá-los. "Não leia" sem motivo é a instrução que mais se ignora.
- **O veredito prende o hash do que julgou**, como a evidência de camada 2, e é
  append como `decisions.md` — pelas mesmas duas razões: prova velha não vale
  por prova nova, e reprovação que some é reprovação que se re-litiga.
- **`harness finish` é o dente.** Três `kind` distintos (`blind_review_missing`,
  `blind_review_stale`, `blind_review_failed`) porque cada um manda o humano
  fazer coisa diferente — confundir "ninguém julgou" com "julgaram e reprovaram"
  faz o loop consertar o que ninguém chegou a olhar.

`blind` é módulo próprio, e não uma extensão de `review`: aquele é o state
machine **por feature** do padrão Produtor-Revisor (Fase 4, hoje dormente — ver
§10), com iteração e teto de re-submissão; este é **por demanda**, uma passada,
no gate. A separação também é o que mantém a camada 3 viva enquanto a Fase 4 não
está: fosse `blind` uma extensão de `review`, a verificação independente teria
herdado a dormência do time.

**Limite declarado.** O harness não prova que o subagente recebeu só o pacote —
prova que o pacote existe, que saiu de código, e que o veredito está preso ao
estado que julgou. O resto é o passo 15 do lifecycle. Mesma fronteira do resto do
projeto: invariante vira mecanismo, julgamento vira prosa.

---

## 6. Fronteira machine-local

**Política canônica, uma frase:** *especificação, contrato e prova são
versionados; saída de compilação que carrega dado de máquina é machine-local e
regenerada por `compile`.* A íntegra é a **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md` — fonte
canônica; quando qualquer documento divergir dela, ela vence.

Todo output que o harness mescla em settings carrega dado desta máquina: o
comando de hook leva path **absoluto** (o `cmd.exe` não expande `$VAR`) e a
superfície de sessão enumera arquivos do contrato ativo. Por isso o destino é
`.claude/settings.local.json`, que o Claude Code já lê com precedência sobre o
`settings.json` do time.

Antes desta fronteira o merge caía no `settings.json`, que os projetos-alvo
commitam: **um clone em outro path recebia um `PreToolUse` apontando para um
diretório inexistente — o repositório parecia governado e nenhum guard rodava.**

Duas garantias, ambas idempotentes e não-destrutivas:

1. `prepare_managed_settings` é o **único** ponto por onde os seis escritores
   (`compiler`, `boundary_guard`, `session_start`, `stop_hook`,
   `session_permissions`, `statusline`) resolvem o arquivo — a troca de destino
   não pode ficar pela metade em um deles. O `statusline` é o mais recente e
   grava numa chave de topo (`statusLine`), não sob `hooks`; entrou pela mesma
   porta justamente para que a exceção de formato não virasse exceção de
   destino.
2. `ensure_machine_local_gitignores` escreve as regras em arquivos
   **tool-owned** (`.claude/.gitignore`, `.harness/.gitignore`), nunca no
   `.gitignore` da raiz do usuário.

**Trade-off aceito:** um clone novo **não nasce governado**. É exatamente o que
`harness doctor` existe para acusar.

### Estratégia de merge

Nunca sobrescrever o que o usuário tem. As entradas gerenciadas ficam
registradas em `.harness/compiled-state.json` (mecanismo antigo, reconstruído do
zero a cada `harness compile`) e `.harness/compiled-state-session.json`
(compartilhado pelos hooks de sessão, cada um sob sua própria chave, sempre
preservando as alheias). Recompilar remove as entradas antigas gerenciadas e
insere as novas, preservando regra e hook manuais.

---

## 7. Fluxo de dados de ponta a ponta

```
repositório ──preflight──► READY? ──► analyze ──► repo-profile.json ─┐
                                                                     ├─► session_permissions ──► settings.local.json
harness.yaml ──compile──► permissions                                │                              │
             │            AGENTS.md                                  │                              ▼
             │            boundary_guard.py (install_boundary_guard) │                     boundary_guard.py
             │                                                       │                     session_start.py
demanda ──assess──► laudo ──► spec + Plans ──compile-contract──► feature_list.json ───────┤ stop_hook.py
             │                                                       │                     statusline.py
   (4 fontes)   FORA_DE_ESCOPO      ▲                                │
                     barra          │                                │                              │
                                GATE HUMANO                          │                              ▼
                             (approved_by/at)                        │                     decisão allow/deny
                                                                     │                     por tool call
                                                                     ▼
                                              verify ─┬──► evidence/<contrato>/<id>.json   (verde)
                                                      └──► attempts/<contrato>/<id>.jsonl  (vermelho)
                                                                     │            │
                                                                     │            ▼
                                                                     │      budget ──► veredito
                                                                     │      (escalation formata a parada)
                                                                     ▼
                            feature-lock  ·  regression  ·  supervise  ·  blind  ·  finish
                                                                     │
                                                     blockers: [] ───┼──► commit + push
                                                                     ▼    (branch do contrato)
                                                              pr-draft ──► pr-body.md
                                                                           + gh pr create
                                                                           (o humano abre)
```

Os dois pontos onde o fluxo pode parar antes de qualquer escrita são os
portões: `preflight` com `NOT_READY` e `assess` com `FORA_DE_ESCOPO`. Todo o
resto ou segue, ou para no gate humano do contrato.

`review` não aparece no diagrama de propósito: ele só entra no fluxo de um
projeto que compilou um time, e nenhum compilou (§10). O diagrama descreve o que
roda, não o que existe.

Depois do gate, o fluxo não pede humano de novo. O que autoriza o commit é
`harness finish` com `blockers: []` — condição de máquina, não aprovação de
conversa. A única coisa reservada ao humano no fim é **abrir o PR**, e o
`pr_draft` existe para que isso não exija redigir nada: ele lê o contrato e a
evidência já gravada e devolve corpo e comando prontos.

---

## 8. Diagnóstico: seis laudos, nenhum conserta sozinho

| Comando | Mecanismo | Detecta |
|---|---|---|
| `preflight` | 4 categorias sobre o repo **cru**, read-only | Falta de git, manifest, runner de teste ou linter — antes de instalar |
| `health` | Resolve executável e importa módulo, na abertura | Ferramenta de `verify_cmd` que não responde, governança não compilada, harness em no-op |
| `audit` | **Dogfooding**: recompila em memória e faz diff byte-exato contra o disco | Drift de artefato compilado editado à mão |
| `audit-runtime` | Schema + frescor + invariantes | `passes:true` sem evidência, 2+ features em progresso, `progress.md` ausente |
| `audit-team`† | Catálogo vs. artefatos gerados | Papel órfão, papel sem agente, revisor com `Edit`/`Write` |
| `doctor` | Compara as 3 camadas de distribuição | Versão dessincronizada, compilação ausente, hook que não roda |

† Dormente com o resto da Fase 4 (ver §2 e §10): audita artefatos de time que
nenhum projeto gerou.

`health` é o passo 2 do lifecycle e o único que roda **antes** de qualquer
decisão da sessão. Ele deliberadamente **não** executa o `verify_cmd`: um check
caro vira opcional na prática, e um check opcional não cobre o modo de falha que
ele existe para pegar. Sem ele, ferramenta ausente entra no loop disfarçada de
teste vermelho — e o desenho dá respostas opostas aos dois casos (o disjuntor
classifica um como transiente e o outro como estrutural).

O `audit` não reimplementa as regras do compilador — ele **é** o compilador,
rodado em memória. Regra nova no `compiler.render()` passa a ser auditada de
graça, e nunca há duas definições de "certo".

Esse princípio já se pagou. A issue #61 era um `critical` falso —
`hook_not_registered` para o `guard_tests.py` — em **todo** repositório
compilado: o `compile` registrava o hook e, no mesmo comando, o
`install_boundary_guard` removia o registro, por design. Havia duas rotas de
correção: ensinar o `audit` a conhecer o `boundary_guard`, ou tirar a entrada
do `render()`. A primeira criaria exatamente a segunda definição de "certo"
que este parágrafo existe para impedir. A correção foi na fonte, e o `audit`
não ganhou uma linha. (Atualização T-04/onda-1: o `guard_tests.py` deixou de
ser gerado — o script sem consumidor era peso morto puro; quem entrega o
gate de edição de teste é o `boundary_guard`, por decisão por-tarefa.)

`audit`, `audit-runtime` e `audit-team` saem com código **1** se houver qualquer
finding `critical`, ou se o score cair abaixo de 60. A regra de exit ficou
explícita depois de um caso real: UM `critical` custa 40 pontos, deixava o score
em exatamente 60, e o comando saía 0 — um repositório sem harness nenhum passava
por qualquer gate de CI que olhasse o exit code.

### A exceção: a camada 2 se conserta sozinha

O título desta seção vale para os laudos, não para as três camadas de
distribuição. Delas, a do meio — o `.harness/` compilado — é a única em que
consertar é **determinístico e local**: recompilar é rodar o mesmo compilador
sobre a mesma entrada. Não precisa de rede, não precisa de decisão. Por isso
`autoupdate` a regenera sem pedir, disparado por qualquer subcomando ou pela
abertura de sessão.

A decisão e a execução ficam separadas de propósito: `plan_update()` é pura e
compara **tuplas semver**, nunca `!=`. A distinção importa porque as duas
assimetrias têm respostas opostas — artefato atrás recompila, artefato à frente
só avisa. Um `!=` regrediria o trabalho de outra máquina.

As outras duas camadas não têm esse conserto. O pacote pip é ação de fora do
processo. E a camada 3 — o cache de plugin — carrega as skills na
inicialização e exige rede: qualquer correção só valeria na sessão seguinte.
Sobra avisar, e o aviso vive no `SessionStart` porque é o único ponto que roda
antes de a pessoa começar a trabalhar.

Esse aviso e o `doctor` leem a **mesma** função, `stale_plugin_installs()` —
não duas comparações de versão. É o mesmo princípio da seção 2: a divergência
entre duas tabelas que deveriam concordar é o bug que este desenho existe para
prevenir, e um diagnóstico que discorda do aviso da sessão seria exatamente
isso.

Três invariantes fecham o comportamento automático. Ele **falha aberto** — a
recompilação que morre nunca derruba o comando que a disparou. Ele **nunca
toca git** — daí o `--no-branch` no `compile-session` interno: trocar a branch
do desenvolvedor como efeito colateral de um comando de leitura seria pior que
o artefato velho. E ele **respeita o kill-switch**, porque o sentinel desliga o
harness inteiro, inclusive a parte que se conserta.

---

## 9. Kill-switch: o paradoxo e sua resolução

Estado = arquivo-sentinela `.harness/harness.disabled` (machine-local,
gitignored). Presente, cada hook gerado faz no-op no topo do `main()`.

**Invariante de segurança:** o agente dentro do Claude Code **não pode se
auto-desativar** — enquanto o harness está ativo, o `boundary_guard` tem uma
regra de nível *floor* que nega criar o sentinel e rodar `harness disable`. O
usuário, no terminal próprio, não passa por hook nenhum. Sem paradoxo: a
checagem do kill-switch precede o floor, e o floor anti-auto-desativação só roda
enquanto o harness está **ativo**.

É por isso que `enable`/`disable` ficam **fora** de `_HARNESS_SUBCOMMANDS` no
guard — e é a mesma razão de `harness finish` nunca chamar git: um subcomando na
allowlist do agente que faça ação irreversível vira bypass do floor.

**O risco que sobra é operacional**, não arquitetural — comandos de uso e o
aviso completo sobre esquecer o kill-switch ligado estão em
[GUIDE.md § 11](GUIDE.md) (`harness disable`/`harness status`/`harness enable`).

---

## 10. Estado atual e limites conhecidos

**Fases 1–3 entregues e em uso:** o projeto se governa com o próprio harness —
os contratos em `.harness/work/` deste repositório são o histórico real de uso.

**Fase 4 (Produtor-Revisor) está entregue em código e dormente.** `teams`,
`review` e `team_audit` existem, têm suíte, e os padrões de time estão em
`src/harness/teams/patterns/`. Nada os aciona: não há
`.harness/team/manifest.json` em projeto nenhum, nenhum dos 17 passos do
lifecycle chama `harness team`/`review`/`audit-team`, e sem manifesto o veto do
revisor no `boundary_guard` é no-op por construção. A distinção importa porque
o custo de uma capacidade dormente não é zero — ela aparece em tabela de
arquitetura, em tabela de diagnóstico e no feature-lock, e cada aparição
convida a raciocinar sobre uma proteção que não está ligada. Enquanto ninguém
gerar o manifesto, a Fase 4 é código com teste, não mecanismo em operação.

**Fases 5–7 são backlog documentado** (`docs/roadmap-autonomous.md`), com uma
ressalva: parte do que a Fase 6 previa para o item 3 abaixo já saiu, fora do
roadmap, pelo design de loop engineering. O diagnóstico honesto de onde a
autonomia ainda trava:

1. **O gate de aprovação exige humano.** É enforçado só na compilação;
   mecanicamente nada impede um agente de preencher o frontmatter — pré-contrato
   o guard libera comando. *"A skill nunca se auto-aprova" é instrução, não
   mecanismo.* A Fase 5 fecha por mecanismo: risk-tier determinístico, juiz
   independente em processo frio, `approval_hash` e regra de floor sobre
   `approved_*`. A v0.32.0 **aumentou o que está em jogo** aqui: como o gate
   virou único, aprovar o contrato passou a autorizar também o commit e o push
   da branch. Isso não é folga nova — o que impede o agente de commitar sem
   trabalho provado é `harness finish` com `blockers: []`, condição de máquina
   sobre evidência fresca, e o floor continua barrando branch protegida e
   `--force`. Mas fecha o item 1 por mecanismo virou mais urgente, não menos.
2. **Não existe driver de loop.** `supervisor.py` é leitor síncrono deliberado;
   ninguém encadeia feature→feature, sessão→sessão. O orquestrador real só
   existe hoje dentro do teste E2E.
3. **O sinal existe; falta o consumidor bloqueante.** Este item era, até v0.28,
   "nenhum sinal é consumido por máquina" — e não é mais verdade, como a §5
   descreve em detalhe. `verify` grava toda tentativa FALHA em
   `.harness/attempts/` com `failure_signature`; `stop_conditions` aceita forma
   tipada, compilada para o `feature_list.json` e **contada** por `budget`, que
   devolve um entre seis vereditos; `escalation` dá formato obrigatório à
   parada; `convergence` acrescenta a trajetória opt-in. O que falta é o outro
   lado: **nada obriga**. `budget` responde e o lifecycle obedece por prosa —
   ligar o hook `Stop` bloqueante (Fase 6) é a decisão de ativação que
   transforma o veredito em mecanismo. Enquanto isso, o disjuntor é um
   instrumento que o agente pode escolher não ler.

**Achado central da investigação:** os módulos que resolveriam o item 3 não
tinham dependência dura de Docker nem de chave de API. O que os prendia à era
congelada era o *sinal* que consumiam, não a infraestrutura — e o item 3 acima é
a confirmação empírica: re-plumbados a partir do que já existe em disco
(`attempts/`, `feature_list.json`, `git status`), eles voltaram a funcionar sem
nenhuma infraestrutura nova. O que resta das Fases 5–7 é o mesmo exercício sobre
as primitivas nativas do Claude Code — `--max-budget-usd`, `--resume`,
`--output-format json`, Stop bloqueante, PostToolUse, SubagentStop.

---

## Referências

- [README.md](../../README.md) — o que o plugin é, CLI completa, instalação
- [GUIDE.md](GUIDE.md) — referência do dia a dia, seção por seção
- [TUTORIAL.md](TUTORIAL.md) — do zero à demanda implementada, com exemplos reais
- [arquitetura-visual.html](arquitetura-visual.html) — esta arquitetura em
  diagramas interativos
- [docs/preflight.md](../preflight.md) — detalhe do portão de entrada
- [docs/roadmap-autonomous.md](../roadmap-autonomous.md) — Fases 5–7
- [CHANGELOG.md](../reference/CHANGELOG.md) — histórico de versões
