# Evidência — Fase 4: verificação dos 8 outcomes

Gerado em 2026-07-16T16:30:00+00:00 a partir da execução real de
`tests/e2e/test_fase4_outcomes.py` (21 testes, ângulo independente/adversarial —
estado forjado à mão, sabotagem manual de artefatos gerados, subprocess real da
CLI e do hook standalone; nenhum teste reaproveitado dos subagentes de
execução). Todos os 21 testes deste arquivo passaram na primeira rodada — nenhum
ajuste de código de produção foi necessário para fechar a Fase 4.

## Outcome 1 — Catálogo de 6 padrões, invariante de tools do reviewer/supervisor

Veredito: **ATINGIDO**

`list_patterns()` expõe exatamente os 6 padrões do ROADMAP
(`producer-reviewer`, `supervisor`, `pipeline`, `expert-pool`,
`fan-out-fan-in`, `hierarchical-delegation`). Os dois priorizados carregam com
papéis completos (`tools` por papel); `reviewer`/`supervisor` nunca têm
`Edit`/`Write`; os 4 declarativos carregam sem `tools` fixado.
Testes: `test_catalog_exposes_six_patterns_with_tool_invariant`,
`test_load_pattern_unknown_raises_team_error`.

## Outcome 2 — `generate_team` de ponta a ponta

Veredito: **ATINGIDO**

Num projeto sintético (`tmp_path`), `generate_team` grava
`.claude/agents/producer.md`/`reviewer.md`, `.claude/skills/*/SKILL.md`,
bloco de time em `AGENTS.md`, `.harness/TEAM.md` e
`.harness/team/manifest.json` com o schema fixado. Invariante de tools
verificado no ARQUIVO gerado (não só no dataclass); idempotente (2ª geração
não duplica blocos); padrão `supervisor` mantém `supervisor`/`reviewer`
read-only.
Testes: `test_generate_team_end_to_end_writes_all_artifacts`,
`test_generate_team_supervisor_pattern_keeps_supervisor_readonly`.

## Outcome 3 — State machine escala, nunca força; teto duro

Veredito: **ATINGIDO**

3 ciclos submit→reject com `max_iterations=3`: `escalate=True` só na 3ª
iteração, `status` permanece `'rejected'` em disco (nunca `'approved'` por
esgotamento — divergência deliberada da fonte exigida pelo ROADMAP); 4ª
resubmissão levanta `ReviewError` (teto duro real, não só aviso); aprovar
diff de teste sem `justification` falha sem corromper o estado.
Testes: `test_review_never_approves_by_exhaustion_and_hard_cap_blocks_resubmit`,
`test_review_approving_test_diff_requires_justification`.

## Outcome 4 — Feature-lock estendido (veto do revisor)

Veredito: **ATINGIDO**

Com manifesto producer+reviewer: deny sem review, deny em `in_review`/
`rejected`; **deny com aprovação DESATUALIZADA em relação à evidência mais
recente** (`review.updated_at < evidencia.recorded_at` — o achado específico
de reflect+judge), testado nas DUAS cópias (função importável
`evaluate_feature_list_edit` E hook standalone via subprocess real, gerado
por `render_boundary_guard()`); allow só com aprovação posterior à evidência.
Defesa em profundidade da justificativa de diff de teste lida do disco. Sem
manifesto (ou papéis incompletos), comportamento idêntico à Fase 3 — zero
regressão.
Testes: `test_feature_lock_requires_approved_review_when_team_declared`,
`test_feature_lock_without_manifest_behaves_like_fase3`,
`test_feature_lock_denies_stale_approval_older_than_evidence`,
`test_feature_lock_standalone_hook_also_denies_stale_approval`,
`test_feature_lock_test_diff_approval_requires_justification_on_disk`.

## Outcome 5 — `supervisor.on_feature_verified` acionado de verdade pela CLI

Veredito: **ATINGIDO**

Via subprocess real (`python -m harness.cli verify T-01 --dir <projeto>`)
num projeto com time compilado pela própria CLI (`team generate`):
`.harness/review/T-01.json` aparece com `status='in_review'`, `iteration=1`
sem que o teste tenha chamado `review submit` manualmente — prova que o
achado de reflect+judge (código antes morto) foi corrigido de ponta a ponta.
Controle negativo: sem time compilado, `verify` não cria nenhum registro de
revisão (zero regressão do comportamento da Fase 3).
Testes: `test_cli_verify_auto_submits_review_when_team_compiled`,
`test_cli_verify_without_team_does_not_create_review`.

## Outcome 6 — `team_audit` detecta os 3 invariantes

Veredito: **ATINGIDO**

Time gerado de verdade (`generate_team`), sem edição manual: score 100, zero
findings. Sabotagem manual do disco reproduz cada invariante: agente órfão
(`warning orphan_team_agent`), ferramenta extra no reviewer
(`critical team_agent_extra_tools`, citando `Edit`), drift do bloco
gerenciado (`warning team_agent_drift`).
Testes: `test_team_audit_healthy_team_scores_100`,
`test_team_audit_detects_orphan_agent`,
`test_team_audit_detects_reviewer_extra_tool`,
`test_team_audit_detects_managed_block_drift`.

## Outcome 7 — Precedência corrigida de `recommend_pattern`

Veredito: **ATINGIDO**

Sinal explícito de "supervisor"/"distribuir...paralelo" na descrição vence
`has_tests=True` (o cenário exato que a ordem original quebrava — repo real
com testes pedindo supervisor explicitamente). Demais ramos (sinal de
revisão, `has_tests` sozinho, default) corretos.
Testes: `test_recommend_pattern_supervisor_signal_beats_has_tests`,
`test_recommend_pattern_other_branches`.

## Outcome 8 — `dispatch_next` respeita `depends[]`

Veredito: **ATINGIDO**

Primeiro consumidor real do campo `depends[]` (parseado desde a Fase 1, nunca
antes ordenado por ninguém): dependência não satisfeita adia a feature; id
inexistente nunca fica pronta; ordem de arquivo não importa, só o grafo de
dependências; sem contrato devolve `None` sem exceção.
Testes: `test_dispatch_next_respects_depends`,
`test_on_feature_verified_is_noop_without_full_team`.

## Resultado agregado

```
$ python -m pytest tests/e2e/test_fase4_outcomes.py -q
.....................                                                    [100%]
21 passed in 4.34s

$ python -m pytest tests/ -q
(suíte completa do repo, incluindo Fases 1-3)
379 passed, 7 skipped in 60.49s
```

Zero gaps encontrados nesta rodada — nenhum ajuste de código de produção foi
necessário para os 8 outcomes fecharem verdes. Gate de encerramento E2E real
(dogfood, opt-in) já registrado separadamente em
`tests/e2e/evidence/fase4-dogfood-producer-reviewer.md`.
