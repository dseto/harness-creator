---
name: compile
description: Recompila .harness/harness.yaml para a governança nativa do Claude Code (permissions + hooks + AGENTS.md) após edição manual do yaml. Idempotente; preserva configurações manuais do settings.json.
when_to_use: Depois que o usuário editou .harness/harness.yaml à mão (mudou política, test_command, test_glob, enforce_tdd) e precisa que a mudança valha nas sessões do Claude Code; ou quando o audit apontou drift.
argument-hint: "[diretório-alvo, default: raiz do projeto atual]"
disable-model-invocation: false
---

# Recompilar harness

## Passos

1. Se `.claude/settings.json` existir no alvo, leia ANTES de compilar (para o
   diff do passo 3).
2. Rode:
   ```
   python -m harness.cli compile --dir <alvo>
   ```
   Erro "não existe" → o projeto não tem harness; redirecione para
   `/harness-creator:init`.
3. Mostre o diff do `settings.json` (antes → depois) em termos humanos: quais
   regras de permissão entraram/saíram, quais hooks mudaram. Repasse também os
   `warnings` do JSON de saída (ex.: seções de execução ignoradas).
4. Avise: mudanças valem na PRÓXIMA sessão do Claude Code nesse projeto.

## Regras

- Hooks em `.harness/hooks/` são gerados — se o usuário os editou à mão, avise
  que a recompilação sobrescreve e confirme antes.
- Nunca edite settings.json manualmente para "completar" a compilação; se algo
  parece faltar, rode `/harness-creator:audit` para diagnóstico.
