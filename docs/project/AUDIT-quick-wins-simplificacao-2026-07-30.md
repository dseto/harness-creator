# Auditoria — Quick Wins de Simplificação e Eficiência de Tokens — 2026-07-30

Demanda: auditoria de "quick wins" e simplificação extrema do `harness-creator`
sob os cinco eixos de Engenharia de Harness (SSOT/eliminação de duplicação,
corte de overengineering, eficiência de tokens/roteamento de modelo, corte de
validação indiscriminada, governança spec-driven).

Irmã do [AUDIT-harness-engineering-2026-07-30.md](AUDIT-harness-engineering-2026-07-30.md)
(fricção humana, matriz HITL, FinOps) — **sem sobreposição deliberada**: aquele
laudo cobre *quem decide o quê*; este cobre *quanto custa em tokens/latência/
linhas o que já foi decidido*. As três user stories do
[USER-STORY-p0-friccao-ciclo-2026-07-30.md](USER-STORY-p0-friccao-ciclo-2026-07-30.md)
(kill-switch visível, rastro de `verify` falho, SHAs da era congelada) não são
repetidas aqui.

Escopo desta rodada: **somente o laudo**. Nenhuma mudança de código, config ou
documentação existente. A Onda 1 do plano de execução (seção 4) foi
formalizada como contrato próprio em
[.harness/work/onda-1-flags-e-facas/](../../.harness/work/onda-1-flags-e-facas/spec.md).

Método: três subagentes de exploração dedicados rodando em paralelo —
`skills/` (duplicação/verbosidade de prompt), `src/harness/` (overengineering/
código morto), runtime `.harness/`+testes+docs (custo recorrente por
sessão/tool-call) — mais verificação direta de cada citação usada nos diffs
da seção 3 e nas tarefas do contrato de Onda 1. Todo achado cita `file:line`;
números de latência/tokens/linhas foram **medidos no repositório**, não
estimados.

---

## 0. Números-base medidos

| Métrica | Valor |
|---|---|
| `src/harness/` | 12.813 linhas, 31% prosa (docstring+comentário) |
| Prompt de `skills/*` (7 SKILL.md + 3 refs) | 1.172 linhas |
| `AGENTS.md` injetado por sessão | ≈2.450 tokens |
| Injeção do hook `SessionStart` | ≈600 tokens (2.162 chars) |
| **Piso fixo de contexto por sessão** | **≈3.050 tokens antes da 1ª mensagem** |
| Latência de hook por `Bash` call | **218 ms** (2 processos Python) |
| `docs/plugin/*` (GUIDE+TUTORIAL+ARCHITECTURE) | 2.316 linhas ≈ 33.500 tokens |
| `python -c pass` (baseline da máquina) | 66,9 ms mediana |

