---
slug: setup-fail-closed-sem-init
approved_by: Daniel Seto
approved_at: 2026-08-16T00:34:41Z
stop_conditions:
  - "3 falhas consecutivas do mesmo teste (`pytest -k <mesmo nome>`)"
  - "uma correção exigir mudar os escapes de runtime do boundary_guard (task add-file, .harness/scratch/, YAML colável) — permanecem intocados por design, fora de escopo"
---

# Spec: Setup do ciclo vira fail-closed — plan/compile não rodam sem `harness init`

## Resumo executivo
Hoje um repositório que nunca rodou `/harness-creator:init` consegue atravessar
o ciclo inteiro (plan → contrato → implementação) com metade da governança
desligada e só um aviso em stderr no meio do caminho — que na prática ninguém
viu: numa sessão real o plano executou inteiro, alterações fora do contrato
passaram, e o harness só confessou no fim que faltava `harness.yaml` e que a
sessão não estava compilada. Depois desta mudança, os comandos que INICIAM o
ciclo se recusam a rodar sem a governança instalada, e os comandos de trabalho
se recusam a rodar quando há contrato ativo mas nenhum enforcement ligado
nesta máquina — sempre com mensagem dizendo o que aconteceu, por quê, e o
comando exato para voltar ao fluxo. O runtime (escapes baratos do guard) não
muda nada.

