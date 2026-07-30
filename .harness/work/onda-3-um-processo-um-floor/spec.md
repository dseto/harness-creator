---
slug: onda-3-um-processo-um-floor
approved_by: Daniel Seto
approved_at: 2026-07-30T13:13:44Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd sem causa nova identificada"
  - "a tarefa do _evaluate_bash/_evaluate_powershell parecer exigir unificar a checagem de command substitution (\"$(\"/crase) entre os dois — isso reverteria uma decisão de segurança já documentada no código (backtick e \"$(\" são sintaxe legítima em PowerShell); parar e devolver ao humano em vez de fazer essa fusão"
  - "qualquer teste hoje verde em tests/test_boundary_guard.py, tests/test_compiler.py, tests/test_audit.py ou tests/test_docs_enforcement_claims.py quebrar fora do arquivo/tarefa em execução"
---

# Spec: Onda 3 — um processo, um floor

## Resumo executivo
O maior arquivo de segurança do produto (`boundary_guard.py`, o hook que decide
o que o agente pode ou não fazer) hoje roda em dois processos por comando de
terminal, tem duas implementações separadas do mesmo raciocínio de segurança
que já divergiram sutilmente uma da outra, e nega ferramentas nativas de
acompanhamento de tarefa do próprio Claude Code por engano. Depois desta onda:
um único processo avalia cada comando de terminal (mais rápido), a divergência
entre as duas implementações do veto do revisor fica travada por teste em vez
de invisível, e a auditoria do projeto detecta sozinha quando o hook instalado
ficou desatualizado em relação ao código-fonte.

## Escopo
Itens 2, 11, o restante do item 10 e item 17 do
[AUDIT-quick-wins-simplificacao-2026-07-30.md](../../../docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md),
seção "Onda 3 — um processo, um floor":

