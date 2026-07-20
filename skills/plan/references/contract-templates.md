# Templates de contrato — `spec.md` e `Plans.md`

Escreva em `.harness/work/<slug>/spec.md` e
`.harness/work/<slug>/Plans.md`, **exatamente** no formato abaixo (é o que
`src/harness/contract.py` parseia). `<slug>` é um identificador curto
kebab-case derivado da demanda.

### Template `spec.md` (frontmatter `approved_by`/`approved_at` SEMPRE vazios nesta etapa)

```markdown
---
slug: <slug>
approved_by:
approved_at:
stop_conditions:
  - "<stop condition 1>"
  - "<stop condition 2>"
---

# Spec: <título da demanda>

## Escopo
<descrição em linguagem natural do que deve ser feito e por quê>

## Critérios de aceitação
- <critério executável 1 — inclua o comando de prova>
- <critério executável 2 — inclua o comando de prova>

## Não-objetivos
- <o que fica fora do escopo>

## Unknowns
- <unknown do profile não confirmado pelo usuário, se houver>
```

### Template `Plans.md`

Cada tarefa é um bloco `## [T-XX] <descrição>` seguido de bullets `files` e
`verify` (ambos obrigatórios — sem eles `parse_plans` levanta
`ContractError` citando o id da tarefa) e `depends` (opcional, lista de ids
de que esta tarefa depende; ausente = lista vazia):

```markdown
## [T-01] <descrição da tarefa 1>
- files: `<arquivo1>`, `<arquivo2>`
- verify: `<comando de verificação executável>`

## [T-02] <descrição da tarefa 2>
- files: `<arquivo3>`
- verify: `<comando de verificação executável>`
- depends: T-01
```

Regras de formato (não divergir — são o que o parser em `contract.py`
espera literalmente):
- O cabeçalho da tarefa é `## [ID] descrição` — o ID vai entre colchetes.
- `files` e `verify` aceitam múltiplos itens entre crases separadas por
  vírgula; se não houver crases, usa split por vírgula simples.
- `verify` usa só o PRIMEIRO valor como `verify_cmd` da tarefa — não
  liste mais de um comando de verificação por tarefa.
- `depends` é uma lista de ids de tarefas (mesma sintaxe de `files`).

### Granularidade de tarefas em linguagens compiladas

Para linguagens com unidade de compilação (C#/.csproj, Java/módulo
Maven-Gradle, Go/pacote, Rust/crate): uma tarefa que toca só PARTE dos
arquivos de uma unidade de compilação nunca fecha `verify_cmd` sozinha —
o `dotnet build`/`mvn compile`/`go build` da unidade inteira só passa
quando TODAS as tarefas daquela unidade tiverem pousado. Duas opções ao
planejar: (a) agrupe tarefas da mesma unidade de compilação num único
`[T-XX]` com todos os arquivos em `files`, ou (b) mantenha tarefas
separadas mas avise no `spec.md` que o `verify_cmd` delas só fica verde
depois que o conjunto todo landar — não é bug do harness, é como
compiladores funcionam; planejar sem isso gera uma tarefa que nunca
verifica isolada.

### Granularidade de tarefas de UI com estado visual condicional

Componente de framework front-end (Angular/React/Vue) com estado visual
condicional (badge/cor/aviso/indicador) quase sempre precisa do arquivo de
estilo (`.scss`/`.css`) além de lógica+template+teste — é fácil planejar
pensando só no comportamento quando o critério de aceitação fala de
"aparência". Ao declarar `files[]` de uma tarefa assim, liste explicitamente
o arquivo de estilo do componente junto com `.ts`/`.html`/`.spec.ts` (ou
equivalentes do framework) — evita descobrir a falta só na implementação e
precisar de `harness task add-file` para corrigir depois.

### Concorrência em `feature_list.json` (times paralelos)

`.harness/feature_list.json` não tem trava de escrita — se múltiplos
agentes/sessões tentam marcar `passes:true` em paralelo no mesmo
arquivo, há corrida. Enquanto o driver multi-sessão da Fase 6
(`docs/roadmap-autonomous.md`, um agente por feature por vez) não
existir, centralize as transições `passes:true` numa única sessão
orquestradora quando trabalhar com múltiplos agentes em paralelo — não
deixe cada agente editar `feature_list.json` por conta própria.

`harness verify <id> --mark-passed` existe para poupar essa sessão
orquestradora de editar `feature_list.json` na mão a cada tarefa: opt-in,
grava `passes:true` só depois de um `verify_cmd` com exit code 0. Serve
para o fluxo sequencial de UMA sessão única — continua sem lock entre
processos, então não use `--mark-passed` com múltiplos agentes escrevendo
o mesmo `feature_list.json` em paralelo.
