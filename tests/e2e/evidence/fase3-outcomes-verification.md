# Evidência — Fase 3: verificação dos 6 outcomes

Gerado em 2026-07-19T02:13:30.229226+00:00 por `tests/e2e/test_fase3_outcomes.py` (repos sintéticos em tmp_path via subprocess da CLI real + hooks standalone gerados + funções públicas de módulo).

## Outcome 1 — harness verify roda o verify_cmd REAL; evidência (schema exato) só com exit 0; falha propaga o exit code real sem gravar nada

Veredito: **ATINGIDO**

`harness verify T-OK`: exit 0, o verify_cmd REAL rodou (efeito observável `verify_ran.txt` criado em disco), evidência gravada em `.harness/evidence/T-OK.json` com o schema EXATO de verify.py (feature_id/verify_cmd/recorded_at/exit_code/files_hash), `exit_code: 0`, `recorded_at` ISO8601 e `files_hash` idêntico ao recomputado de fora via `compute_files_hash`.

```json
{
  "feature_id": "T-OK",
  "verify_cmd": "echo verify-ok > verify_ran.txt",
  "recorded_at": "2026-07-19T02:13:26.452530+00:00",
  "exit_code": 0,
  "files_hash": "sha256:7bc04e06b6c59c8e34b9686c932b7eb9cbe315928da06a836a7e0031699d7ff6"
}
```
`harness verify T-FAIL` (verify_cmd `exit 7`): CLI saiu com exit code 7 — o código REAL do comando, não um 1 genérico — e NENHUM `.harness/evidence/T-FAIL.json` foi gravado.
Feature inexistente e diretório sem feature_list.json: exit 1 com erro legível no stderr (nunca evidência, nunca traceback).
`compute_files_hash` (chamada direta): insensível à ordem de files[] (sorted), prefixo `sha256:`, muda quando o conteúdo muda, e arquivo ausente usa a sentinela `<missing>` sem levantar exceção.

_Atualizado em 2026-07-19T02:13:30.229226+00:00 por esta rodada._

## Outcome 2 — get_stop_conditions expõe as stop conditions do spec.md (consistente com parse_spec) e o passo 10 do lifecycle cita essa fonte como disjuntor

Veredito: **ATINGIDO**

`get_stop_conditions` sobre spec com 3 condições (uma não-string, `42`): retorna `list[str]` normalizada e IDÊNTICA a `[str(x) for x in parse_spec(...)['stop_conditions']]` — mesma fonte do parser existente, nunca um segundo parse de frontmatter.
Chave `stop_conditions` ausente -> `[]`; chave nula -> `[]` (opcional no contrato, nunca levanta por ausência); spec.md inexistente -> `ContractError` (do próprio parse_spec).
`.harness/LIFECYCLE.md` instalado por `install_lifecycle` (o mesmo caminho de `compile-session`): o parágrafo do passo 10 cita explicitamente o campo `stop_conditions:` do frontmatter do `spec.md` ativo, o acessor `harness.contract.get_stop_conditions` e a palavra 'disjuntor' — a fonte do circuito de parada do loop de autocorreção é a mesma que o outcome (a) provou funcionar.

_Atualizado em 2026-07-19T02:13:30.229226+00:00 por esta rodada._

## Outcome 3 — feature-lock: passes:true só com evidência fresca (mais nova que o último commit); sem/velha evidência -> deny; edição sem transição mantém o deny de superfície

Veredito: **ATINGIDO**