1. **Item 2 — dois processos por chamada de `Bash`.** `guard_test_runner.py`
   é um segundo hook (matcher `Bash`) registrado por `harness compile` que
   hoje SEMPRE devolve `allow` sem ler o comando
   ([compiler.py:153-199](../../../src/harness/compiler.py#L153)) — o
   `boundary_guard.py` (matcher `*`) já avalia todo `Bash` de qualquer forma,
   então esse segundo processo (≈125ms medidos) não muda nenhuma decisão
   hoje, só soma latência. Remove a geração/registro; se a disciplina de
   TDD precisar gatear execução de teste no futuro, isso entra dentro do
   roteamento único do `boundary_guard`, não como processo à parte.
2. **Item 17 — ferramentas nativas de tarefa negadas por engano.**
   `_UNKNOWN_WRITE_NAME_PATTERN` ([boundary_guard.py:3038](../../../src/harness/boundary_guard.py#L3038))
   nega qualquer tool desconhecida cujo nome contenha "write/create/edit" —
   e isso já negou `TaskCreate` numa sessão real deste projeto. `TaskCreate`,
   `TaskGet`, `TaskList`, `TaskOutput`, `TaskStop`, `TaskUpdate` são
   ferramentas nativas read-only-adjacentes de acompanhamento de tarefa do
   próprio Claude Code (não escrevem no repositório-alvo) e entram na
   allowlist conhecida junto de `Task` (que já está lá).
3. **Item 10 (restante) — drift do hook instalado é invisível.** `harness
   audit` hoje não compara o `boundary_guard.py` instalado em
   `.harness/hooks/` com o que o código-fonte atual geraria — o repo já
   viveu esse drift de verdade (hook compilado v0.28 rodando junto de
   pacote v0.29). `audit_project` passa a re-renderizar o hook em memória e
   comparar com o conteúdo em disco; divergência vira `finding` de severidade
   alta. `session_start.py` também avisa no início da sessão seguinte, pelo
   mesmo canal que já avisa sobre kill-switch desligado.
4. **Item 11 — duas cópias do mesmo raciocínio de segurança.**
   `_evaluate_bash`/`_evaluate_powershell`
   ([boundary_guard.py:2717](../../../src/harness/boundary_guard.py#L2717)/[:2899](../../../src/harness/boundary_guard.py#L2899))
   repetem a mesma sequência de 6 passos (floor de push/segredo/kill-switch,
   commit em branch protegida, bootstrap, coleta de `allowed_commands`,
   avaliação por segmento). Extrai um helper compartilhado só para os passos
   GENUINAMENTE idênticos, preservando a checagem de command substitution
   (`"$("`/crase) como exclusiva do Bash — ver correção abaixo sobre por que
   uma fusão total das duas funções não é segura.
   Adicionalmente: `_review_gate_problem`/`_load_review_record`
   ([boundary_guard.py:1434](../../../src/harness/boundary_guard.py#L1434)
   vs [:2438](../../../src/harness/boundary_guard.py#L2438)) — a versão
   importável e a versão embutida no script standalone já divergiram no
   tratamento de erro (`ReviewError` com mensagem própria de um lado,
   `except (OSError, ValueError)` com mensagens diferentes do outro). Ver
   correção abaixo sobre o fix real dessa divergência.

## Correção em relação ao laudo original
Duas correções encontradas ao verificar o código-fonte antes de escrever
este contrato:

1. **Item 2 não é esforço Baixo.** O laudo original marcou "Baixo". Ao
   levantar todo `grep -rl guard_test_runner`, o nome aparece em 8 arquivos
   de código/teste vivos além dos 3 arquivos de documentação do plugin
   (`compiler.py`, `hook_launcher.py` — comentário —, `boundary_guard.py` —
   comentário —, `killswitch.py` — docstring —, `test_compiler.py`,
   `test_hook_launcher.py`, `test_boundary_guard.py`, `test_audit.py`,
   `tests/e2e/test_boundary_flow.py`, `tests/e2e/test_fase2_outcomes.py` +
   evidência). Mesmo padrão do item 12 da Onda 1 (`guard_tests.py`): remover
   um mecanismo registrado exige atualizar toda prova que hoje afirma que
   ele existe. Esforço sobe para **Médio**; a ação continua correta e de
   risco baixo (o hook removido é comprovadamente inerte hoje).
2. **A ação sugerida para o item 11 ("embutir `review.py` via
   `inspect.getsource()`, padrão já usado no arquivo") não é executável como
   descrita.** O próprio módulo já documenta por quê
   ([boundary_guard.py:1246-1249](../../../src/harness/boundary_guard.py#L1246)):
   `harness.review` importa de `harness.analyzer` e `harness.patterns` —
   módulos que o hook standalone não pode importar (stdlib-only, `-S -E`
   desde a Onda 1). `getsource()` de uma função não embute suas dependências
   transitivas; embutir `_review_gate_problem` puxaria import não-stdlib
   junto. A correção real e segura: uma **prova de paridade** (teste que
   roda as duas implementações com os mesmos fixtures e compara o
   resultado) — trava a divergência existente sem prometer uma fusão que a
   própria arquitetura do hook impede. Mantido no escopo (é o mesmo tema —
   "1 floor, não 2" — e mora no mesmo arquivo/tarefa), com a técnica
   corrigida.

## Critérios de aceitação
- `harness compile` não gera nem registra mais `guard_test_runner.py`; todo
  teste/doc que hoje afirma que ele existe foi atualizado ou removido.
  Prova: `pytest tests/test_compiler.py tests/test_hook_launcher.py tests/test_boundary_guard.py tests/test_audit.py tests/test_docs_enforcement_claims.py -q`
- `TaskCreate`/`TaskGet`/`TaskList`/`TaskOutput`/`TaskStop`/`TaskUpdate` são
  `allow` explícito (não caem no ramo de tool desconhecida).
  Prova: `pytest tests/test_boundary_guard.py -q`
- `harness audit` relata divergência quando o `boundary_guard.py` instalado
  em disco não bate com o que o código-fonte atual geraria; `session_start`
  avisa disso na sessão seguinte.
  Prova: `pytest tests/test_audit.py tests/test_session_start.py -q`
- A sequência compartilhada entre `_evaluate_bash`/`_evaluate_powershell`
  vive num só lugar (sem duplicar os passos idênticos), a checagem de
  command substitution continua exclusiva do Bash, e existe teste de
  paridade travando `_review_gate_problem` importável vs. a versão embutida
  no script standalone.
  Prova: `pytest tests/test_boundary_guard.py -q`
- Suíte completa dos arquivos tocados permanece verde.
  Prova: `pytest tests/test_compiler.py tests/test_hook_launcher.py tests/test_boundary_guard.py tests/test_audit.py tests/test_session_start.py tests/test_docs_enforcement_claims.py tests/e2e/test_boundary_flow.py tests/e2e/test_fase2_outcomes.py -q`

## Não-objetivos
- Não unifica `_evaluate_bash`/`_evaluate_powershell` numa única função
  parametrizada por "flavor" — a checagem de command substitution
  (`"$("`/crase) é exclusiva do Bash por decisão de segurança já documentada
  no código (backtick/`$(` são sintaxe legítima em PowerShell); só os passos
  genuinamente idênticos (floor, bootstrap, coleta de `allowed_commands`)
  saem para um helper compartilhado.
- Não muda `harness.review` para virar stdlib-only — mudaria a API pública
  do módulo importável por um ganho de dedupe que a prova de paridade já
  entrega com risco menor.
- Não afrouxa nenhuma decisão de floor (rede, segredo, push fora do
  contrato, branch protegida, kill-switch) — todo o trabalho desta onda é
  ou remoção de código morto/inerte, ou extração sem mudança de
  comportamento, ou detecção nova (drift), nunca relaxamento de negação.
- Não adiciona `TaskCreate`/etc. a nenhuma allowlist de ESCRITA — elas
  entram como ferramenta read-only-adjacente conhecida
  (`_READONLY_ALLOWLIST_TOOLS`), igual a `Task` hoje.
- Não mexe em `doctor.py` — `MANAGED_HOOK_FILENAMES` mantém
  `guard_test_runner.py` deliberadamente (detecta o arquivo legado em
  instalações antigas, mesma razão que já mantém `guard_tests.py` lá desde
  a Onda 1).
- Não reabre o formato do registro de revisão
  (`.harness/review/<id>.json`) nem o schema de `feature_list.json`.

## Unknowns
(nenhum — escopo confirmado por leitura direta do código antes de escrever
este contrato)
