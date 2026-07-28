# Plans: item-8-preflight-read-only

## [T-01] Rodar o preflight volta a não escrever nada no repositório avaliado, nem perguntar nada a quem roda
- files: `src/harness/cli.py`, `src/harness/config.py`, `src/harness/preflight.py`, `tests/test_preflight.py`, `tests/e2e/evidence/preflight-dogfood-2026-07-17.md`
- verify: `python -m pytest tests/test_preflight.py -q`

## [T-02] Quando o comando de teste ou de lint não resolve, o laudo diz ao usuário exatamente qual comando rodar para corrigir
- files: `skills/preflight/SKILL.md`, `tests/test_preflight.py`
- verify: `python -m pytest tests/test_preflight.py -k skill -q`
- depends: T-01
