---
slug: atritos-do-ciclo
approved_by: Daniel Seto
approved_at: 2026-07-28T23:30:21Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd sem hipótese nova — parar e devolver ao humano"
  - "Um fix exigir transformar um deny de floor em allow além do que este contrato declara — parar e perguntar"
  - "A correção do e2e exigir mudar código de produção em vez do teste — sinal de que o bug não é do teste; parar e reportar"
---

# Spec: corrigir os cinco atritos do ciclo achados com o guard ligado

## Resumo executivo
Na primeira demanda rodada de ponta a ponta com a governança de fato ativa,
cinco coisas atrapalharam quem estava trabalhando — sem que nenhuma delas
protegesse nada. Em quatro casos o agente foi impedido de fazer algo inofensivo
que o próprio processo exige dele; no quinto, foi impedido corretamente, mas a
mensagem não dizia o que fazer em seguida. Este contrato corrige os cinco sem
afrouxar nenhuma regra de segurança: continua valendo tudo o que era barrado
por um motivo real.

## Escopo

Os cinco atritos foram registrados durante o contrato `harness-finish`
(v0.25.0). Nenhum é hipotético — todos apareceram ao vivo.

**1. Não há rota sancionada para ler o relógio.** A skill `plan` EXIGE carimbar
`approved_at` com o timestamp ISO atual no momento da aprovação, e o guard nega
todas as formas de obtê-lo: `date` e `python -c` são deny. Na prática o agente
fica sem como cumprir a própria regra do processo. `date` entra em
`READONLY_SHELL_UTILITIES`, com as flags de ESCRITA do relógio (`-s`, `--set`)
barradas — mesmo padrão já usado para `find` (`FIND_WRITE_FLAGS`) e para
`grep`/`rg` (`GREP_RG_EXEC_FLAGS`), onde um utilitário read-only tem um punhado
de flags que o tornam destrutivo.

**2. Não dá para rodar regressão no meio de um contrato.**
`_collect_allowed_bash_commands` monta a superfície de comando com o
`verify_cmd` de cada tarefa mais `lint_command`, `typecheck_command` e
`build_command` do `repo-profile.json` — e ignora o `test_command`, que está no
mesmo profile. A assimetria é pura: o lint do projeto roda a qualquer momento,
o teste do projeto só na grafia exata do `verify_cmd` da tarefa. O efeito é que
uma mudança em código compartilhado não pode ser testada contra o resto da
suíte antes do commit. O `test_command` do profile passa a entrar na mesma
lista.

Ressalva de diagnóstico, para quem for mexer: depois que TODAS as features do
contrato passam, `_contract_fully_passed` aposenta o guard da superfície e
qualquer `pytest` passa a ser aceito. Isso mascara o furo se o teste for feito
no fim do ciclo.

**3. `git branch --show-current` é negado** apesar de ser leitura pura. Entra em
`FIXED_GIT_SEQUENCES` como sequência de TRÊS tokens: `["git", "branch"]` com
dois tokens liberaria `git branch -D <nome>`, que apaga branch.

**4. A suíte e2e depende do encoding do console.**
`tests/e2e/test_contract_flow.py` falha no Windows porque o `subprocess.run` do
teste decodifica a saída como UTF-8 enquanto o processo filho escreve em
cp1252; a thread leitora morre com `UnicodeDecodeError` e o `stderr` chega
`None`, quebrando o assert com um `TypeError` que não tem nada a ver com o que
está sendo testado. Passa com `PYTHONIOENCODING=utf-8`, o que confirma a causa.
A correção é no teste — declarar `encoding`/`errors` na chamada — e não no
código de produção.

**5. Commitar chore na `main` é negado, e a mensagem não ajuda.** A regra de
trabalho deste repo manda bump de versão, CHANGELOG e correção de doc irem
direto para a `main`, mas `git commit` em branch protegida é deny incondicional
do floor. **O floor está certo e permanece intacto** — decisão explícita do
usuário nesta rodada. O que muda é a mensagem: hoje ela oferece duas saídas,
`git checkout -b` e `harness compile-session`, e as duas são conselho errado
para um chore de release, que por política vai direto para a `main`.

