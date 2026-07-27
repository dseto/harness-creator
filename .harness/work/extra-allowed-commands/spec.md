---
slug: extra-allowed-commands
approved_by: "Daniel Seto"
approved_at: "2026-07-22T17:05:09Z"
stop_conditions:
  - "3 falhas consecutivas do verify_cmd DA MESMA TAREFA (contador por task-id, não pela string do comando) — parar e devolver ao humano com o log da última falha"
  - "Necessidade de mudar a semântica de matching JÁ existente de verify_cmd (prefixo de tokens via `_segment_prefixes_any`) — parar e perguntar; esta demanda REUSA o mecanismo, não o redesenha"
  - "Suíte completa (`python -m pytest tests -q`) quebrar em teste que NÃO pertence a esta demanda — parar e reportar a regressão sem tentar consertar código alheio"
  - "Necessidade de tocar `compiler.py` (Fase 1 — approval_policy) para o contrato fechar — parar; Fase 1 não tem conceito de allowlist por-comando, é não-objetivo confirmado"
---

# Spec: `governance.extra_allowed_commands` — comandos permanentes declarados pelo dono do repo

## Escopo

Hoje o `boundary_guard.py` (dispatcher único de fronteira, Fase 2) deriva a
superfície de `Bash`/`PowerShell` permitida SÓ a partir de:
1. `verify_cmd` das features do contrato ativo (`.harness/feature_list.json`);
2. `lint_command`/`typecheck_command`/`build_command`/instalação do
   `.harness/repo-profile.json` (`extras` + `package_manager`);
3. sequências fixas (`git status/log/diff/add/commit`, subcomandos do
   próprio `harness`);
4. utilitários read-only (`cat/head/tail/ls/grep/rg/...`) e `cd` intra-repo.

Não existe forma de declarar um comando adicional PERMANENTE — um CLI que É
o produto do repo (ex.: `python -m mar_committee` no repo `entebate`) fica
bloqueado pelo guard mesmo com todas as features `passes: true`, porque
`feature_list.json` não expõe esse comando em nenhum `verify_cmd` fora de um
contrato ad-hoc, e esse ad-hoc morre quando o próximo contrato substitui o
arquivo. O workaround atual (compilar um contrato cujos `verify_cmd` SÃO os
subcomandos do CLI) funciona mas é caro: exige plan + aprovação humana +
recompile toda vez.

Esta demanda adiciona `governance.extra_allowed_commands` (lista de strings)
ao schema de `.harness/harness.yaml`, e planeja o comando declarado nas DUAS
superfícies que já derivam de `verify_cmd`/lint/build/install/git-local hoje:

