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

Se der `ModuleNotFoundError`: `$env:PYTHONPATH = "${CLAUDE_PLUGIN_ROOT}\src"` e
repita o comando (motivo em [GUIDE.md](../../docs/plugin/GUIDE.md), seção 1).

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

## Passo 2 — Gerar `.harness/harness.yaml` no alvo

**Não escreva o YAML à mão.** Até a v0.33.0 este passo mandava copiar um
template em prosa que cobria 6 das 11 chaves do schema real
(`harness.config.HarnessConfig`) — as 5 ausentes só eram descobertas lendo
Python. Agora o arquivo nasce de `harness.templates.render_harness_yaml`, que
introspecciona o schema: toda chave sai no arquivo, com o valor e um
comentário de uma linha, e uma chave nova em `config.py` aparece sozinha na
próxima geração.

Rode, substituindo `<alvo>` pelo diretório-alvo e as 4 respostas da
entrevista (aspas simples nos textos, `True`/`False` nos booleanos Python):

```
python -c "from pathlib import Path; from harness.config import GovernanceConfig, HarnessConfig, VerificationConfig; from harness.templates import render_harness_yaml; cfg = HarnessConfig(governance=GovernanceConfig(approval_policy='<resposta>'), verification=VerificationConfig(enforce_tdd=<resposta>, test_command='<resposta>', test_glob='<resposta>')); path = Path('<alvo>') / '.harness' / 'harness.yaml'; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(render_harness_yaml(cfg), encoding='utf-8')"
```

Todo campo que a entrevista não perguntou (orçamento, `extra_allowed_commands`,
`branch_per_contract`, `protected_branches`, `allowed_skips`) sai com o
default do schema — visível e comentado no arquivo gerado, não escondido.
Se der `ModuleNotFoundError`, aplique o pré-requisito no topo desta skill.

## Passo 3 — Compilar

```
python -m harness.cli compile --dir <alvo>
```

Saída JSON lista settings.local.json, hooks e AGENTS.md gerados. Se der
`ModuleNotFoundError`, aplique o pré-requisito acima e repita.

## Passo 4 — Apresentar e avisar

1. Mostre ao usuário O QUE foi gerado (permissions ask/allow, hooks, bloco do
   AGENTS.md) e o porquê em 1 frase cada.
2. **Avise**: os hooks `PreToolUse` (entre eles o `boundary_guard.py`) podem
   passar a valer IMEDIATAMENTE, ainda nesta sessão — não conte com uma
   janela livre até reiniciar. As regras de `permissions` enumeradas em
   `.claude/settings.local.json` é que podem só ser lidas na próxima sessão.
   Diga também que, enquanto não houver contrato compilado, a superfície de
   ESCRITA fica fechada (default-deny) e a de COMANDO fica no mínimo de
   bootstrap: git local, subcomandos do próprio `harness` e utilitários
   read-only — o suficiente para rodar `/harness-creator:plan` em seguida.
3. Sugira rodar `/harness-creator:audit` depois para validar.

## Regras

- NUNCA sobrescreva um `.harness/harness.yaml` existente sem confirmar — se já
  existir, mostre o atual e pergunte se quer reconfigurar.
- Não edite `.claude/settings.local.json` à mão — o compilador faz merge preservando
  o que o usuário já tem lá.
