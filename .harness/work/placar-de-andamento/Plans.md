## [T-01] `harness status --brief` mostra o placar do chat montado por código: progresso X/N, tarefas com estado, tarefa atual com tentativa n/teto, última prova com o erro, métrica quando houver e próximo passo — markdown+unicode, sem ANSI; `harness status` sem flag continua com o JSON de hoje byte-idêntico
- files: `src/harness/panel.py`, `src/harness/cli.py`, `tests/test_panel.py`
- verify: `pytest tests/test_panel.py -q`

## [T-02] `harness status --panel` mostra o mesmo placar colorido no terminal (cor só em TTY; em pipe sai texto puro) e `--watch N` re-renderiza sozinho no intervalo pedido
- files: `src/harness/panel.py`, `src/harness/cli.py`, `tests/test_panel.py`
- verify: `pytest tests/test_panel.py -q`
- depends: T-01

## [T-03] A barra do Claude Code passa a mostrar sempre demanda, progresso, tarefa, tentativa, último veredito e o custo da sessão quando o CLI o fornecer — `compile-session` instala a statusline e recompilar não duplica nem deixa entrada órfã
- files: `src/harness/statusline.py`, `src/harness/cli.py`, `tests/test_statusline.py`
- verify: `pytest tests/test_statusline.py -q`
- depends: T-01

## [T-04] O lifecycle manda colar `harness status --brief` na abertura de cada iteração, na transição de fatia e em parada — e proíbe redigir o placar de cabeça
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `README.md`, `docs/plugin/arquitetura-visual.html`, `AGENTS.md`
- verify: `pytest tests/test_lifecycle.py -q`
- depends: T-01

## [T-06] Quem lê a documentação do plugin encontra o placar: tutorial, guia e arquitetura passam a mostrar os três renders, a statusline entre os artefatos gerados e os dois módulos novos na tabela de camadas
- files: `docs/plugin/TUTORIAL.md`, `docs/plugin/GUIDE.md`, `docs/plugin/ARCHITECTURE.md`, `tests/test_docs_placar.py`, `.harness/work/placar-de-andamento/spec.md`, `.harness/work/placar-de-andamento/Plans.md`
- verify: `pytest tests/test_docs_placar.py -q`
- depends: T-01

## [T-08] O rastro de tentativas que o próprio harness escreve deixa de travar o fecho da demanda: `.harness/attempts/` passa a ser artefato gerenciado, como a evidência e o veredito cego
- files: `src/harness/branching.py`, `tests/test_branching.py`
- verify: `pytest tests/test_branching.py -q`
- depends: T-01

## [T-07] O produto se apresenta na versão que ele realmente é: v0.34.0 nas três fontes manuais, nos marcadores de versão da documentação e com a entrada de CHANGELOG do placar
- files: `src/harness/__init__.py`, `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`, `README.md`, `docs/plugin/ARCHITECTURE.md`, `docs/plugin/arquitetura-visual.html`, `docs/plugin/GUIDE.md`, `docs/reference/CHANGELOG.md`, `tests/test_version_sync.py`
- verify: `pytest tests/test_version_sync.py -q`
- depends: T-06

## [T-05] Escalada, fecho e disjuntor falam resultado para o humano no stderr — inclusive o `harness finish`, que hoje não fala nada — e o JSON do stdout dos três continua byte-idêntico
- files: `src/harness/escalation.py`, `src/harness/finish.py`, `src/harness/budget.py`, `src/harness/cli.py`, `tests/test_escalation.py`, `tests/test_finish.py`, `tests/test_budget.py`
- verify: `pytest tests/test_escalation.py tests/test_finish.py tests/test_budget.py -q`
- depends: T-01
