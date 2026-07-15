# Pivot: Plugin "harness-creator" para Claude Code — criar/avaliar/compilar harness, sem executar

> Substitui os planos anteriores (backend B1-B11 ✅ implementado; motor
> OpenRouter/Bedrock ❌ abandonado junto com o cockpit).

## Contexto

Decisão do usuário: **abandonar o cockpit como gerenciador de execução**. O
produto passa a viver **dentro do Claude Code** como **plugin** que ajuda a
**criar, avaliar e compilar** estrutura de harness para projetos — a execução
fica com o próprio Claude Code (que o usuário já usa, autenticado por
assinatura, sem API key).

Decisões travadas com o usuário:
1. **Forma**: plugin (skills + scripts), instalável via `claude --plugin-dir`.
2. **Alvo**: a estrutura gerada **compila para governança nativa do Claude
   Code** — `.claude/settings.json` (permissions + hooks PreToolUse) +
   `AGENTS.md` no projeto-alvo. Governança vale de verdade nas sessões reais.
3. **Backend existente** (`src/harness/`, 53 testes): vira **biblioteca de
   validação** — `HarnessConfig` (pydantic) é a fonte de verdade do
   `harness.yaml`; matriz de aprovação e lógica de test-glob são reusadas
   pelo compilador. Orquestrador/sandbox/TDD-loop ficam **congelados** (não
   deletados; referência para execução futura).

Fatos confirmados (docs oficiais, via agente guide):
- Plugin: `.claude-plugin/plugin.json` (name/description/version) +
  `skills/<nome>/SKILL.md`; skills viram `/harness-creator:<nome>`; teste
  local com `claude --plugin-dir ./`.
- Hook PreToolUse em settings.json do projeto: recebe JSON no stdin
  (`tool_name`, `tool_input.file_path|command`), responde
  `{"hookSpecificOutput": {"hookEventName":"PreToolUse",
  "permissionDecision": "allow|deny|ask", "permissionDecisionReason": ...}}`.
- Permissions: `allow`/`ask`/`deny` com padrões `Bash(cmd *)`,
  `Edit(path/**)`; precedência deny > ask > allow; `ask` prompta o humano.
- Incerteza documentada: hooks DE plugin auto-aplicarem em projeto-alvo não é
  coberto nas docs → **contornado por design**: as skills GERAM permissions e
  hooks dentro do projeto-alvo (visível, versionável), não dependem de hook
  de plugin.

## Abordagem

### Novo layout do repo (vira o plugin + biblioteca)

```
Harness-creator/
├── .claude-plugin/plugin.json        # NOVO
├── skills/
│   ├── harness-init/SKILL.md         # NOVO
│   ├── harness-audit/SKILL.md        # NOVO
│   └── harness-compile/SKILL.md      # NOVO
├── src/harness/
│   ├── compiler.py                   # NOVO — coração do pivot
│   ├── audit.py                      # NOVO
│   ├── config.py                     # reusado (HarnessConfig valida harness.yaml)
│   ├── governance/approval.py        # reusado (_POLICY_MATRIX/_ALWAYS_GATED → permissions)
│   ├── verification/tdd_loop.py      # reusado (_glob_to_regex → hook de testes)
│   └── (orchestrator/sandbox/…)      # congelados, intocados
└── tests/  (53 existentes intactos + test_compiler.py + test_audit.py)
```

### 1. `src/harness/compiler.py` — harness.yaml → artefatos nativos

Entrada: `.harness/harness.yaml` do projeto-alvo (validado por
`HarnessConfig` — reaproveita governance/verification; seções de execução
como sandbox/routing são aceitas mas ignoradas na compilação, com aviso).

