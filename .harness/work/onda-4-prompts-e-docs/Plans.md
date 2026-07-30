## [T-01] Instrução de PYTHONPATH deixa de se repetir em 5 skills — vira 1 linha por skill mais uma explicação única no GUIDE
- files: `skills/plan/SKILL.md`, `skills/preflight/SKILL.md`, `skills/init/SKILL.md`, `skills/audit/SKILL.md`, `skills/team/SKILL.md`, `docs/plugin/GUIDE.md`, `tests/test_prompt_docs_dedup.py`
- verify: `pytest tests/test_prompt_docs_dedup.py -k pythonpath -q`

## [T-02] Assess delega a coleta mecânica a um subagente Haiku, mantendo o julgamento das dimensões no modelo forte
- files: `skills/assess/SKILL.md`, `tests/test_prompt_docs_dedup.py`
- verify: `pytest tests/test_prompt_docs_dedup.py -k assess_model -q`

## [T-03] Anedota do kill-switch contada uma única vez, com TUTORIAL e ARCHITECTURE apontando para o GUIDE
- files: `docs/plugin/GUIDE.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/ARCHITECTURE.md`, `tests/test_prompt_docs_dedup.py`
- verify: `pytest tests/test_prompt_docs_dedup.py -k killswitch -q`
