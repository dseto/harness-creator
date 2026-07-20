# BACKLOG DE EXECUÇÃO - CLAUDE CODE
# Correção de 3 pontos de fricção reais, achados numa sessão de dogfood real:
# implementação ponta a ponta da Story 2.6 (deleção de perfis) no projeto
# consumidor `elegant-heisenberg` via `plan` → aprovação → `compile-contract`
# → `compile-session` → loop `supervise`/`verify` nas 7 tarefas, com
# regressão final 100% verde (137 testes frontend + 116 testes de
# integração backend, zero quebra).
#
# Origem: observação direta durante a execução real, com file:line
# confirmado por leitura de código e/ou reprodução antes de qualquer item
# entrar aqui. Nenhum dos 3 é efeito colateral da remoção da era congelada
# (938df48/95d9cde/3cde0d3) — verificado: nenhum dos arquivos envolvidos foi
# tocado por esses commits; `orchestrator.py` (deletado) nunca referenciou
# `feature_list.json`/`passes` (grep confirma zero ocorrências).
#
# Alvo de código: `src/harness/contract.py`, `src/harness/verify.py`,
# `src/harness/cli.py`. Skill: `skills/plan/SKILL.md`.
#
# Validação global ao fechar: `$env:PYTHONPATH = "src"; python -m pytest
# tests -q` 100% verde + reprodução manual do item 1 (verify_cmd com saída
# UTF-8 não-ASCII, ex. `ng test`, sem `PYTHONUTF8=1` setado) sem
# UnicodeDecodeError.

---

## Item 1 — UnicodeDecodeError (cp1252) em subprocess de verify_cmd no Windows

**Achado:** `verify.py:136-141` (`run_verify`, execução real) e
`contract.py:316-323` (`_dry_check_verify_cmd`, `--dry-run-verify`) chamam
`subprocess.run(verify_cmd, shell=True, capture_output=True, text=True, ...)`
sem `encoding=` explícito. No Windows, `text=True` sem encoding cai no
codec do console (cp1252 no ambiente testado) — qualquer `verify_cmd` cuja
saída contenha bytes fora desse charset (checkmarks Unicode do `ng test`
via vitest, acentos) derruba a thread leitora do `subprocess` com
`UnicodeDecodeError`, poluindo stderr com traceback mesmo quando o comando
em si teve sucesso (exit 0).

**Reprodução confirmada nesta sessão:** `compile-contract --dry-run-verify`
sem `$env:PYTHONUTF8=1` setado → traceback em 4 threads leitoras
diferentes, uma por `verify_cmd` distinto testado. Com `PYTHONUTF8=1`
(usado nas chamadas subsequentes de `harness verify` desta sessão), o
sintoma não aparece — confirma que é exatamente esse o mecanismo, não
comando quebrado.

**Por que importa:** já era conhecido informalmente (`claude-progress.md`
do projeto consumidor documentava o mesmo contorno,
`$env:PYTHONUTF8=1`), mas o harness-creator nunca corrigiu na fonte — cada
projeto consumidor precisa redescobrir e contornar por conta própria.

**Correção:** adicionar `encoding="utf-8", errors="replace"` explícito nas
duas chamadas (`verify.py:136-141`, `contract.py:316-323`), em vez de
depender de `PYTHONUTF8` estar setado no ambiente de quem invoca o CLI.

**Verify:** `python -m pytest tests/test_verify.py tests/test_contract.py -q`
verde + teste novo que roda um `verify_cmd` com saída não-ASCII sem
`PYTHONUTF8` setado e confirma ausência de `UnicodeDecodeError`.

**Esforço:** S — **Risco se não corrigir:** baixo (contorno externo já
documentado, mas sói poluir stderr e confundir quem não conhece o contorno).

---

## Item 2 — Nenhum comando marca `passes:true` automaticamente após verify bem-sucedido

