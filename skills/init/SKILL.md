---
name: init
description: Cria a estrutura de harness (governança de agentes) num projeto — entrevista curta, gera .harness/harness.yaml e compila para permissions, hooks PreToolUse e AGENTS.md nativos do Claude Code.
when_to_use: Quando o usuário quer adicionar governança de harness a um projeto (aprovações HITL, proteção de testes/TDD, política de rede) ou pede "criar harness", "iniciar harness", "governança de agente" no projeto atual.
argument-hint: "[diretório-alvo, default: raiz do projeto atual]"
disable-model-invocation: false
---

# Criar estrutura de harness no projeto

Você vai criar a governança de harness no projeto-alvo (argumento `$0` ou a
raiz do projeto atual) e compilá-la para os mecanismos nativos do Claude Code.

## Pré-requisito (só se o Passo 3 falhar)

Não rode uma checagem de import à parte — é um `Bash` a mais pedindo
aprovação sem necessidade. Se `harness.cli` der `ModuleNotFoundError`, ISSO
que indica falta de `PYTHONPATH`; só então rode com
`$env:PYTHONPATH = "${CLAUDE_PLUGIN_ROOT}\src"` (PowerShell) e repita o
comando.

## Passo 1 — Entrevista curta (use AskUserQuestion)

Pergunte, com defaults sensatos:

1. **Política de aprovação** (`approval_policy`):
   - `balanced` (recomendado) — aprova tudo que muda estado (edit/execute/rede)
   - `paranoid` — aprova literalmente tudo, inclusive leituras
   - `auto` — auto-aprova edit/execute; NÃO é read-only (avise isso); só rede e
     edição de teste seguem gateados
2. **Comando de teste** (`test_command`) — detecte do projeto (pytest, npm test,
   go test...) e proponha; confirme com o usuário.
3. **Glob dos arquivos de teste** (`test_glob`) — detecte a convenção
   (ex.: `tests/**/*.py`, `**/*.test.ts`) e proponha.
4. **TDD enforcement** (`enforce_tdd`) — default true (hook pede confirmação
   humana ao rodar a suíte direto e ao editar arquivos de teste).

## Passo 2 — Escrever `.harness/harness.yaml` no alvo

Apenas as seções compiláveis (NÃO inclua sandbox/routing/eet — são do modo de
execução congelado e só gerariam warning):

```yaml
governance:
  approval_policy: <resposta>
  budget:
    max_tokens_per_task: 500000      # orientação (advisory), não enforcement
    max_tool_calls_per_task: 120
verification:
  enforce_tdd: <resposta>
  test_command: "<resposta>"
  test_glob: "<resposta>"
```

## Passo 3 — Compilar

```
python -m harness.cli compile --dir <alvo>
```

Saída JSON lista settings.json, hooks e AGENTS.md gerados. Se der
`ModuleNotFoundError`, aplique o pré-requisito acima e repita.

## Passo 4 — Apresentar e avisar

1. Mostre ao usuário O QUE foi gerado (permissions ask/allow, hooks, bloco do
   AGENTS.md) e o porquê em 1 frase cada.
2. **Avise**: permissions e hooks passam a valer na PRÓXIMA sessão do Claude
   Code aberta nesse projeto (a sessão atual não recarrega settings).
3. Sugira rodar `/harness-creator:audit` depois para validar.

## Regras

- NUNCA sobrescreva um `.harness/harness.yaml` existente sem confirmar — se já
  existir, mostre o atual e pergunte se quer reconfigurar.
- Não edite `.claude/settings.json` à mão — o compilador faz merge preservando
  o que o usuário já tem lá.