Saídas no projeto-alvo:
1. **`.claude/settings.json`** (merge preservando chaves alheias — só
   gerencia `permissions` e `hooks` dentro de um bloco marcado):
   - `approval_policy` → permissions, derivado de
     `_POLICY_MATRIX`/`_ALWAYS_GATED` (fonte única, não duplicar tabela):
     - `paranoid` → `ask`: Bash, Edit, Write, Read(*)
     - `balanced` → `allow`: Read/Grep/Glob; `ask`: Bash(*), Edit(*), Write(*)
     - `auto` → `allow` amplo; permanece `ask`: WebFetch, WebSearch,
       `Bash(curl *)`, `Bash(wget *)` (classe network sempre gateada)
   - hooks PreToolUse:
     - matcher `Write|Edit` → `.harness/hooks/guard_tests.py`
     - matcher `Bash` → `.harness/hooks/guard_test_runner.py`
2. **`.harness/hooks/*.py`** — scripts standalone (SÓ stdlib; o compilador
   EMBUTE no script o regex do `test_glob` — via `_glob_to_regex` — e o
   `test_command`):
   - `guard_tests.py`: `file_path` casa test_glob → `permissionDecision:
     "ask"` com razão ("edição de teste exige aprovação humana — regra
     edit_test do harness"). Não-teste → `allow`.
   - `guard_test_runner.py`: comando colide com test_command (mesma
     tokenização por metacaracteres do TDDGuard) → `ask` com razão TDD
     (`enforce_tdd: false` compila para hook ausente).
3. **`AGENTS.md`** do alvo — seções geradas de template: regras TDD, escopo
   mínimo, budget advisory (Claude Code não expõe tokens a hooks — budget é
   orientação, dito explicitamente), convenções. Marcadores
   `<!-- harness:begin/end -->` para regenerar sem destruir edições manuais.

CLI: subcomandos novos no `cli.py` existente — `harness compile [dir]`,
`harness audit [dir]` (saída JSON + resumo humano).

### 2. `src/harness/audit.py` — avaliar projeto

Checks (score 0–100 + findings estruturados):
- `.harness/harness.yaml` existe e valida contra `HarnessConfig`
- settings.json coerente: recompila em memória e faz diff (drift = finding)
- hooks presentes e executáveis; AGENTS.md com bloco harness
- qualidade da política: budget definido, test_command/glob plausíveis
  (glob casa arquivos reais do projeto), política não-auto em repo com CI
Dogfooding: audit = compile em memória + diff, não segunda implementação.

### 3. Skills (plugin)

- **`/harness-creator:init`** — entrevista curta (política de aprovação,
  test_command, test_glob, budget advisory), escreve
  `.harness/harness.yaml`, roda `harness compile`, mostra o que foi gerado,
  avisa que hooks/permissions valem a partir da próxima sessão.
- **`/harness-creator:audit`** — roda `harness audit`, apresenta score +
  findings, oferece aplicar correções (recompilar / editar yaml).
- **`/harness-creator:compile`** — recompila após edição manual do yaml;
  idempotente; mostra diff do settings.json.

Skills usam `${CLAUDE_PLUGIN_ROOT}`/path do repo para chamar
`python -m harness.cli compile ...` (o plugin documenta o pré-requisito
`pip install -e .` do repo ou embute `PYTHONPATH`).

### 4. Testes

- `tests/test_compiler.py`: mapeamento permissions por política (3 modos);
  merge preserva chaves existentes do settings.json; regeneração idempotente;
  hook gerado é standalone — teste executa `guard_tests.py` via subprocess
  com JSON fake no stdin e valida `permissionDecision` (caso teste e caso
  não-teste; test_glob recursivo `**/test_*.py` não super-bloqueia — regressão
  do bug já corrigido no is_test_path).
- `tests/test_audit.py`: projeto completo → score alto/0 findings; sem hooks
  → finding; drift (settings editado à mão divergindo do yaml) → finding.
- Suíte existente (53) permanece verde — biblioteca intocada exceto adições.

## Ordem de implementação

1. `compiler.py` + templates de hooks + `harness compile` + test_compiler.py
2. `audit.py` + `harness audit` + test_audit.py
3. Plugin packaging: plugin.json + 3 SKILL.md
4. Docs: ARCHITECTURE.md ganha seção "Pivot: modo plugin" (orquestrador
   congelado como referência); README de instalação do plugin
5. E2E manual (verificação abaixo)

## Verificação

1. Suíte: `python -m pytest tests -q` — 53 + ~12 novos verdes.
2. Hook isolado:
   `echo '{"tool_name":"Edit","tool_input":{"file_path":"tests/test_x.py"}}' | python .harness/hooks/guard_tests.py`
   → JSON com `"permissionDecision": "ask"`.
3. E2E real: criar projeto sample, `claude --plugin-dir C:\Projetos\Harness-creator`,
   rodar `/harness-creator:init`, reiniciar sessão no sample, pedir ao Claude
   para editar um arquivo de teste → prompt de aprovação aparece; `curl` via
   Bash → prompt aparece. Rodar `/harness-creator:audit` → score alto.

## Fora de escopo (registrado)

- Execução própria de tarefas (orquestrador/sandbox) — congelado.
- Cockpit web — abandonado.
- Enforcement de budget de tokens (Claude Code não expõe usage a hooks) —
  vira advisory no AGENTS.md.
- Publicação em marketplace de plugins — depois do E2E local.

## Implementado — desvios vs plano original (equalizado em 2026-07-15)

Status: **implementado, 75/75 testes verdes** (53 pré-existentes + 22 novos —
o plano estimava ~12). Desvios deliberados:

1. **Merge do settings.json via estado externo**, não "bloco marcado" dentro
   do próprio settings: as entradas gerenciadas ficam registradas em
   `.harness/compiled-state.json`. Motivo: settings.json permanece 100%
   limpo/válido para o Claude Code, sem chave estranha; recompilar remove só
   o que era gerenciado e preserva regras/hooks manuais.
2. **`routing.tiers` e `routing` viraram opcionais** em `config.py` (defaults
   vazios): harness.yaml de projeto-alvo não define execução. O orquestrador
   congelado segue exigindo tiers preenchidos para rodar.
3. **CLI com flag `--dir`** (`harness compile --dir X`) em vez de argumento
   posicional — mais explícito nas skills.
4. **Skills nomeadas `init`/`audit`/`compile`** (dirs `skills/init` etc.) para
   a invocação ficar `/harness-creator:init` como planejado — a primeira
   implementação usava `harness-init` e gerava `/harness-creator:harness-init`
   (redundante); corrigido.
5. **Hooks com path absoluto embutido** no settings.json (decisão explícita:
   cmd.exe não expande `$VAR`; repo movido = drift que o `harness audit`
   acusa).
6. Incidente não relacionado ao plano: `src/harness/context/` tinha sido
   movido acidentalmente (fora da sessão) para `governance/context/`;
   restaurado.

## Fechamento (2026-07-15)

Aceitação rodada contra os 3 critérios da seção "Verificação" acima — todos
atingidos e superados:

1. **Suíte**: 87 testes (77 unit + 8 E2E com cópia real da MinimumAPI .NET +
   2 headless reais opt-in), 85 passam sempre + 2 skipped por padrão
   (`HARNESS_E2E_HEADLESS=1` pra rodar, custam tokens reais). Zero falhas.
2. **Hook isolado**: validado por unit tests e, ao vivo, com payloads .NET
   reais (`Edit`/`Bash` via stdin) contra `MinimumAPI-harness`.
3. **E2E real**: roteiro manual de 7 casos rodado numa sessão real do Claude
   Code contra `MinimumAPI-harness` — todos ✅ (leitura livre, edição/
   execução/rede gateadas, TDD bloqueando teste e runner, audit score 100).

Além do escopo original: descoberta e correção de 2 bugs que só apareceram
testando contra código real (test runner multi-palavra sobre-bloqueando;
audit hardcoded pra `.py`); achado de UX (razão do hook TDD não aparece na
UI de aprovação); confirmação empírica de que `claude -p` headless nunca
trava em ação `ask` (nega e segue, exit 0) e que o sinal de bloqueio pra
scripts é o campo `permission_denials` do `--output-format json`, não o
exit code — documentado e coberto por teste.

Sem git neste diretório — nada para commitar/PR. Documentação (README,
GUIDE, ARCHITECTURE) atualizada ao longo da execução, não ao final.

**Veredito: DEMANDA FECHADA.**
