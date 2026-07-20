# harness-creator — Arquitetura

> **Fórmula de 2026:** `Agente = Modelo + Harness`.
> O modelo fornece o raciocínio; o harness garante execução confiável, segurança e governança.

## Pivot (2026-07): modo plugin — compilar governança, não executar

O produto atual é um **plugin do Claude Code** que cria/avalia/compila
estrutura de harness. A execução fica com o próprio Claude Code:

- **`src/harness/compiler.py`** — `.harness/harness.yaml` → `.claude/settings.json`
  (permissions + hooks PreToolUse), `.harness/hooks/*.py` (guards standalone,
  só stdlib, com o regex do test_glob embutido) e bloco gerenciado no
  `AGENTS.md` do projeto-alvo. Fontes de verdade reusadas, não duplicadas:
  `_POLICY_MATRIX`/`_ALWAYS_GATED` (Camada 4) e `_glob_to_regex` (Camada 2).
- **`src/harness/audit.py`** — score 0-100 + findings estruturados;
  dogfooding: recompila em memória e compara com o disco (drift).
- **Skills** — `/harness-creator:init|audit|compile`.
- **Budget de tokens** — o Claude Code não expõe usage a hooks; compila para
  orientação no AGENTS.md, explicitamente advisory.
- **Merge não-destrutivo** — settings.json: entradas gerenciadas registradas
  em `.harness/compiled-state.json`; recompilar troca só o que é do harness,
  preservando regras/hooks manuais do usuário.
