## [T-01] Inserir passo 15 (gate de aprovação humana) em lifecycle.py e renumerar 16/17
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`
- verify: `pytest tests/test_lifecycle.py -q`

## [T-02] Atualizar teste e2e do outcome 6 para 17 passos + gate de aprovação
- files: `tests/e2e/test_fase2_outcomes.py`
- verify: `pytest tests/e2e/test_fase2_outcomes.py -q -k outcome6`
- depends: T-01

## [T-03] Atualizar documentação corrente que cita "16 passos" para "17 passos"
- files: `docs/plugin/GUIDE.md`, `docs/plugin/TUTORIAL.md`, `docs/project/ROADMAP.md`, `skills/plan/SKILL.md`
- verify: `bash -c "for f in docs/plugin/GUIDE.md docs/plugin/TUTORIAL.md docs/project/ROADMAP.md skills/plan/SKILL.md; do grep -q '17 passos' $f || exit 1; done"`
- depends: T-01

## [T-04] Instruir skill plan (Passo 5) a sempre mostrar caminho relativo do contrato antes da aprovação
- files: `skills/plan/SKILL.md`
- verify: `grep -q "caminho relativo" skills/plan/SKILL.md`

## [T-05] Regressão completa (critério de aceitação top-level do spec.md)
- files: `src/harness/lifecycle.py`
- verify: `pytest tests -q`
- depends: T-01, T-02, T-03, T-04
