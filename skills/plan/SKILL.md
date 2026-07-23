---
name: plan
description: Transforma uma demanda em linguagem natural num contrato aprovável — spec.md (o quê, critérios de aceitação executáveis, unknowns, stop conditions) + Plans.md (o como, tarefas com arquivos e verify_cmd) — e só compila para feature_list.json depois do gate único de aprovação humana.
when_to_use: Quando o usuário descreve uma demanda/feature/mudança e quer transformá-la num contrato formal antes de codificar — pede "planejar", "criar contrato", "gerar spec", "montar o plano de tarefas", ou é redirecionado aqui porque compile-contract rejeitou um contrato não aprovado.
argument-hint: "[descrição da demanda]"
disable-model-invocation: false
---

# Planejar demanda -> contrato aprovável

Você vai transformar a demanda do usuário (argumento `$0`, ou pergunte se
vazio) num contrato `spec.md` + `Plans.md` em `.harness/work/<slug>/`,
seguido do gate único de aprovação humana e da compilação para
`.harness/feature_list.json`.

## Pré-requisito (só se os comandos abaixo falharem)

Não rode uma checagem de import à parte. Se `harness.cli` der
`ModuleNotFoundError`, ISSO que indica falta de `PYTHONPATH`; só então rode
com `$env:PYTHONPATH = "${CLAUDE_PLUGIN_ROOT}\src"` (PowerShell) e repita o
comando.

## Passo 1 — Analisar o repo-alvo

```
python -m harness.cli analyze --dir <alvo>
```

Isso grava `.harness/repo-profile.json` e imprime o profile em JSON.

## Passo 2 — Apresentar o profile e os unknowns

1. Apresente os achados do profile (languages, package_manager,
   test_command, test_glob, extras) numa única tabela curta —
   valor + evidência (arquivo que provou o achado).