- **`boundary_guard.py`** (runtime, gate real): cada entrada de
  `extra_allowed_commands` é tokenizada e somada a `allowed_sequences` em
  `_evaluate_bash`/`_evaluate_powershell` — MESMA semântica de PREFIXO de
  tokens que `verify_cmd` já tem via `_segment_prefixes_any` (comentário do
  próprio pedido: "prefixo de tokens — mesma semântica do allow de verify_cmd
  hoje"). Nenhum mecanismo de matching novo — reuso puro.
- **`.claude/settings.json`** (`session_permissions.py`, enumeração nativa do
  Claude Code): cada entrada vira `Bash(<comando>*)`, mesmo estilo de
  `_HARNESS_CLI_ALLOW`/`_GIT_LOCAL_ALLOW` (prefixo com `*`, sem espaço antes).

O **runtime floor** (`git push`, `curl`/`wget`/`npm publish`/`pip upload`/
`twine upload`/`gh release`, escrita em segredo) continua bloqueio
INCONDICIONAL — roda ANTES de qualquer checagem de superfície nas duas
camadas hoje, então uma entrada de `extra_allowed_commands` que case o floor
nunca vira `allow`, sem precisar de código novo para essa garantia (só um
teste que PROVA isso).

### Decisões de arquitetura (fixadas por este contrato)

1. **Só Fase 2** (`boundary_guard.py`/`session_permissions.py`). O compilador
   Fase 1 (`compiler.py`, política `approval_policy` genérica + hooks
   `guard_tests.py`/`guard_test_runner.py`) não tem conceito de allowlist
   por-comando — não é tocado.
2. **O hook standalone continua stdlib-only.** `boundary_guard.py` (o script
   gerado, `render_boundary_guard()`) não pode importar `yaml`/`HarnessConfig`
   em runtime (roda fora do pacote instalado). Quem lê `.harness/harness.yaml`
   é código REAL do pacote (`load_extra_allowed_commands`, chamado por
   `install_boundary_guard`/`compile_session_permissions` NO MOMENTO da
   compilação) — o valor lido vira uma constante Python literal
   (`EXTRA_ALLOWED_COMMANDS = [...]`) BAKED no script gerado, mesmo padrão
   já usado para `FIXED_GIT_SEQUENCES`/`FIXED_HARNESS_SEQUENCES`. Mudou
   `harness.yaml` → precisa rodar `harness compile-session` de novo para o
   hook instalado refletir a mudança (mesma disciplina de qualquer outra
   mudança de superfície neste projeto).
3. **Leitura de `harness.yaml` é non-fatal.** Arquivo ausente, YAML inválido,
   ou `HarnessConfig.model_validate` falhando (schema divergente) →
   `extra_allowed_commands = []`, comportamento IDÊNTICO ao atual (sem
   crash, sem quebrar repos que ainda não têm o arquivo ou que o têm
   malformado). Mesma postura de degradação graciosa já usada para
   `.harness/repo-profile.json` ausente.
4. **Reuso de código entre os dois módulos.** `session_permissions.py` JÁ
   importa `is_floor_bash_command`/`is_floor_secret_path` de
   `harness.boundary_guard` (precedente de cross-import estabelecido) — o
   novo `load_extra_allowed_commands` mora em `boundary_guard.py` e é
   importado por `session_permissions.py`, sem duplicar a leitura do YAML.
5. **Sem DSL nova.** Cada entrada de `extra_allowed_commands` é uma string de
   comando literal (ex.: `"python -m mar_committee"`), tokenizada pelo MESMO
   `_tokenize_command` que já processa `verify_cmd`. Sem glob, sem regex.

## Critérios de aceitação

- **AC-1 (schema)**: `GovernanceConfig.extra_allowed_commands` aceita lista de
  strings a partir do YAML e default é `[]` quando a chave está ausente.
  Prova: `python -m pytest tests/test_config.py -q`.
- **AC-2 (boundary_guard allow)**: hook gerado com
  `extra_allowed_commands=["python -m mar_committee"]` e contrato ativo (sem
  nenhum `verify_cmd` cobrindo o CLI) permite `Bash` com comando
  `python -m mar_committee --help` e `python -m mar_committee config-show`
  (ambos prefixados pela sequência declarada). Prova:
  `python -m pytest tests/test_boundary_guard.py -q`.
- **AC-3 (prefixo exato, não substring)**: comando `mar_committee` (sem
  `python -m` na frente) continua negado — o match é prefixo de TOKENS
  (`tokens[:n] == seq`), não substring solto. Prova: mesmo arquivo.
- **AC-4 (floor tem precedência)**: `extra_allowed_commands` contendo uma
  sequência do runtime floor (`"git push"`, `"curl"`) NUNCA vira `allow` —
  testado explicitamente declarando o comando e confirmando `deny` com o
  motivo do floor. Prova: mesmo arquivo.
- **AC-5 (degradação graciosa)**: `install_boundary_guard`/
  `compile_session_permissions` sem `.harness/harness.yaml` no alvo (ou com
  YAML inválido) produzem exatamente o comportamento de HOJE (sem
  `extra_allowed_commands`, sem crash). Prova: ambos os arquivos de teste
  (`test_boundary_guard.py`, `test_session_permissions.py`).
- **AC-6 (settings.json)**: `render_session_permissions`/
  `compile_session_permissions` emitem `Bash(python -m mar_committee*)` em
  `permissions.allow` quando `extra_allowed_commands` declara o comando; uma
  entrada de floor declarada em `extra_allowed_commands` é filtrada e NUNCA
  aparece em `allow` (mesmo `_passes_runtime_floor_filter` já existente).
  Prova: `python -m pytest tests/test_session_permissions.py -q`.
- **AC-7 (lint)**: `ruff check src/harness/config.py src/harness/boundary_guard.py src/harness/session_permissions.py`
  sem findings.
- **AC-8 (zero regressão)**: `python -m pytest tests -q` inteira verde.
- **AC-9 (E2E dogfood, gate final)**: mock em disco reproduzindo o cenário
  real do repo `entebate` — contrato compilado + `.harness/harness.yaml` com
  `governance.extra_allowed_commands: ["python -m mar_committee"]` — instala
  o `boundary_guard.py` de verdade, invoca via `subprocess` real com
  `tool_name=Bash`/`command="python -m mar_committee config-show"` (esperado
  `allow`) e com um comando NÃO declarado e fora do `verify_cmd`/superfície
  (esperado `deny`). Evidência real (JSON das duas decisões) gravada em
  `tests/e2e/evidence/extra-allowed-commands-dogfood-2026-07-22.md`,
  commitada. Prova:
  `python -m pytest tests/e2e/test_extra_allowed_commands_e2e.py -q`.

## Não-objetivos

- Tocar `compiler.py` (Fase 1, `approval_policy`) — sem conceito de
  allowlist por-comando lá; fora de escopo.
- Subcomando/flag de CLI para gerenciar `extra_allowed_commands` — o dono do
  repo edita `.harness/harness.yaml` à mão e roda `harness compile-session`.
- Qualquer validação/sandboxing do comando declarado além do runtime floor
  já existente — declarar um comando perigoso-mas-fora-do-floor (ex.:
  `rm -rf`) é escolha de governança do dono do repo; o floor continua o
  único veto incondicional.
- Sintaxe de glob/wildcard dentro de uma entrada de `extra_allowed_commands`
  — string literal tokenizada, mesmo mecanismo de `verify_cmd`.
- Migração automática de repos existentes. Adicionar a chave no
  `.harness/harness.yaml` DESTE repo (dogfood) é conveniência opcional desta
  demanda, não requisito de nenhum critério de aceitação.
- Editar manualmente `.harness/feature_list.json` ou `.claude/settings.json`
  fora do fluxo `harness compile-session` — o contrato não introduz novo
  caminho de escrita direta desses artefatos.

## Unknowns

Nenhum unknown do profile se aplica — `.harness/repo-profile.json` já
confirma `languages=python`, `test_command=pytest`, `test_glob=tests/**/*.py`,
`extras.lint_command=ruff check .`; o único `unknown` do profile
(`package_manager: nenhum lockfile detectado`) é irrelevante para esta
demanda (não introduz dependência nova nem toca instalação).
