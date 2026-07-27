---
slug: lifecycle-gate-aprovacao-commit
approved_by: Daniel Seto
approved_at: 2026-07-23T10:44:08Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd"
---

# Spec: Gate de aprovação humana antes do commit no Agent Session Lifecycle

## Escopo
O Agent Session Lifecycle (`src/harness/lifecycle.py`, compilado em `AGENTS.md`
+ `.harness/LIFECYCLE.md`) hoje tem 16 passos; o passo 15 ("Commit apenas em
estado retomável") commita direto, sem parar para aprovação humana. Inserir um
novo passo 15 — "Parar e pedir aprovação humana explícita antes do commit, com
mensagem clara do que foi feito (o que mudou, prova de que `verify_cmd`
passou, quebras documentadas se houver)" — antes do passo de commit. Commit
vira passo 16 (só após aprovação recebida) e "deixar a working tree limpa"
vira passo 17. É mudança de texto/instrução do lifecycle (mesma natureza dos
16 passos já existentes, todos prosa que a sessão segue), não um mecanismo
técnico novo.

Adicional (melhoria de processo identificada durante esta própria sessão):
a skill `skills/plan/SKILL.md` (Passo 5 — Gate de aprovação) não instrui
explicitamente a apresentar o caminho de `spec.md`/`Plans.md` antes de pedir
aprovação — o usuário teve que perguntar "onde está o Plans.md" na sessão
anterior. Adicionar instrução explícita no Passo 5 para sempre mostrar o
caminho RELATIVO (não absoluto) dos dois arquivos como link markdown (ex.:
`.harness/work/<slug>/spec.md`) junto com o pedido de aprovação — relativo
porque é clicável no client, absoluto não é.

## Critérios de aceitação
- `pytest tests/test_lifecycle.py -q` passa, incluindo teste novo que confirma
  a presença do gate de aprovação humana no passo 15 (bloco fino e detalhe).
- `pytest tests/e2e/test_fase2_outcomes.py -q -k outcome6` passa, com o
  outcome 6 verificando 17 passos (não mais 16) e citando o gate de aprovação.
- `grep -q "caminho relativo" skills/plan/SKILL.md` passa — Passo 5 da skill
  passa a instruir explicitamente mostrar o caminho relativo (link
  markdown clicável) do contrato antes do pedido de aprovação.
- `pytest tests -q` passa (suíte completa, sem regressão em nenhum outro
  teste do plugin).

## Não-objetivos
- Não criar hook técnico (`PreToolUse` ou outro) que bloqueie `Bash(git
  commit*)` até uma aprovação registrada em algum estado/flag — o gate fica
  só como instrução textual do lifecycle, igual aos outros 16 passos hoje.
  Confirmado com o usuário: enforcement automático é escopo maior e fora
  desta demanda.
- Não alterar `boundary_guard.py`, `compiler.py`, `compile-contract` nem
  `compile-session` — nenhuma lógica de compilação de permissions/hooks muda.
- Não editar manualmente `tests/e2e/evidence/fase2-outcomes-verification.md`
  — esse arquivo é regravado automaticamente pela própria suíte e2e ao
  rodar (merge não-destrutivo por outcome); qualquer diferença nele é
  resultado de rodar o teste do outcome 6, não edição direta.
- Não alterar `docs/project/ROADMAP-fase2.backlog.md` nem outros documentos
  de backlog histórico/congelado — só documentação corrente (guias/tutorial/
  roadmap vigente/skill) é atualizada para citar 17 passos.

## Unknowns
Nenhum. O único `unknown` do profile (`package_manager`) foi confirmado pelo
usuário como `pip`.
