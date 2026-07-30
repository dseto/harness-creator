## [T-01] `skills/plan/SKILL.md` ganha um passo explícito para rodar `harness finish` na branch do contrato, antes do commit final
- files: `skills/plan/SKILL.md`, `tests/test_finish_lifecycle_docs.py`
- verify: `pytest tests/test_finish_lifecycle_docs.py -k plan_skill -q`

## [T-02] `docs/plugin/GUIDE.md` § 10 documenta a ordem recomendada (branch do contrato, antes do PR)
- files: `docs/plugin/GUIDE.md`, `tests/test_finish_lifecycle_docs.py`
- verify: `pytest tests/test_finish_lifecycle_docs.py -k guide_secao_10 -q`
