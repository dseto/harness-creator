# Plans: atualização transparente do harness no projeto

## [T-01] O harness reconhece quando os arquivos de governança do projeto foram gerados por uma versão mais antiga do que a instalada na máquina
- files: `src/harness/autoupdate.py`, `tests/test_autoupdate.py`
- verify: `pytest tests/test_autoupdate.py -q`

Módulo novo com a parte pura da decisão: lê `plugin_version` de
`.harness/compiled-state.json` e compara com `harness.__version__` por
tupla semver (não por `!=`, como faz o `doctor`). Classifica quatro
estados — em dia, defasado, adiantado, ilegível/ausente — e diz quais
artefatos precisam ser regravados (`harness.yaml` presente -> `compile`;
`feature_list.json` presente -> `compile-session`). Não executa nada
ainda.

## [T-02] Recompilar o projeto nunca tira o desenvolvedor da branch em que ele está trabalhando
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `pytest tests/test_cli.py -q`

`harness compile-session` ganha `--no-branch`: compila os mesmos
artefatos, mas pula o bloco que posiciona o repositório em
`contract/<slug>` quando `branch_per_contract` está ativo. Sem isso, uma
recompilação disparada no início da sessão poderia mover a pessoa de
`main` para a branch do contrato sem ela pedir.

## [T-03] A atualização automática nunca quebra o comando que a disparou, nunca regride versão e obedece ao kill-switch e ao opt-out
- files: `src/harness/autoupdate.py`, `tests/test_autoupdate.py`
- verify: `pytest tests/test_autoupdate.py -q`
- depends: T-01, T-02

Executor da recompilação, no mesmo módulo: quando o veredito de T-01 é
"defasado", dispara `compile` e/ou `compile-session --no-branch` num
subprocess do próprio interpretador que já tem o pacote instalado, e
imprime uma linha só (`harness: recompilado 0.29.0 -> 0.30.0`). Falha do
subprocess vira aviso, nunca exceção. Veredito "adiantado" só avisa.
Kill-switch ativo (`.harness/harness.disabled`) ou
`HARNESS_AUTO_UPDATE=0` no ambiente: não faz nada. Estado "em dia" não
dispara subprocess algum.

## [T-04] Rodar qualquer comando do harness já deixa o projeto na versão instalada, sem passo extra
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `pytest tests/test_cli.py -q`
- depends: T-03

`main()` chama a verificação depois do parse e antes do dispatch. Ficam
de fora `compile` e `compile-session` (recursão), `doctor` (precisa
mostrar o estado real, não corrigi-lo) e `status`/`enable`/`disable` (o
kill-switch tem de funcionar em qualquer estado). Cobre também as skills
`/harness-creator:*`, que chamam a CLI.

## [T-05] Abrir uma sessão do Claude Code também atualiza o projeto, sem ninguém rodar comando nenhum
- files: `src/harness/session_start.py`, `tests/test_session_start.py`, `src/harness/autoupdate.py`
- verify: `pytest tests/test_session_start.py -q`
- depends: T-03

O script `SessionStart` gerado passa a disparar a mesma verificação. Dois
cuidados que o código atual impõe: o hook é lançado com `-S -E`
(`hook_launcher.py:119`), então o subprocess precisa ser um Python novo
SEM essas flags para enxergar `site-packages` e importar `harness`; e o
hook continua stdlib-only, com timeout e `except` amplo — falha na
atualização nunca pode impedir a injeção de contexto da sessão.

## [T-06] O ciclo completo funciona num repositório de verdade: estado antigo entra, versão atual sai, branch intacta
- files: `tests/e2e/test_autoupdate_flow.py`
- verify: `pytest tests/e2e/test_autoupdate_flow.py -q`
- depends: T-04, T-05

Repositório temporário com `harness.yaml`, contrato compilado,
`branch_per_contract` ativo e `compiled-state.json` gravado com uma
versão antiga. Roda um comando coberto pelo gatilho e prova: o
`plugin_version` passou a ser o do pacote instalado, a branch ativa não
mudou, e o comando original produziu a saída de sempre.

## [T-07] A documentação passa a descrever a atualização como um passo só
- files: `docs/plugin/TUTORIAL.md`, `docs/plugin/GUIDE.md`, `README.md`
- verify: `pytest tests/test_docs_enforcement_claims.py -q`
- depends: T-06

Atualiza as instruções de atualização: instalar o pacote é o único passo
manual; o projeto se recompila sozinho no uso seguinte. Documenta o
opt-out `HARNESS_AUTO_UPDATE=0`, os comandos deliberadamente isentos, e o
que continua manual (pacote pip e cache de plugin do Claude Code).
