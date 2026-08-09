## [T-01] O rastro de tentativas sabe distinguir falha transiente de falha estrutural, e o disjuntor conta só as estruturais
- files: `src/harness/attempts.py`, `tests/test_attempts.py`
- verify: `pytest tests/test_attempts.py -q`

## [T-02] `verify_cmd` com sinal transiente tenta de novo sozinho até 3× com pausa, sem gastar orçamento de correção; sinal não-transiente nunca tenta de novo
- files: `src/harness/verify.py`, `tests/test_verify.py`
- verify: `pytest tests/test_verify.py -q`
- depends: T-01

## [T-03] Falha transiente que insiste 3× vira veredito próprio do disjuntor — parada de ambiente, não padrão repetido nem teto de iterações
- files: `src/harness/budget.py`, `tests/test_budget.py`
- verify: `pytest tests/test_budget.py -q`
- depends: T-01

## [T-04] Todo veredito de parada do disjuntor vem com o bloco de escalada nas seis partes que o §8 exige, pronto para copiar ao humano
- files: `src/harness/escalation.py`, `src/harness/cli.py`, `tests/test_escalation.py`, `tests/test_cli.py`
- verify: `pytest tests/test_escalation.py tests/test_cli.py -q`
- depends: T-03

## [T-05] O passo 10 do lifecycle documenta o retry transiente e manda usar o bloco de escalada gerado em vez de escrever a mensagem à mão
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/arquitetura-visual.html`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-04