Transição `passes: false -> true` via Edit SEM evidência em disco: deny citando T-01 e mandando rodar `harness verify` primeiro — nas DUAS cópias da lógica (hook standalone via subprocess E `evaluate_feature_list_edit` importável). Razão do hook: `feature-lock: transicao para passes:true sem evidencia fresca - T-01: sem evidencia (.harness/evidence/T-01.json nao existe ou JSON invalido) - rode harness verify <id> primeiro`
Evidência com `recorded_at` de 2020 (mais velha que o último commit, backdated para 2026-01-01): deny nas duas cópias, razão citando 'evidencia mais antiga que o ultimo commit'.
Mesma edição com evidência fresca (recorded_at = agora, mais nova que o último commit): ALLOW nas duas cópias, razão confirmando a evidência fresca de T-01 — o agente só marca done depois do `harness verify` real. Razão do hook: `feature-lock: transicao para passes:true com evidencia fresca confirmada para T-01`
Edição do feature_list.json que NÃO transiciona nenhuma feature (só muda desc): a versão importável delega (`None`) e o hook standalone cai no comportamento genérico de superfície -> deny ('fora da superficie do contrato ativo') — o feature-lock não abriu uma porta nova para edições arbitrárias do arquivo.

_Atualizado em 2026-07-19T02:13:30.229226+00:00 por esta rodada._

## Outcome 4 — hook Stop detecta feature em progresso sem verificação atualizada, silencia quando tudo verificado; compile-session instala idempotente sem matcher

Veredito: **ATINGIDO**

Working tree limpa: `is_feature_in_progress` False e o hook Stop standalone não imprime NADA (encerramento sem fricção quando não há trabalho pendente).
Diff não commitado tocando `src/app.py` (files[] de T-01), sem evidência: `is_feature_in_progress`/`needs_verification` True para T-01 (e False para T-02, intocada); o hook standalone devolve `additionalContext` citando SÓ T-01 e mandando rodar `harness verify`. Contexto: `Feature(s) em progresso sem verificacao atualizada: T-01. Rode `harness verify <id>` antes de encerrar a sessao para gravar a evidencia em .harness/evidence/<id>.json.`
Evidência gravada com o files_hash ATUAL: `needs_verification` False e o hook volta a silenciar — evidência atualizada encerra a cobrança.
Arquivo modificado DEPOIS da evidência (files_hash gravado != hash atual): `needs_verification` volta a True e o hook flagra T-01 de novo — evidência desatualizada não vale como prova.
`passes: true` nunca é 'em progresso' (mesmo com diff pendente); feature sem files[] nunca é 'em progresso' (sem pathspec não há como detectar trabalho — evita diff do repo inteiro).
`compile-session` (CLI real) instala o hook: chave `stop_hook` no JSON de saída, arquivo instalado idêntico a `render_stop_hook()`, UMA entrada em hooks.Stop SEM chave `matcher` (Stop não suporta matcher), e a segunda rodada não duplica (idempotente).

_Atualizado em 2026-07-19T02:13:30.229226+00:00 por esta rodada._

## Outcome 5 — audit-runtime pega os 2 invariantes como critical e usa is_feature_in_progress IMPORTADA de stop_hook (os dois módulos concordam no mesmo cenário)

Veredito: **ATINGIDO**

`harness.runtime_audit.is_feature_in_progress` É o mesmo objeto de `harness.stop_hook.is_feature_in_progress` (assert de identidade `is`) — a decisão de 'em progresso' tem UMA implementação, não duas.
Duas features com diff não commitado: `is_feature_in_progress` (stop_hook, chamada direta) flagra ['T-01', 'T-02']; `audit_runtime` emite UM finding `multiple_features_in_progress` critical citando exatamente esses ids — os dois lugares que decidem 'em progresso' concordam. Mensagem: `Mais de uma feature 'em progresso' simultaneamente: T-01, T-02.`
`git checkout -- src/b.py`: stop_hook deixa de flagrar T-02 e o finding `multiple_features_in_progress` some do audit — exatamente 1 feature em progresso é estado legal.
`passes: true` sem evidência -> critical `missing_evidence` citando T-02; evidência com `exit_code: 1` -> critical `evidence_exit_code_nonzero`; evidência válida com `exit_code: 0` -> zero findings, score 100.
CLI `harness audit-runtime`: exit 0 com score 100 no estado sadio; apagando a evidência de T-02 e o claude-progress.md -> exit 1 com score 45 (<60) e findings JSON parseáveis (['missing_evidence', 'missing_progress_file']).

_Atualizado em 2026-07-19T02:13:30.229226+00:00 por esta rodada._

