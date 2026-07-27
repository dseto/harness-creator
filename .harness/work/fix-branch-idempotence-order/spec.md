---
slug: fix-branch-idempotence-order
approved_by: Daniel Seto
approved_at: 2026-07-23T14:20:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste (pytest tests/test_branching.py)"
---

# Spec: ensure_contract_branch checa branch-ja-correta antes de dirty-tree

## Escopo
`ensure_contract_branch` (src/harness/branching.py:46) checa working-tree
suja (linhas 78-86) antes de verificar se HEAD ja esta na branch
`contract/<slug>` correta (linhas 90-92). Isso viola a garantia de
idempotencia documentada no docstring da funcao ("ja na branch -> no-op")
e quebra recompilacao mid-task (`harness compile-session`) quando existem
mudancas tracked nao commitadas mas o repo ja esta no branch certo. Fix:
mover o check de "HEAD ja e a branch alvo -> retorna cedo" para ANTES do
guard de dirty-tree; o guard de dirty-tree so se aplica quando de fato vai
criar ou trocar de branch (fluxo `switch`/`switch -c`).

## Criterios de aceitacao
- Com HEAD ja em `contract/<slug>` e tracked modificado/staged (dirty),
  `ensure_contract_branch` retorna a branch sem levantar `BranchingError`
  (no-op real). Prova: `pytest tests/test_branching.py -q`
- Comportamento existente preservado: branch inexistente ou branch
  diferente da alvo + dirty-tree ainda levanta `BranchingError` antes de
  criar/trocar branch. Prova: `pytest tests/test_branching.py -q`
- Suite completa do projeto permanece verde. Prova: `pytest -q`

## Nao-objetivos
- Nao muda o comportamento de dirty-tree guard quando branch precisa ser
  criada ou trocada (continua bloqueando).
- Nao muda a definicao de "dirty" (tracked-only, `-uno`) documentada no
  modulo.

## Unknowns
(nenhum)
