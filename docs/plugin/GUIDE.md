# Guia de uso — harness-creator

Este guia cobre o **dia a dia**: depois do plugin instalado, como você de fato
usa o harness para fazer uma alteração num projeto.

Para o que o plugin é e como está estruturado, veja o [README](../../README.md).

## 1. Instalar o plugin (uma vez, por máquina)

```powershell
cd C:\Projetos\Harness-creator
pip install -e .
claude --plugin-dir C:\Projetos\Harness-creator
```

Isso abre uma sessão do Claude Code com as 5 skills disponíveis:
`/harness-creator:init`, `/harness-creator:audit`, `/harness-creator:compile`,
`/harness-creator:plan`, `/harness-creator:team`.

> Repita `claude --plugin-dir ...` toda vez que abrir o Claude Code para
> trabalhar com harness — não é uma instalação permanente do Claude Code em
> si, é um flag de sessão. (Se preferir permanente, ver seção 10.)

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
- `.claude/settings.json` — regras de permissão (`allow`/`ask`)
- `.harness/hooks/guard_tests.py` e `guard_test_runner.py`
- bloco gerenciado em `AGENTS.md`

**Importante: feche e reabra a sessão do Claude Code nesse projeto.**
`settings.json` só é lido na inicialização — a sessão que rodou o `/init` não
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
o diff do `settings.json` — o que entrou/saiu. **Reabra a sessão** de novo
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

Isso compila a **Fase 2** do roadmap (Execução Autônoma no Raio de Impacto):

- **Permissions da sessão** (`session_permissions.py`) — `allow` enumerado
  (nunca genérico) para exatamente a superfície que o contrato aprovado usa:
  `Edit`/`Write` nos `files[]` das tarefas, os `verify_cmd` e comandos de
  lint/build do profile, instalação de dependência do `package_manager`
  detectado, e git local do ritual (`status/log/diff/add/commit`).
- **`boundary_guard.py`** — hook `PreToolUse` único que substitui (e remove,
  quando presente) o hook antigo `guard_tests.py`: cobre Edit/Write/Bash numa
  só passada em vez de N guards por ação, decidindo `allow`/`deny` a partir
  da superfície do contrato ativo. Traz proteção contra enfraquecimento de
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
- **Lifecycle de 16 passos** — bloco gerenciado adicional no `AGENTS.md`
  (ler AGENTS.md → rodar `init.*` → ler progresso → escolher UMA feature →
  implementar → verificar → autocorrigir → registrar evidência → commit em
  estado retomável → deixar a working tree limpa).
- **Templates de sessão** (`templates.py`) — `claude-progress.md` (esqueleto
  runtime, gerado só se ainda não existir) e `init.sh`/`init.ps1`
  (determinísticos a partir do `repo-profile.json`).
- **Hook SessionStart** — injeta no início da sessão o resumo do progresso,
  a feature ativa e o `git log` recente, para a sessão nascer sabendo onde
  parou.

**O runtime floor nunca vira `allow`**, com ou sem contrato ativo: leitura de
segredos (`.env`, `.pem`, `id_rsa`, `*credentials*`), rede/publicação não
planejada (`curl`, `wget`, `npm publish`, `pip upload`, `twine upload`, `gh
release`) e `git push` continuam fora da superfície liberada — são
verificados incondicionalmente, antes de qualquer outra checagem do
`boundary_guard.py`.

## 7. Verificar a implementação (Fase 3 — loop de auto-verificação)

Depois de implementar uma feature do contrato ativo, rode:

```
harness verify <feature-id> --dir <alvo>
```

Isso roda o `verify_cmd` **real** daquela tarefa (o mesmo comando do
contrato, validado contra o profile) — não é uma alegação do agente, é
execução de fato. Só se passar é que grava
`.harness/evidence/<feature-id>.json` (timestamp, comando, hash). É o passo
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
registra o estado no `claude-progress.md` e devolve com diagnóstico.

O hook **Stop** fecha o loop da sessão: se o agente tentar encerrar com uma
feature `in_progress` cuja verificação nunca rodou ou está falhando, o
encerramento devolve essa razão a ele — que retoma o ciclo ou executa o
ritual de handoff. De novo, quem é avisado é o agente, não você.

```
harness audit-runtime --dir <alvo>
```

Audita os artefatos runtime-mutáveis (`claude-progress.md`,
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

```
/harness-creator:audit
```

Score 0–100. Rode depois de qualquer edição manual em `settings.json`,
`AGENTS.md` ou nos hooks — ele detecta *drift* (alguém editou à mão e
divergiu do que o `harness.yaml` geraria) e sugere recompilar.

## 10. Deixar o plugin sempre disponível (opcional)

Em vez de repetir `--plugin-dir` toda sessão — e é o ÚNICO jeito de usar o
plugin fora do terminal, ex. no app desktop, que não aceita flags de CLI —
registre um marketplace local apontando pro diretório do plugin.

1. O repo do plugin precisa de um `.claude-plugin/marketplace.json`
   auto-referenciando-se (já existe neste repo — ver
   [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)):
   ```json
   {
     "name": "harness-creator-local",
     "owner": { "name": "<seu nome>" },
     "plugins": [
       { "name": "harness-creator", "source": "./", "version": "0.15.0" }
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
   novo — mudança em `settings.json` não é recarregada em sessão já aberta.

(Confira a sintaxe atual — `enabledPlugins`/`extraKnownMarketplaces` — no
schema de settings da sua versão; o formato já mudou uma vez antes e pode
mudar de novo entre releases.)

## Resumo do ciclo completo

```
instalar plugin (1x)
        │
        ▼
/harness-creator:init  no repo-alvo  ──► gera harness.yaml + settings.json + hooks + AGENTS.md
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
        │                                            compile-session (Fase 2: permissions do
        │                                            raio de impacto + boundary_guard + lifecycle
        │                                            + templates + SessionStart)
        │                                                           │
        │                                                           ▼
        │                                            harness verify <id> (Fase 3: roda o
        │                                            verify_cmd real, só grava evidência com
        │                                            prova executável)
        │                                                           │
        │                                                           ▼
        │                                            /harness-creator:team (Fase 4: aprovar
        │                                            arquitetura do time 1x → produtor-revisor
        │                                            roda sem novo toque humano)
        │
        └─ quer conferir? ──► /harness-creator:audit
```
