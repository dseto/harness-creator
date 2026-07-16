# Changelog

## 0.11.0 — 2026-07-15

Fase 1 do roadmap (Delegação Baseada em Contratos): move a autoridade humana
de aprovar cada ação para aprovar um único contrato por demanda, antes de
qualquer código.

### Adicionado
- `src/harness/analyzer.py` — análise determinística do repo-alvo (stack,
  comando de teste, lint/build, CI, convenções). Cada achado grava
  `evidence`; o que não foi observado entra em `unknowns[]` — o contrato só
  pode referenciar fatos com evidência.
- `.harness/repo-profile.json` — saída persistida do analyzer, consumida
  pela skill `plan`.
- `src/harness/contract.py` — parseia `spec.md` + `Plans.md` e compila para
  `.harness/feature_list.json` (`{id, desc, files[], verify_cmd, passes}`
  por tarefa). Gate de aprovação: exige `approved_by`/`approved_at`
  preenchidos no frontmatter do `spec.md`; sem isso, `ContractNotApprovedError`.
- `harness analyze --dir` e `harness compile-contract --dir --slug` na CLI.
- Skill `/harness-creator:plan` — entrevista a demanda, apresenta o profile e
  os `unknowns`, escreve o contrato (`spec.md`/`Plans.md`) em
  `.harness/work/<slug>/` e só compila depois da aprovação humana explícita
  (a skill nunca preenche `approved_by`/`approved_at` por conta própria).
- `tests/e2e/test_contract_flow.py` — E2E do fluxo completo
  analyze → spec/Plans → gate de aprovação → compile-contract.
- `tests/e2e/test_contract_dogfood.py` — gate de encerramento da fase: contrato
  aprovado + `claude -p` real implementando uma melhoria genuína na cobaia
  `MinimumAPI` (validação de `Document` só por dígitos), provada por
  `dotnet test` real antes/depois; evidência em
  `tests/e2e/evidence/fase1-dogfood-document-digits.md`.
- `tests/e2e/test_fase1_outcomes.py` — suíte de verificação independente dos
  6 outcomes prometidos pela Fase 1, com evidência acumulada em
  `tests/e2e/evidence/fase1-outcomes-verification.md`.

### Corrigido
- Arnês de verificação independente (`test_fase1_outcomes.py`): o teste do
  fluxo headless da skill `plan` não compilava baseline de permissões
  (`approval_policy: auto`) antes de invocar `claude -p`, então o headless
  negava toda ação `ask` e os outcomes "skill usa o profile"/"skill nunca se
  auto-aprova" ficavam sem veredito; e a fixture de evidência sobrescrevia o
  `.md` inteiro a cada processo pytest separado, apagando vereditos de rodadas
  anteriores. Ambos corrigidos — evidência agora mescla entre execuções e o
  teste headless compila o baseline antes de rodar.

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