O deny passa a nomear uma TERCEIRA saída, sempre — e a dizer explicitamente que
ela não é do agente: quando a mudança é chore de doc/versão que a política do
repo manda ir direto para a `main`, o caminho é pedir ao humano que rode o
commit no terminal dele, não procurar outra rota.

A saída é incondicional em vez de condicionada ao conteúdo do diff staged
porque classificar "chore" por caminho não funciona: neste próprio repo o bump
de versão toca `src/harness/__init__.py`, onde mora o `__version__`, e nenhuma
allowlist genérica de documentação pega um arquivo `.py` sem virar regra
específica deste repositório. O custo aceito é a linha aparecer em todo deny de
branch protegida; por isso o texto precisa deixar claro que a decisão é do
humano, para não ensinar o agente a contornar o gate de PR.

**6. O resumo de progresso não é regenerado depois de uma demanda encerrada.**
Achado ao compilar ESTE contrato — é um defeito entregue na v0.25.0, pelo
próprio `harness finish`. O stub que ele grava abre com ``Contrato `<slug>`
ENCERRADO``, mas `install_templates` só regenera o arquivo quando consegue ler
o slug antigo pelo header canônico ``Contrato: `<slug>` `` — com dois-pontos e
terminando em crase. Sem casar, `_extract_progress_contract` devolve `None`, a
regeneração é pulada e o arquivo é preservado.

O efeito é que a sessão seguinte herda o resumo da demanda ANTERIOR: ao
compilar este contrato, o `progress.md` seguia afirmando que o contrato ativo
era o `harness-finish`, já encerrado, e o hook `SessionStart` injetou
"nenhuma feature pendente" numa sessão com cinco tarefas a fazer. É exatamente
o modo de falha que o `finish` existe para matar, reintroduzido por ele. A
correção é o stub emitir a linha canônica e declarar o encerramento na linha
seguinte — um formato só, um parser só.

## Critérios de aceitação

- `date` e `date -u +%Y-%m-%dT%H:%M:%SZ` são allow; `date -s "..."` e
  `date --set ...` continuam deny — prova:
  `python -m pytest tests/test_boundary_guard.py -k date -q`
- Com um `test_command` no `repo-profile.json`, o comando correspondente é
  allow mesmo com o contrato ainda em andamento (nem todas as features
  passando) — prova:
  `python -m pytest tests/test_boundary_guard.py -k profile_test_command -q`
- `git branch --show-current` é allow e `git branch -D qualquer-coisa`
  continua deny — prova:
  `python -m pytest tests/test_boundary_guard.py -k show_current -q`
- `tests/e2e/test_contract_flow.py` passa sem depender de `PYTHONIOENCODING`
  no ambiente — prova:
  `python -m pytest tests/e2e/test_contract_flow.py -q`
- Na branch protegida, a razão do deny nomeia a terceira saída — chore de
  doc/versão é decisão do humano e vai no terminal dele — sem deixar de dizer
  que a rota normal continua sendo o PR — prova:
  `python -m pytest tests/test_boundary_guard.py -k chore -q`
- Depois de `harness finish` encerrar uma demanda, compilar o contrato seguinte
  regenera o `.harness/progress.md` com o contrato NOVO — prova:
  `python -m pytest tests/test_finish.py -k regenera -q`

## Não-objetivos

- Afrouxar qualquer regra de floor. Nenhum deny existente vira allow, exceto os
  três comandos de LEITURA nomeados acima (`date` sem flag de escrita,
  `git branch --show-current`, e o `test_command` já declarado no profile).
- Permitir commit direto na `main`. Decisão explícita: o floor de branch
  protegida fica como está; só a mensagem melhora.
- Liberar `python -c`. É execução arbitrária de código — resolver o problema do
  relógio com ele seria abrir uma porta larga para fechar uma janela.
- Mexer no `test_glob` ou na superfície de ESCRITA. Os cinco atritos são todos
  de superfície de COMANDO, menos o #4, que é um bug de teste.
- Endereçar o resto da issue #52 (`audit-runtime`, `doctor`, `SessionStart`
  cegos ao kill-switch). O `harness finish` já cobre o momento do fecho.
- Bump de versão e CHANGELOG, que seguem como chore direto na `main` após o
  merge.

## Unknowns

- Nenhum. O alvo é o próprio repositório do harness-creator, cujo
  `repo-profile.json` foi regravado nesta sessão e não trouxe `unknowns`.
