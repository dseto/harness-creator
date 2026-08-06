---
slug: governanca-parcial-invisivel-sem-init
approved_by: Daniel Seto
approved_at: 2026-08-06T18:33:19Z
stop_conditions:
  - "3 falhas consecutivas do mesmo teste (`pytest -k <mesmo nome>`)"
  - "uma correção exigir mudar a semântica de `load_extra_allowed_commands`/`load_protected_branches` (permanecem non-fatal por design — fora de escopo)"
---

# Spec: Governança parcial sem `harness init` deixa de ser invisível

## Resumo executivo
Hoje dá pra rodar o ciclo inteiro do harness (plan → contrato → sessão →
trabalho) num repositório que nunca rodou a instalação inicial
(`/harness-creator:init`). O guard funciona, mas metade da governança
(proteção de testes, política de aprovação) nunca foi ligada — e nada avisa
disso. Depois desta mudança, o harness continua funcionando do mesmo jeito
nesse cenário (nenhum comando novo passa a falhar), mas avisa claramente,
nos 3 lugares onde o operador olha o estado do projeto, que está rodando
com proteção reduzida e por quê.

## Escopo
Repo sem `.harness/harness.yaml` (nunca rodou `init`) mas com
`.harness/feature_list.json` compilado (rodou `plan`/`compile-contract`
direto) consegue chegar a `compile-session` funcionando. Três pontos do
código tratam essa ausência de forma silenciosa ou quebrada:

1. `compile_session_permissions` (`src/harness/session_permissions.py:272`)
   e o dispatch de `compile-session` em `src/harness/cli.py:432` não
   verificam `.harness/harness.yaml` — nenhum aviso sai quando ele falta.
2. `run_doctor` (`src/harness/doctor.py:236`) só emite `issues`/`notes`
   quando `governed` (yaml presente); e `status` (`src/harness/killswitch.py:70`,
   despachado em `src/harness/cli.py:728`) não reporta esse estado.
3. `allowlist_yaml_hint` (`src/harness/boundary_guard.py:334`) sempre omite
   a chave `governance:` do bloco colável, assumindo que o arquivo (e a
   chave) já existem — falso quando não rodou `init`.

## Critérios de aceitação
- Repo com `feature_list.json` mas sem `harness.yaml`: `harness
  compile-session --dir <repo>` imprime em stderr um aviso citando que
  `.harness/harness.yaml` não existe, que hook TDD e política de aprovação
  não foram instalados, e que `/harness-creator:init` resolve — sem sair
  com erro/exit != 0 por causa disso.
  Prova: `pytest tests/test_session_permissions.py -q` e
  `pytest tests/test_cli.py -q -k compile_session`
- Mesmo cenário (`feature_list.json` presente, `harness.yaml` ausente):
  `harness status --dir <repo>` e `harness doctor --dir <repo>` reportam o
  mesmo estado (campo/nota citando `harness.yaml` ausente e governança
  parcial) — `doctor` sai com `ok`/exit 0 continua permitido (não é um
  "issue" que bloqueia, é uma "note"/aviso informativo, dado que o repo
  pode legitimamente nunca ter rodado `init`).
  Prova: `pytest tests/test_doctor.py -q` e `pytest tests/test_killswitch.py -q`
- Repo sem `.harness/harness.yaml` (ou com ele mas sem a chave
  `governance:`): o bloco retornado por `allowlist_yaml_hint` inclui a
  chave `governance:` no YAML colável. Repo com `harness.yaml` e chave
  `governance:` já presente continua omitindo a chave (comportamento atual
  preservado — colar de novo duplicaria a chave).
  Prova: `pytest tests/test_boundary_guard.py -q -k allowlist_yaml_hint`
- Teste de integração usando cópia de `C:\Projetos\MinimumAPI` (repo .NET
  real, já governado — tem `.harness/harness.yaml` próprio) como fixture:
  prova, contra um projeto real fora do fixture sintético de testes, que
  (a) o cenário do issue #72 não regrediu — remover `harness.yaml` da
  cópia e rodar `compile-session`/`status`/`doctor` emite os avisos dos
  3 critérios acima; (b) o fluxo GOVERNADO da cópia (com `harness.yaml`
  intacto) continua saindo limpo, sem os avisos novos aparecendo onde
  não deveriam (nenhuma regressão introduzida pelas mudanças).
  Prova: `pytest tests/test_integration_minimumapi.py -q`

## Não-objetivos
- Não mexer na degradação graciosa em si: `load_extra_allowed_commands` e
  `load_protected_branches` continuam non-fatal, retornando defaults
  quando o yaml falta.
- Não tornar `.harness/harness.yaml` obrigatório para `compile-session` —
  ele continua funcionando sem o arquivo.
- Não adicionar um comando novo (`harness init-check` etc.) — os avisos
  entram nos comandos que já existem (`compile-session`, `status`,
  `doctor`).
- A cópia de `C:\Projetos\MinimumAPI` vai para um diretório temporário
  (`tmp_path`) a cada teste; o projeto original nunca é modificado.
  `bin/`, `obj/`, `*.db`, `*.db-shm`, `*.db-wal` e os logs (`api_*.log`)
  ficam fora da cópia — não são relevantes para o harness e só pesam o
  teste.

## Unknowns
(nenhum — profile já analisado nesta sessão do repo-alvo, achados
confirmados por leitura direta do código-fonte citado acima)
