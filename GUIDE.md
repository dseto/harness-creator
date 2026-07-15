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

Isso abre uma sessão do Claude Code com as 3 skills disponíveis:
`/harness-creator:init`, `/harness-creator:audit`, `/harness-creator:compile`.

> Repita `claude --plugin-dir ...` toda vez que abrir o Claude Code para
> trabalhar com harness — não é uma instalação permanente do Claude Code em
> si, é um flag de sessão. (Se preferir permanente, ver seção 6.)

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

## 5. Verificar se está tudo consistente

```
/harness-creator:audit
```

Score 0–100. Rode depois de qualquer edição manual em `settings.json`,
`AGENTS.md` ou nos hooks — ele detecta *drift* (alguém editou à mão e
divergiu do que o `harness.yaml` geraria) e sugere recompilar.

## 6. Deixar o plugin sempre disponível (opcional)

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
        └─ quer conferir? ──► /harness-creator:audit
```
