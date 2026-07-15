# Changelog

## 0.10.0 — 2026-07-15

Pivot: de executor agêntico próprio para **plugin do Claude Code** que cria,
avalia e compila governança de harness — sem executar tarefas, sem
`ANTHROPIC_API_KEY`.

### Adicionado
- `src/harness/compiler.py` — `.harness/harness.yaml` → `.claude/settings.json`
  (permissions + hooks PreToolUse) + `AGENTS.md` (bloco gerenciado). Reusa
  `_POLICY_MATRIX`/`_ALWAYS_GATED` e `_glob_to_regex` da biblioteca existente.
- `src/harness/audit.py` — score 0-100 + findings via dogfooding (recompila
  em memória e compara com o disco).
- `harness compile --dir` / `harness audit --dir` na CLI.
- Plugin (`.claude-plugin/plugin.json`) com 3 skills:
  `/harness-creator:init|audit|compile`.
- Merge não-destrutivo do `settings.json` (preserva regras/hooks manuais do
  usuário; estado gerenciado em `.harness/compiled-state.json`).
- Suíte de testes em 3 camadas: 77 unit + 8 E2E (cópia real de API .NET via
  subprocess) + 2 headless reais (`claude -p`, opt-in).
- `scripts/make_playground.py` — gera playground reprodutível pra teste
  manual contra API real.

### Corrigido
- `guard_test_runner.py` sobre-bloqueava `test_command` de 2+ palavras (ex.:
  `dotnet test` marcava `dotnet build` também) — trocado por matching de
  sequência consecutiva de tokens.
- `audit.py` só procurava arquivo de teste `.py` (hardcoded) — agora varre
  qualquer extensão respeitando `test_glob`.

### Descoberto e documentado
- `claude -p` (headless) nunca trava numa ação `ask` — nega automaticamente
  e a sessão termina normal (exit 0). O sinal de bloqueio pra scripts é o
  campo `permission_denials` do `--output-format json`, não o exit code.
- Razão específica do hook de TDD não aparece na UI de aprovação do Claude
  Code — visualmente idêntica a um `ask` genérico (achado de UX, não bug).
- Regra `ask` sempre vence `allow` por precedência de bucket, independente
  de especificidade — não dá pra abrir exceção pontual pras próprias skills
  sem afrouxar o gate geral de `Bash`.

### Congelado (referência, fora do produto atual)
- Orquestrador próprio (`orchestrator.py`) + sandbox Docker + TDD loop — a
  versão anterior deste projeto, um executor agêntico completo de 6 camadas.
  Segue no repo, testado, mas fora do caminho principal.

## 0.1.0

Versão inicial: arcabouço de execução agêntica com orquestrador próprio,
sandbox Docker, aprovação HITL, roteamento de modelo e telemetria.