2. Cada item em `unknowns[]` vira uma pergunta DIRETA ao usuário (ex.: "não
   detectei comando de teste — qual é?"). Regra dura: um `unknown`
   **confirmado pelo usuário** vira fato do contrato; um `unknown`
   **não confirmado** permanece como `unknown` explícito no `spec.md`.
   PROIBIDO inventar/assumir um valor para preencher um unknown.

## Passo 3 — Entrevista mínima da demanda

Levante, com o usuário, o essencial para escrever o contrato:

1. **Objetivo** — o que muda e por quê, em 1-2 frases.
2. **Critérios de aceitação EXECUTÁVEIS** — cada critério precisa vir
   acompanhado de um comando de prova (ex.: `pytest tests/test_x.py -q`),
   não uma frase de intenção.
3. **Não-objetivos** — o que fica deliberadamente fora do escopo.
4. **Stop conditions** — quando o agente deve parar e devolver ao humano em
   vez de insistir (ex.: "3 falhas consecutivas da mesma suíte de teste").

## Passo 4 — Escrever `spec.md` e `Plans.md`

Antes de escrever, carregue `references/contract-templates.md` (caminho
relativo a esta skill) — ele documenta o formato EXATO que
`src/harness/contract.py` espera, com os templates literais de `spec.md`
e `Plans.md`, as regras de formato do parser, a granularidade de tarefas
em linguagens compiladas e a concorrência em `feature_list.json`. Escreva
`.harness/work/<slug>/spec.md` e `.harness/work/<slug>/Plans.md`
seguindo esse formato **exatamente**, sem divergir. `<slug>` é um
identificador curto kebab-case derivado da demanda.

## Passo 5 — Gate de aprovação (REGRA DURA)

Apresente o `spec.md` e o `Plans.md` completos ao usuário e peça aprovação
explícita. Sempre mostre o caminho relativo (NUNCA o caminho absoluto) dos
dois arquivos como link markdown antes de pedir aprovação (ex.:
`.harness/work/<slug>/spec.md`) — caminho relativo é clicável no client;
sem isso o usuário precisa perguntar onde o contrato está.

> **A skill NUNCA preenche `approved_by`/`approved_at` por conta própria.**
> Esses dois campos ficam vazios no frontmatter até o humano dizer, em
> palavras claras, que aprova o contrato. Só depois disso — nunca antes,
> nunca por inferência, nunca porque "parece óbvio que vai aprovar" — edite
> `spec.md` preenchendo `approved_by` com o nome/identificação do usuário e
> `approved_at` com o timestamp ISO 8601 atual (ex.:
> `2026-07-15T10:00:00Z`).

Se o usuário pedir mudanças, edite `spec.md`/`Plans.md` e repita este passo
até a aprovação explícita.

## Passo 6 — Compilar o contrato

Só depois do frontmatter aprovado (Passo 5), rode:

```
python -m harness.cli compile-contract --dir <alvo> --slug <slug>
```

Mostre a saída JSON ao usuário: caminho do `feature_list.json`, quantas
features foram compiladas, e liste o `verify_cmd` de cada uma (leia
`.harness/feature_list.json` gerado).

Se o comando sair com **exit 1** por contrato não aprovado
(`ContractNotApprovedError`, mensagem "contrato não aprovado"), **volte ao
Passo 5** — não tente contornar o gate de nenhuma forma (não edite o
frontmatter sem aprovação real, não ignore o erro, não escreva o
`feature_list.json` manualmente).

Se o contrato tiver `verify_cmd` de ferramentas de linha de comando com
flags (ex.: `ng test --config=...`), considere rodar com `--dry-run-verify`:

```
python -m harness.cli compile-contract --dir <alvo> --slug <slug> --dry-run-verify
```

Isso roda cada `verify_cmd` distinto com timeout curto e avisa (stderr) se
algum falhar rápido — sinal de possível flag/opção inválida. Dois pontos
importantes: (a) os avisos saem em stderr e NÃO bloqueiam a compilação —
`compile-contract` continua saindo com exit 0; (b) um `verify_cmd` de
tarefa TDD recém-planejada (teste ainda não escrito) TAMBÉM falha rápido
por natureza — um aviso não é necessariamente bug, é sinal pra ler antes
de aprovar o contrato, não pra assumir erro automaticamente.

Se um `verify_cmd` de build/test de linguagem compilada falhar com erro
de arquivo em uso/lock (`MSB3027`, `MSB3021`, `EBUSY`, `Text File Busy`),
é provável que um processo do próprio projeto-alvo esteja rodando em
paralelo (ex.: `dotnet run`, `npm start`) — pergunte ao usuário antes de
encerrá-lo, não assuma.

> **Escopo desta detecção:** a checagem automática de lock/EBUSY só cobre
> chamadas via `harness verify`/`compile-contract --dry-run-verify` (dentro
> de `VerifyFailedError`). Um `MSB3027`/`EBUSY` batido rodando um comando
> ad-hoc durante debug ativo (ex.: `dotnet ef migrations add` manual, fora
> do `verify_cmd` da tarefa) fica fora do alcance da detecção automática —
> reconheça o padrão manualmente nesse caso e pergunte ao usuário antes de
> encerrar qualquer processo.

## Passo 7 — Compilar a sessão autônoma (Fase 2)

Logo depois do `feature_list.json` compilado com sucesso (Passo 6), rode:

```
python -m harness.cli compile-session --dir <alvo>
```

Isso compila, em sequência, os 5 artefatos da Fase 2 a partir do contrato
recém-aprovado e do `repo-profile.json` (se já existir): `.claude/settings.json`
com a superfície `allow` ENUMERADA do contrato, `boundary_guard.py` ativo
como hook `PreToolUse` único de Edit/Write/Bash, `AGENTS.md` com o Agent
Session Lifecycle de 17 passos (mais o detalhe em `.harness/LIFECYCLE.md`),
`claude-progress.md`/`init.sh`/`init.ps1` gerados a partir do profile, e o
hook `SessionStart` registrado (injeta o estado da sessão anterior no
início da próxima sessão).

Mostre ao usuário os artefatos gerados (a saída JSON do comando lista os
paths reais). Deixe explícito que o runtime floor — segredos (`.env`,
`.pem`, `id_rsa`, `*credentials*`), rede não planejada (`curl`, `wget`,
`npm publish`, `pip upload`, `twine upload`, `gh release`) e `git push` —
**nunca** vira `allow`, nem mesmo depois desta compilação: o
`boundary_guard.py` bloqueia essas ações incondicionalmente, com ou sem
contrato ativo.

Se o comando sair com **exit 1** por `.harness/feature_list.json` ausente,
volte ao Passo 6 — `compile-session` nunca roda sem um contrato já
compilado.

## Passo 8 — Teste manual de UI (REGRA DURA — obrigatório se alguma tarefa tocou frontend)

Depois que TODAS as tarefas do contrato passarem (`harness supervise` devolve
`next: null`), se qualquer `files[]` tocou componente/template de UI
(Angular/React/Vue/etc. — o `languages`/`extras` do profile do Passo 1 já
identifica o framework), teste manualmente antes de declarar a demanda
concluída. Testes automatizados (unit/integration/component) verificam
código; não confirmam o que o usuário vai efetivamente ver.

1. Suba a aplicação de verdade (backend real + frontend real + banco real de
   dev, nunca mock) pelo comando documentado no README/AGENTS.md do alvo.
2. Navegue os fluxos dos critérios de aceitação do `spec.md`: o caminho
   normal e pelo menos as bordas citadas explicitamente (validação de erro,
   estado vazio, transição de estado).
3. Capture evidência real — screenshot ou leitura de DOM/texto da página
   confirmando o estado esperado. "os testes automatizados passaram" não é
   evidência de UI. Salve todo arquivo de evidência (PNG, HTML de debug,
   JSON de resposta) em `.harness/scratch/` — o boundary_guard libera
   escrita incondicional lá e a pasta é auto-ignorada pelo git; NUNCA salve
   na raiz do repo-alvo (polui `git status` com artefatos esquecidos).
4. Se achar um defeito só visível em uso real (ex.: locale/formatação,
   campo nunca persistido, elemento não renderizado), corrija antes de
   reportar concluído — use `harness task add-file` (ver
   `references/contract-templates.md`) se precisar tocar um arquivo fora
   da superfície já declarada pela tarefa.
5. Ao reportar ao usuário, diga explicitamente o que foi testado
   manualmente — nunca afirme "testado" sem ter feito.

Isso é ADICIONAL aos `verify_cmd` automatizados de cada tarefa, não os
substitui. Sem UI tocada nas tarefas (mudança só de backend/API/CLI), este
passo não se aplica.

## Regras

- Nunca auto-aprove o contrato: `approved_by`/`approved_at` só são
  preenchidos após o humano confirmar explicitamente, nunca antes.
- Nunca promova um `unknown` a fato do contrato sem confirmação direta do
  usuário — um `unknown` sem confirmação permanece `unknown` no `spec.md`.
- Nunca invente `verify_cmd`, arquivo ou critério de aceitação que não veio
  do profile (com evidência) ou da entrevista com o usuário.
- Se `compile-contract` retornar exit 1 por não-aprovação, volte ao Passo 5
  — nunca contorne o gate.
- Não edite `.harness/feature_list.json` manualmente; ele só nasce de
  `compile-contract`.
- Nunca declare uma demanda que tocou UI como concluída sem o teste manual
  do Passo 8 — suíte automatizada verde não é evidência de que a tela
  funciona (ver Passo 8 para o que conta como evidência real).