**Achado:** `harness verify <id>` (`verify.py`) roda o `verify_cmd`, grava
evidência em `.harness/evidence/<id>.json` (`exit_code`, `files_hash`), mas
**não** escreve de volta em `.harness/feature_list.json`. O campo `passes`
que `supervisor.py:57,64` lê para decidir a próxima tarefa só é alterado por
edição manual do JSON — confirmado por grep: nenhuma ocorrência de
`"passes"` em `cli.py`/`verify.py`.

**Por que é assim (intencional, não bug):** a nota de `skills/plan/SKILL.md`
("centralize as transições `passes:true` numa única sessão orquestradora")
já avisa que múltiplos agentes escrevendo em paralelo no mesmo
`feature_list.json` sem trava é uma corrida real — a ausência de um comando
automático hoje é a proteção contra isso, não uma omissão.

**Fricção observada:** mesmo numa sessão única e sequencial (sem paralelismo
algum, como a desta implementação), a orquestração exigiu editar o JSON via
Python inline 7 vezes (uma por tarefa) — puro boilerplate repetido, sem
ganho de segurança adicional numa sessão que já é sequencial.

**Correção proposta:** `harness verify <id> --mark-passed` (flag opt-in,
default continua sem marcar): se `exit_code == 0`, escreve `passes: true`
na feature correspondente do `feature_list.json` do próprio processo,
usando o mesmo mecanismo de leitura/escrita atômica que `compile-contract`
já usa (evita reintroduzir a corrida — sem lock entre processos, mas
dentro de UM processo que já correu o verify não há concorrência a
proteger). Não altera o comportamento default; skill (`plan/SKILL.md`)
passa a sugerir `--mark-passed` para sessões orquestradoras únicas e
continua alertando para não usá-lo com múltiplos agentes em paralelo no
mesmo `feature_list.json`.

**Verify:** `python -m pytest tests/test_verify.py -q` com caso novo:
`verify --mark-passed` em feature com `exit_code==0` grava `passes:true`;
sem a flag, comportamento atual (não grava) preservado; com
`exit_code!=0`, `--mark-passed` não marca nada.

**Esforço:** M — **Risco se não corrigir:** baixo (funciona hoje, é
ergonomia, não correção de bug).

---

## Item 3 — `dotnet build`/`dotnet test` como verify_cmd falha se a API do projeto-alvo estiver rodando

**Achado:** durante a execução real, `dotnet build backend/src/.../Api.csproj`
(verify_cmd de uma tarefa .NET) falhou com `MSB3027`/`MSB3021` — DLL de
saída bloqueada porque `GestaoProjetos.Api.exe` (a própria API do projeto
consumidor, iniciada via `start-all`) estava rodando e segurando o arquivo.
Não é bug do harness-creator (é comportamento normal do MSBuild em
Windows), mas o harness não avisa sobre essa classe de falha nem sugere a
causa — o agente vê só o erro cru do MSBuild.

**Por que importa:** verify_cmd de `dotnet build`/`dotnet test` é o padrão
recomendado pelo próprio harness-creator para monorepos .NET (visto nos
contratos `nudges-push` e `delecao-perfis` desta sessão) — a colisão com um
processo `dotnet run` do próprio projeto-alvo rodando em paralelo é um
cenário comum, não um caso de borda raro (qualquer dev com o app aberto
localmente esbarra nisso).

**Correção proposta:** não é código do harness-creator para "resolver"
(matar processo do usuário sem permissão seria pior) — é documentação. Em
`skills/plan/SKILL.md` (Passo 6/7) e/ou no template de `AGENTS.md` gerado
por `compile-session`, adicionar uma nota curta: "se um `verify_cmd` de
build/test de linguagem compilada falhar com erro de arquivo em uso/lock
(`MSB3027`, `EBUSY`, `Text File Busy`), é provável que um processo do
próprio projeto-alvo esteja rodando (ex.: `dotnet run`, `npm start`) —
pergunte ao usuário antes de encerrá-lo, não assuma".

**Verify:** revisão manual do texto adicionado — não é testável por pytest
(é conteúdo de skill/template, não lógica).

**Esforço:** S — **Risco se não corrigir:** baixo (a mensagem de erro do
MSBuild já aponta o PID que segura o lock; só falta uma pista contextual
pro agente não tratar como bug de código).