Correção a duas premissas do briefing original: (a) não existe "prosa em 9
locales" em `boundary_guard.py` — a menção histórica em
[AUDIT-harness-engineering-2026-07-30.md:184](AUDIT-harness-engineering-2026-07-30.md)
refere-se ao parser de saída de test-runner **descartado** (CHANGELOG v0.28),
assunto diferente; (b) o bloco `harness:auto` do `progress.md` **já tem cap**
(10 entradas, [templates.py:91](../../src/harness/templates.py#L91)) — o
problema é densidade sem dedupe, não crescimento ilimitado.

---

## 1. 🚀 Matriz de Quick Wins

| # | Componente/Arquivo | Problema | Técnica / Ação | Impacto medido | Esforço |
|---|---|---|---|---|---|
| 1 | [hook_launcher.py:109](../../src/harness/hook_launcher.py#L109) | Hook lançado sem `-S`: Python varre site-packages a cada tool call — 24 ms disso é um `.pth` editable de **outro projeto** | Emitir `-S -E` no `hook_command` (hooks são stdlib-only por design) | **−25 ms × toda tool call** (90→68 ms) | Baixo |
| 2 | [settings.local.json:110-128](../../.claude/settings.local.json#L110) + `guard_test_runner.py` | 2 processos Python por Bash call (matchers `Bash` e `*` separados); `guard_test_runner` nem lê o payload — imprime `allow` constante em 100% dos casos | Fundir o roteamento de test-runner dentro do `boundary_guard.main()`; remover o hook | **−99 ms/Bash call (−45%)**; até −12 s por tarefa no teto de 120 calls | Baixo |
| 3 | [AGENTS.md:1-59](../../AGENTS.md) | Metade manual **stale da era congelada**: promete sandbox/container que não existe no host Windows, tools `read_file`/`write_file`/`run_terminal` que não são do Claude Code, `ContextManager` e pacotes `tools/ verification/ context/ telemetry/ routing/` fora da árvore atual — injetado toda sessão | Reescrever para a realidade atual; 160→~90 linhas | **−~1.000 tokens/sessão** + elimina instrução falsa (anti prompt-drift) | Baixo |
| 4 | [compiler.py:362-364](../../src/harness/compiler.py#L362) | Bloco gerado do AGENTS.md repete escopo/segredos (strings constantes, sem interpolação do YAML) que já estão na parte manual — SSOT quebrada dentro do próprio arquivo injetado | Bloco gerado só carrega o que deriva do `harness.yaml` (política, `test_command`, orçamento) | Fim da regra declarada 2× por sessão | Baixo |
| 5 | [session_start.py:234](../../src/harness/session_start.py#L234) | Matcher `"*"`: os ~600 tokens re-injetam também em **cada compact** (3 compacts = 2.400 tokens de duplicata) | Restringir a `startup\|resume\|clear` | **−600 tokens por compact** (anti token-snowball) | Baixo |
| 6 | [templates.py:375](../../src/harness/templates.py#L375) + [verify.py:492](../../src/harness/verify.py#L492) + [finish.py:206](../../src/harness/finish.py#L206) | Bloco `harness:auto` sem dedupe (T-05 3×, T-01/T-03 2× = 44% do cap desperdiçado); **3 paths de evidência inexistentes e 2 features fantasma** injetados; `finish` encerra a demanda sem zerar o bloco | Dedupe por `T-XX`, validar path antes de anexar, `render_closed_progress` purga o bloco | Injeção 100% verídica; −~250 tokens/sessão | Baixo |
| 7 | `skills/*` (7 SKILL.md + 3 refs) | Duplicação sistêmica: bloco PYTHONPATH **5×**, gate "REGRA DURA" 2×, seções `## Regras` que só reafirmam os passos (~60 linhas), `assess` declara read-only **4× no mesmo arquivo**, anedotas de medição como prosa de skill | Dedup + mover justificativas históricas para `docs/`; SSOT em referência compartilhada | **1.172→~700 linhas (−40%)** por invocação de skill | Médio |
| 8 | [skills/assess/SKILL.md:33-107](../../skills/assess/SKILL.md#L33) | Único spawn point do plugin e **zero roteamento de modelo**; Passo 2 é inventário mecânico (grep/glob/git log — ~64k tokens medidos por avaliação) rodando no modelo forte | Split: coleta em subagente **Haiku** → veredito D2/D4 no modelo forte; 29 linhas de justificativa do spawn viram 4 | Maior corte de custo $ do plugin | Médio |
| 9 | [boundary_guard.py:1-284](../../src/harness/boundary_guard.py#L1) | Docstring de módulo de 284 linhas (19k chars) que o hook compilado **nem contém**; prosa total do arquivo = 36% | Mover histórico de decisões para `docs/project/`; docstring vira contrato de ~30 linhas | −250 linhas no maior arquivo do produto | Baixo |
| 10 | [boundary_guard.py:2183-2240](../../src/harness/boundary_guard.py#L2183) + [audit.py:88](../../src/harness/audit.py#L88) | Render **não-determinístico** (6× `set()!r` — 3 execuções = 3 hashes diferentes) + nenhum check de drift do hook + `.harness/hooks/` é gitignored. Drift real hoje: state compilado v0.28 vs pacote v0.29 | `sorted()` nos 6 pontos; `audit` passa a comparar `render_boundary_guard()` vs disco; aviso de skew no `session_start` | Drift do maior hook detectável pela 1ª vez | Baixo |
| 11 | [boundary_guard.py:2948/3130](../../src/harness/boundary_guard.py#L2948) e [:1679/:2697](../../src/harness/boundary_guard.py#L1679) | `_evaluate_bash` vs `_evaluate_powershell`: 252 linhas com a MESMA sequência de 6 passos (fix de floor pode entrar só num); review-gate com 2 cópias manuais **já divergentes** (similaridade 0,41–0,56) | Extrair `_evaluate_command(flavor)`; embutir `review.py` via `getsource` (padrão já usado no arquivo) | −330 linhas; **1 floor, não 2** | Médio |
| 12 | [compiler.py:166-186](../../src/harness/compiler.py#L166) | `guard_tests.py`: compiler **gera** o script mas o próprio produto **remove seu registro** por decisão do issue #61 — e blindou essa decisão com 6 testes unitários + 2 e2e ("Outcome 5") que hoje afirmam "gerado E não registrado". Escopo real maior que uma poda simples: ver correção na seção 4 | Deletar `_render_guard_tests` + os 6 testes que validam um script sem consumidor + atualizar os 2 e2e para "não gerado" + 3 menções em docs | −~200 linhas mantidas sobre um arquivo morto | **Médio** (revisado — ver nota) |
| 13 | [audit.py:31](../../src/harness/audit.py#L31) / `runtime_audit.py` / `team_audit.py` | `Finding`/`Report`/`_PENALTY`/`_finish` **triplicados** byte a byte (~105 linhas) | `harness/findings.py` compartilhado, re-exportado pelos 3 módulos (zero disrupção nos testes existentes); expor `harness audit --all` depois | −105 linhas; 1 formato de laudo | Baixo |
| 14 | `docs/plugin/` (GUIDE/TUTORIAL/ARCHITECTURE) | Kill-switch em **3 cópias** com a mesma anedota (94 linhas); diagrama do ciclo em 2 versões **já divergentes** (um tem `finish`, outro não); tabela do preflight reescrita em 4 lugares | Padrão de delegação que o próprio repo já usa ("três escapes" do GUIDE): 1 fonte + links | −130 linhas; 2 drifts materializados eliminados | Médio |
| 15 | [cli.py:542](../../src/harness/cli.py#L542) | `verify` que falha despeja stdout **e** stderr completos do runner no contexto do agente — suíte verbosa entra inteira | Truncar às últimas ~40 linhas (o `file_lock_hint` prova que a saída já é analisada, não só ecoada) | Anti-snowball no caminho vermelho (o mais frequente em TDD) | Baixo |
| 16 | [session_permissions.py:302-307](../../src/harness/session_permissions.py#L302) + [compiler.py:477-506](../../src/harness/compiler.py#L477) | Duas rotinas de merge **independentes** (`compile_project` rastreia `managed_permissions` no `compiled-state.json`; `compile_session_permissions` rastreia `managed_session_permissions` no `compiled-state-session.json`) escrevem no MESMO `settings.local.json` sem se enxergar — nenhuma reconhece uma entrada da outra como "gerenciada", então nada sombreado por uma regra nua (`Bash`/`Edit`/`Write`) é podado | Prune de entradas estritamente sombreadas dentro de [`write_managed_settings`](../../src/harness/settings_paths.py#L182) — sink único que os dois caminhos já compartilham | Arquivo gerenciado do tamanho do que está de fato em vigor | Baixo |
| 17 | boundary_guard, roteador de tool desconhecida | Negou `TaskCreate` **nesta própria sessão de auditoria** por heurística de nome ("contém create → deny") — tool interna read-only-adjacente do Claude Code | Allowlist das tools nativas de task-tracking no roteador de tool desconhecida | Fricção falso-positivo a menos ("barrar o mínimo") | Baixo |

---

## 2. 🏗️ Arquitetura Antes vs. Depois

**Por tool call (camada Guardrails):**
```
ANTES  Bash call ─→ python #1 guard_test_runner (125 ms, allow constante, não lê payload)
                 └→ python #2 boundary_guard   (120 ms, 3 reads de disco, git log timeout 10s)
                    = 218 ms/Bash · 90 ms demais tools · site-packages varrido 2×

DEPOIS Bash call ─→ python único -S -E boundary_guard (~70 ms)
                    roteia test-runner inline · _load_json memoizado · git timeout 2 s
                    = −68% por Bash call · −14 s/tarefa no teto de 120 calls
```

**Por sessão (camada Contexto/Memória):**
```
ANTES  AGENTS.md ~2.450 tk (½ stale da era congelada + TDD/escopo/segredos declarados 2×)
     + injeção ~600 tk (2 features fantasma, 3 paths falsos, T-05 3×)
     × re-injetada a cada compact
     ≈ 3.050 tk fixos + 600/compact

DEPOIS AGENTS.md ~1.400 tk (só o que é verdade; gerado = só o derivado do YAML)
     + injeção ~350 tk (deduplicada, verídica, só startup|resume|clear)
     ≈ 1.750 tk fixos (−43%) + 0/compact
```

**Por invocação de skill (camada Orquestração):**
```
ANTES  plan 217 linhas (restatement + prosa de Fase-6 futura) · assess 198 linhas,
       inventário mecânico no modelo forte (~64k tk/avaliação)

DEPOIS plan ~110 · assess ~85 + split Haiku(coleta: grep/git log) → forte(veredito D2/D4)
       preflight/audit/compile marcadas "roda bem em modelo leve"
```

O que **não muda**: floor de segurança (rede, segredos, branch protegida, push
fora do contrato), gate humano do contrato, par red→green, evidência
executável (já enxuta: 8 campos, ~520 B — medido e aprovado).

---

## 3. 🛠️ Refatoração Prática

**(a) Latência — 1 linha, toda tool call** ([hook_launcher.py:109](../../src/harness/hook_launcher.py#L109)):
```diff
 def hook_command(script_path: Path | str) -> str:
-    return f'"{resolve_interpreter()}" "{script_path}" {FAIL_CLOSED_SUFFIX}'
+    # -S: pula site-packages (hooks são stdlib-only por design; medido 90→68 ms)
+    # -E: ignora PYTHONPATH herdado — o hook nunca deve importar do repo-alvo
+    return f'"{resolve_interpreter()}" -S -E "{script_path}" {FAIL_CLOSED_SUFFIX}'
```

**(b) SSOT no AGENTS.md — bloco gerado só carrega o que deriva do YAML** ([compiler.py:362-364](../../src/harness/compiler.py#L362)):
```diff
 {tdd}2. **Escopo mínimo**: modifique apenas arquivos diretamente ligados à
-   tarefa; refactors oportunistas exigem tarefa própria.
-3. **Sem segredos** em código, logs ou commits.
-4. **Orçamento (orientação)**: alvo de ~{g.budget.max_tokens_per_task:,} tokens
+{tdd}2. **Orçamento (orientação)**: alvo de ~{g.budget.max_tokens_per_task:,} tokens
```
(Escopo mínimo e segredos ficam onde já vivem: [AGENTS.md:23-27](../../AGENTS.md#L23),
parte manual. Itens 2-3 do template não interpolam nenhum campo da config —
texto fixo não pertence a bloco "gerado".)

**(c) Injeção verídica — dedupe por tarefa** ([templates.py:375](../../src/harness/templates.py#L375),
com `feature_id` novo vindo de [verify.py:492](../../src/harness/verify.py#L492)):
```diff
-    if begin != -1 and end > begin:
-        previous = [
-            line for line in text[begin + len(_AUTO_NOTE_BEGIN):end].splitlines()
-            if line.strip().startswith("- ")
-        ]
-        entries = (previous + [entry])[-_AUTO_NOTE_MAX_ENTRIES:]
+    if begin != -1 and end > begin:
+        previous = [
+            line for line in text[begin + len(_AUTO_NOTE_BEGIN):end].splitlines()
+            if line.strip().startswith("- ")
+            and not (feature_id and f" {feature_id} " in line)
+        ]
+        entries = (previous + [entry])[-_AUTO_NOTE_MAX_ENTRIES:]
```
Cap de 10 passa a valer 10 **tarefas**, não 10 execuções da mesma.

**(d) Prompt de skill — dedup do bloco repetido 5×** (ex. [skills/plan/SKILL.md:16-21](../../skills/plan/SKILL.md#L16)):
```diff
-Não rode uma checagem de import à parte. Se `harness.cli` der
-ModuleNotFoundError, ISSO que indica falta de PYTHONPATH — configure
-$env:PYTHONPATH="${CLAUDE_PLUGIN_ROOT}\src" e repita o mesmo comando.
-A checagem separada custaria um Bash a mais pedindo aprovação sem
-necessidade, porque o comando real já falha com o mesmo sinal.
-(… 6 linhas equivalentes em init, team, preflight, audit …)
+Se der ModuleNotFoundError: $env:PYTHONPATH="${CLAUDE_PLUGIN_ROOT}\src" e repita.
```
Justificativa vai 1× para `docs/plugin/GUIDE.md`. Mesmo padrão para o gate
"REGRA DURA" (2×) e as seções `## Regras` (4 skills de restatement puro).

**(e) Prune de allowlist no sink único** ([settings_paths.py:182](../../src/harness/settings_paths.py#L182)):
```diff
 def write_managed_settings(path: Path, settings: dict[str, Any]) -> None:
     """Grava o settings gerenciado no formato único (indent 2, UTF-8, `\\n`
     final) que os cinco escritores usavam duplicado."""
+    allow = settings.get("permissions", {}).get("allow")
+    if allow:
+        settings["permissions"]["allow"] = _prune_shadowed(allow)
     path.parent.mkdir(parents=True, exist_ok=True)
     path.write_text(
         json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
     )
```
Um só ponto: os dois merges independentes (`compile_project` via
`compiled-state.json`, `compile_session_permissions` via
`compiled-state-session.json`) passam pela poda sem precisar se conhecer.

---

## 4. 📋 Plano de Execução (80% do ganho, 20% do esforço)

Cada onda = 1 contrato via `/harness-creator:plan` (dogfood do ciclo). Prova
por onda = `pytest -k`/arquivos do escopo tocado, nunca suíte completa por
iniciativa própria.

**Onda 1 — "flags e facas"** (itens **1, 9, 10 parcial, 12, 13, 15, 16** —
formalizada em [.harness/work/onda-1-flags-e-facas/spec.md](../../.harness/work/onda-1-flags-e-facas/spec.md)):
flag `-S -E`, mover docstring de 284 linhas, determinizar render (`sorted()`),
remover geração de `guard_tests.py`, `findings.py` compartilhado, truncar
dump do `verify`, prune de allowlist sombreada. Zero mudança de comportamento
observável fora do declarado em cada critério de aceitação.

> **Nota de revisão**: o item 12 (`guard_tests.py`) tem escopo maior do que a
> estimativa original de "baixo esforço" — ao verificar antes de escrever o
> contrato, descobri que a geração-sem-registro é um **outcome deliberado e
> testado** (issue #61, "Outcome 5" da Fase 2, com 6 testes unitários +
> 2 e2e + 1 doc de evidência afirmando explicitamente "gerado, mas não
> registrado"). Remover a geração exige atualizar essas 8 provas, não só
> apagar `_render_guard_tests`. A ação continua correta (o registro nunca
> acontece; gerar o arquivo não tem consumidor) e o risco continua zero
> (mudança puramente subtrativa, sem decisão de segurança nova) — só o
> esforço sobe de Baixo para Médio. Mantido em Onda 1 porque é mecânico do
> início ao fim, não por ser pequeno.

**Onda 2 — "contexto verídico"**: itens **3, 4, 5, 6** — reescrever AGENTS.md
manual, enxugar bloco gerado, matcher do SessionStart, dedupe/purge do
progress. ⚠️ Mesmos arquivos da **US-1 do P0** (`session_start.py`) —
empacotar no mesmo contrato daquela user story para não abrir duas frentes
no mesmo hook.

**Onda 3 — "um processo, um floor"**: itens **2, 11**, resto do 10
(drift-check no `audit`), item **17** — fusão dos hooks, `_evaluate_command`
unificado, review via `getsource`, allowlist de tools internas. Os 95 testes
de `test_boundary_guard.py` são a rede; razão teste:código 0,83:1 já cobre.

**Onda 4 — "prompts e docs"**: itens **7, 8, 14** — dedup das skills (−40%),
split Haiku/forte no `assess` (primeiro roteamento de modelo real do
produto), delegação nos docs. Restrição dura:
[test_docs_enforcement_claims.py](../../tests/test_docs_enforcement_claims.py)
proíbe reintroduzir afirmações sobre guards — cortes são seguros, reescritas
não.

**Não fazer** (alinhado às leis do projeto): afrouxar o floor; tocar na
semântica de deny do guard além do item 17; consolidar os 4 auditores num só
(mecanismos genuinamente distintos — só a saída unifica, ver item 13); mexer
no formato da evidência (já mínima); mudar o algoritmo de merge
"não-destrutivo" do `session_permissions.py` além da poda estritamente
definida do item 16 — regras manuais genuínas continuam preservadas.

**Saldo total projetado**: piso de sessão −43% · Bash call −68% de hook ·
até −14 s/tarefa · skills −40% por invocação · ~−1.800 linhas mantidas ·
3 drifts reais (hook v0.28/v0.29, diagrama do ciclo, tabela preflight) passam
a ser detectáveis ou deixam de existir.

---

## Referências

- [docs/project/AUDIT-harness-engineering-2026-07-30.md](AUDIT-harness-engineering-2026-07-30.md) —
  laudo irmão (fricção humana, matriz HITL, FinOps/roteamento de modelo);
  este documento não repete nenhum achado de lá.
- [docs/project/USER-STORY-p0-friccao-ciclo-2026-07-30.md](USER-STORY-p0-friccao-ciclo-2026-07-30.md) —
  as 3 user stories P0 (kill-switch visível, rastro de `verify`, SHAs da era
  congelada); Onda 2 deste laudo empacota junto com a US-1 por tocarem o
  mesmo hook.
- [docs/roadmap-autonomous.md](../roadmap-autonomous.md) — Fases 5–7; nenhum
  item deste laudo depende delas nem as antecipa além do já registrado no
  laudo irmão.
- [.harness/work/onda-1-flags-e-facas/](../../.harness/work/onda-1-flags-e-facas/spec.md) —
  contrato formal da Onda 1, aguardando aprovação humana.