## Escopo
Reverte deliberadamente o não-objetivo do contrato
`governanca-parcial-invisivel-sem-init` ("não tornar `.harness/harness.yaml`
obrigatório para `compile-session`", spec.md:73-74, v0.30.0). O critério de
projeto "o harness barra o mínimo" foi criado para o RUNTIME — agente sozinho
por horas, deny duro empurra pro kill-switch. Setup é outro tempo: humano
presente, uma vez por projeto, custo de destravar é rodar `/harness-creator:init`
uma única vez. Barrar ali não gera pressão de kill-switch e fecha o furo real
observado (contrato decorativo: `feature_list.json` existe, nada o aplica).

Quatro frentes:

1. **Gate de setup nos compiladores**: `harness compile-contract` e
   `harness compile-session` falham (exit 1) quando `.harness/harness.yaml`
   não existe, com mensagem apontando `/harness-creator:init`. O aviso em
   stderr de v0.30.0 (CA-1 daquele contrato) deixa de existir nesses dois
   comandos — vira erro.
2. **Gate de trabalho nos comandos do ciclo**: `harness verify` e
   `harness supervise` falham quando há contrato ativo
   (`.harness/feature_list.json` presente) mas o enforcement não está
   instalado nesta máquina (hooks do harness ausentes do settings gerenciado
   `.claude/settings.local.json`, ou guard desativado via kill-switch sem que
   o operador saiba) — mensagem aponta `harness compile-session` (ou
   `harness on`, no caso do kill-switch). É o cenário do clone novo/segunda
   máquina: o contrato viaja pelo git, o enforcement não.
3. **Gate de entrada na skill plan**: o SKILL.md do `/harness-creator:plan`
   ganha um passo 0 explícito — sem `.harness/harness.yaml` no alvo, a skill
   para e redireciona para `/harness-creator:init` antes de qualquer
   entrevista. O preflight continua sendo o portão do repositório cru;
   o init passa a ser pré-requisito declarado do plan.
4. **Checagem de docs/versão no encerramento**: `harness finish` reporta se
   CHANGELOG/versão/marcadores precisam de atualização para esta entrega, e o
   passo de commit pergunta ao desenvolvedor — opcional por decisão dele,
   nunca automático e nunca silencioso.
5. **Registro e docs**: a reversão da decisão v0.30.0 entra em
   `.harness/decisions.md` (distinção setup-time vs runtime, para não ser
   re-litigada), e os docs que descrevem o comportamento "avisa, não bloqueia"
   do cenário sem init são atualizados.

`harness status` e `harness doctor` continuam read-only e continuam apenas
REPORTANDO governança parcial (notes) — comando de diagnóstico que falha
não diagnostica nada.

## Critérios de aceitação
- Repo com `.harness/work/<slug>/` aprovado mas SEM `.harness/harness.yaml`:
  `harness compile-contract --dir <repo> --slug <slug>` sai com exit 1 e a
  mensagem de erro contém o motivo (governança nunca instalada) e o comando
  de volta (`/harness-creator:init`). Com `harness.yaml` presente, compila
  como hoje.
  Prova: `pytest tests/test_contract.py -q -k setup_gate`
- Repo com `feature_list.json` mas sem `harness.yaml`:
  `harness compile-session --dir <repo>` sai com exit 1 com a mesma didática
  (o aviso stderr de v0.30.0 vira erro). Com `harness.yaml` presente,
  compila como hoje.
  Prova: `pytest tests/test_session_permissions.py -q -k setup_gate` e
  `pytest tests/test_cli.py -q -k compile_session_setup_gate`
- Repo com contrato ativo mas sem os hooks do harness no settings gerenciado
  (ou com kill-switch ligado): `harness verify <id>` e `harness supervise`
  saem com exit 1 nomeando o que falta e o comando de volta
  (`harness compile-session` / `harness on`); com enforcement instalado,
  comportamento atual preservado.
  Prova: `pytest tests/test_verify.py -q -k enforcement_gate` e
  `pytest tests/test_supervisor.py -q -k enforcement_gate`
- `skills/plan/SKILL.md` declara o gate de entrada (passo 0: checar
  `.harness/harness.yaml`, parar e redirecionar para `/harness-creator:init`
  se ausente) e não descreve mais o cenário "compila com aviso".
  Prova: `pytest tests/test_plan_skill_approval_flow.py -q -k setup_gate`
- Integração com repo real (fixture MinimumAPI, mesma infra do contrato
  v0.30.0): cópia SEM `harness.yaml` → `compile-session` falha com exit 1 e
  mensagem didática; cópia governada intacta → ciclo sai limpo, sem
  regressão.
  Prova: `pytest tests/test_integration_minimumapi.py -q`
- Docs que afirmavam "avisa, não bloqueia" para o cenário sem init
  (`docs/plugin/GUIDE.md`, `docs/plugin/TUTORIAL.md`) passam a descrever o
  gate fail-closed, e `.harness/decisions.md` registra a reversão com o
  racional setup-time vs runtime.
  Prova: `pytest tests/test_docs_enforcement_claims.py -q`
- `harness finish` passa a incluir na saída uma seção de checagem de
  docs/versão: versão corrente do pacote, se o CHANGELOG tem entrada para o
  contrato que está sendo encerrado, e se os marcadores de versão guardados
  por `tests/test_version_sync.py` estão coerentes. A seção é INFORMATIVA
  (nunca vira blocker — atualizar é opcional), e o passo de commit do
  lifecycle/skill instrui o agente a PERGUNTAR ao desenvolvedor, antes do
  commit, se quer incluir a atualização de docs/CHANGELOG/versão nesta
  entrega — nunca fazer sozinho, nunca pular a pergunta.
  Prova: `pytest tests/test_finish.py -q -k docs_version` e
  `pytest tests/test_finish_lifecycle_docs.py -q`

## Não-objetivos
- **Runtime intocado**: os escapes baratos do boundary_guard
  (`harness task add-file`, `.harness/scratch/`, YAML colável do deny de
  comando) e o runtime floor não mudam em nada. "Barrar o mínimo" continua
  valendo onde foi criado.
- **Comandos read-only continuam sem exigir init**: `analyze`, `status`,
  `doctor`, `health`, e as skills `preflight`/`assess` — o preflight é
  justamente a avaliação PRÉ-init e precisa rodar num repo cru.
- **Nenhum comando novo** (`init-check` etc.) — os gates entram nos comandos
  que já existem.
- **Sem migração retroativa**: repos que já rodaram o ciclo sem init não
  ganham correção automática; na próxima vez que rodarem um comando gateado,
  o erro os direciona.
- `load_extra_allowed_commands`/`load_protected_branches` continuam
  non-fatal com defaults (mesmo não-objetivo do contrato v0.30.0 — o que
  muda é a porta de entrada, não a degradação interna).

## Unknowns
- (nenhum — profile sem unknowns; furo reproduzido e confirmado pelo humano
  na sessão de assess: preflight → plan sem init, aviso invisível, plano
  executado com alterações fora do contrato)
