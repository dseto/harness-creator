# Guia de uso — harness-creator

Este guia cobre o **dia a dia**: depois do plugin instalado, como você de fato
usa o harness para fazer uma alteração num projeto.

Para o que o plugin é e como está estruturado, veja o [README](README.md).

## 1. Instalar o plugin (uma vez, por máquina)

```powershell
cd C:\Projetos\Harness-creator
pip install -e .
claude --plugin-dir C:\Projetos\Harness-creator
```

Isso abre uma sessão do Claude Code com as 4 skills disponíveis:
`/harness-creator:init`, `/harness-creator:audit`, `/harness-creator:compile`,
`/harness-creator:plan`.

> Repita `claude --plugin-dir ...` toda vez que abrir o Claude Code para
> trabalhar com harness — não é uma instalação permanente do Claude Code em
> si, é um flag de sessão. (Se preferir permanente, ver seção 7.)

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
- glob dos arquivos de teste (`tests/**/*.py`, `**/*.test.ts`...)
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
  verificação de cada uma.

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
  `files[]`.
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
máquina distinta do `/harness-creator:audit` (seção 8) — aquele faz diff
byte-exato dos artefatos **compilados** (settings/hooks/blocos gerenciados);
este confere os artefatos que mudam a cada sessão de trabalho.

## 8. Verificar se está tudo consistente

```
/harness-creator:audit
```

Score 0–100. Rode depois de qualquer edição manual em `settings.json`,
`AGENTS.md` ou nos hooks — ele detecta *drift* (alguém editou à mão e
divergiu do que o `harness.yaml` geraria) e sugere recompilar.

## 9. Deixar o plugin sempre disponível (opcional)

Em vez de repetir `--plugin-dir` toda sessão, adicione a
`~/.claude/settings.json` do seu usuário (não do projeto):

```json
{
  "plugins": {
    "harness-creator": { "path": "C:\\Projetos\\Harness-creator" }
  }
}
```

(Confira a sintaxe atual de plugins persistentes no `claude --help` da sua
versão — o formato pode mudar entre releases.)

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
        │
        └─ quer conferir? ──► /harness-creator:audit
```
