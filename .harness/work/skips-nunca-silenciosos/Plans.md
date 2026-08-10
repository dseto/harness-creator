# Plans: nenhum teste pulado passa despercebido

## [T-01] A saída de qualquer runner de teste passa a ser lida: quantos testes pularam, por quê quando o motivo aparece, e se nenhum teste chegou a ser coletado
- files: `src/harness/skips.py`, `tests/test_skips.py`
- verify: `pytest tests/test_skips.py -q`

## [T-02] Toda execução de `harness verify` diz quantos testes pularam, verde ou vermelho, sem precisar de flag — e quando os motivos não estão visíveis na saída, diz isso e ensina como revelá-los
- files: `src/harness/verify.py`, `tests/test_verify_skips.py`
- verify: `pytest tests/test_verify_skips.py -q`
- depends: T-01

## [T-03] Um comando explícito roda a suíte, mostra ao humano tudo o que pulou e grava essa lista como o conjunto conhecido; a verificação normal nunca escreve essa lista sozinha
- files: `src/harness/skips.py`, `src/harness/cli.py`, `src/harness/boundary_guard.py`, `tests/test_skips_baseline.py`, `tests/e2e/evidence/fase2-outcomes-verification.md`
- verify: `pytest tests/test_skips_baseline.py -q`
- depends: T-01

## [T-04] Um teste que começa a pular do nada derruba a verificação e nomeia o que pulou; o que já era conhecido passa sem atrito, e o que deixou de pular só informa
- files: `src/harness/verify.py`, `src/harness/skips.py`, `tests/test_skips_delta.py`
- verify: `pytest tests/test_skips_delta.py -q`
- depends: T-02, T-03

## [T-05] Teste pulado por falta de variável de ambiente, credencial ou ferramenta para o trabalho já na primeira vez, nomeando o que falta — e o dono do repositório libera os pulos legítimos uma única vez no arquivo de configuração
- files: `src/harness/skips.py`, `src/harness/verify.py`, `src/harness/config.py`, `tests/test_skips_actionable.py`
- verify: `pytest tests/test_skips_actionable.py -q`
- depends: T-02

## [T-06] A prova gravada em disco passa a registrar o que pulou, para que quem abrir a evidência semanas depois veja a mesma coisa que quem rodou viu
- files: `src/harness/verify.py`, `tests/test_skips_evidence.py`
- verify: `pytest tests/test_skips_evidence.py -q`
- depends: T-02

## [T-07] O arquivo de configuração do harness passa a nascer com todas as opções que ele aceita, cada uma com seu valor padrão e uma linha explicando — nenhuma opção fica descobrível só lendo o código
- files: `src/harness/config.py`, `src/harness/templates.py`, `skills/init/SKILL.md`, `tests/test_config_template.py`
- verify: `pytest tests/test_config_template.py -q`
- depends: T-05

## [T-08] A documentação continua batendo com o código depois do módulo e do subcomando novos: as contagens que ela declara conferem
- files: `README.md`, `docs/reference/loop-engineering-design.md`, `AGENTS.md`, `docs/plugin/TUTORIAL.md`, `docs/plugin/ARCHITECTURE.md`, `docs/plugin/arquitetura-visual.html`
- verify: `pytest tests/test_docs_derived_facts.py -q`
- depends: T-03, T-07
