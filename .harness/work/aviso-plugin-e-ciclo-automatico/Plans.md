# Plans: parar de exigir do humano o que o harness já sabe

## [T-01] O harness sabe dizer qual instalação de plugin ficou para trás e qual comando exato corrige
- files: `src/harness/doctor.py`, `tests/test_doctor.py`
- verify: `pytest tests/test_doctor.py -q`

Extrai de `run_doctor` a comparação que hoje só existe dentro do laudo, numa
função reutilizável que devolve as instalações atrás do pacote instalado —
cada uma com id, versão e o comando `claude plugin update <id>` já montado.
Lista vazia para arquivo ausente, JSON inválido, versão em dia ou à frente. O
`doctor` passa a consumir a mesma função, para não existirem duas regras de
versão que possam divergir.

## [T-02] O estado do plugin viaja no payload que o hook de sessão já consome
- files: `src/harness/autoupdate.py`, `tests/test_autoupdate.py`
- verify: `pytest tests/test_autoupdate.py -q`
- depends: T-01

`python -m harness.autoupdate` ganha a chave do cache de plugin na saída JSON,
preenchida sempre — inclusive sem recompilação e com `HARNESS_AUTO_UPDATE=0`,
porque a variável desliga o agir, não o informar. Nenhum subprocesso novo: o
hook já dispara este.

## [T-03] A sessão começa com o aviso em destaque, o comando pronto para copiar e o reinício exigido
- files: `src/harness/session_start.py`, `tests/test_session_start.py`
- verify: `pytest tests/test_session_start.py -q`
- depends: T-02

O contexto injetado ganha o bloco de ação com o texto aprovado no `spec.md`:
cabeçalho em caixa alta, as duas versões, o comando isolado para copiar, a
exigência de reiniciar e a frase que deixa claro que nada está bloqueado. Some
por completo com o plugin em dia, ausente ou à frente.

## [T-04] O aviso chega ao contexto rodando o hook de verdade, sem bloquear nada
- files: `tests/e2e/test_autoupdate_flow.py`
- verify: `pytest tests/e2e/test_autoupdate_flow.py -q`
- depends: T-03

Estende o e2e existente com um `installed_plugins.json` real em disco: o hook
roda como subprocesso, o aviso aparece no `additionalContext`, e a saída
continua sendo JSON válido com o resto do contexto intacto. Prova a costura
entre as três peças, que é onde o risco mora.

## [T-05] O Pull Request chega pronto: comando exato e descrição montada a partir do contrato
- files: `src/harness/pr_draft.py`, `src/harness/cli.py`, `tests/test_pr_draft.py`
- verify: `pytest tests/test_pr_draft.py -q`

Comando novo `harness pr-draft`: grava `.harness/scratch/pr-body.md` com
título sugerido, tabela de tarefas com `verify_cmd` e situação da evidência, e
as seções de racional para o agente preencher; imprime em JSON o caminho do
corpo e o comando `gh pr create` com `--body-file` pronto para colar. Corpo em
arquivo, não em `--body` inline, porque acentuação em linha de comando no
PowerShell 5.1 corrompe multi-byte. Sem contrato compilado, erra com mensagem
clara em vez de gerar um corpo vazio.

## [T-06] O lifecycle passa a mandar commitar e empurrar sozinho, com prova verde como pré-condição
- files: `src/harness/lifecycle.py`, `tests/test_lifecycle.py`, `tests/e2e/test_fase2_outcomes.py`, `tests/e2e/evidence/fase2-outcomes-verification.md`
- verify: `pytest tests/test_lifecycle.py -q`

Os passos 15 e 16 do Agent Session Lifecycle deixam de exigir sinal verde
humano. O 15 passa a APRESENTAR o que será commitado (o diff continua
visível); o 16 commita e empurra a branch do contrato, condicionado a `harness
finish` com `blockers: []` e nenhum `verify_cmd` vermelho — as pré-condições
que substituem o gate humano. O texto declara explicitamente que abrir o PR
não é ação do agente.

## [T-07] Aprovar o contrato passa a ser o único pedido feito ao humano antes do PR
- files: `skills/plan/SKILL.md`, `tests/test_plan_skill_approval_flow.py`
- verify: `pytest tests/test_plan_skill_approval_flow.py -q`
- depends: T-05, T-06

O Passo 5 declara que a aprovação autoriza o ciclo inteiro; o Passo 9 passa de
"peça a aprovação do commit" para "commite, empurre e entregue o PR pronto via
`harness pr-draft`". O teste trava as duas metades, no padrão estrutural de
`test_finish_lifecycle_docs.py`: que a autorização está escrita, e que os
limites continuam escritos — proibição de auto-preencher `approved_by`/
`approved_at` e proibição de abrir PR.

## [T-08] A documentação explica a camada 3 e o gate único do ciclo
- files: `docs/plugin/GUIDE.md`, `README.md`, `docs/plugin/TUTORIAL.md`
- verify: `pytest tests/test_docs_enforcement_claims.py -q`
- depends: T-04, T-07

Fecha a tabela das 3 camadas na seção de atualização: a 2 se auto-corrige, a 3
avisa na abertura da sessão, a 1 segue manual — com as quatro razões pelas
quais bloquear a camada 3 foi descartado, para a decisão não voltar como
sugestão. Descreve o ciclo novo: um gate humano (o contrato), commit e push
automáticos, PR entregue pronto e aberto pelo humano.
