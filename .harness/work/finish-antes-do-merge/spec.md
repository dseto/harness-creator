---
slug: finish-antes-do-merge
approved_by: Daniel Seto
approved_at: 2026-07-30T16:10:00Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd (pytest -k) sem causa óbvia"
  - "qualquer teste do escopo tocado que hoje passa virar vermelho por causa desta mudança"
---

# Spec: `harness finish` roda antes do PR, não depois do merge

## Resumo executivo
Hoje, depois que um PR de contrato é mesclado, é preciso rodar `harness
finish` de novo em cima do `main` — e isso sempre deixa uma sobra
(`.harness/progress.md` reescrito, evidência re-carimbada) que precisa de
um commit **direto na `main`**, branch onde o agente nunca pode commitar.
O humano acaba tendo que rodar 2-3 comandos de git manualmente toda vez
que uma demanda termina, só para fechar o contrato. Esta mudança move o
`harness finish` pra rodar **antes** do commit final, ainda na branch do
contrato — a sobra entra no mesmo commit/PR que já vai ser revisado e
mesclado, e o pós-merge não deixa mais nada pendente.

## Escopo
Nenhum código de `harness finish`/`verify` muda — o comando já não toca
git (confirmado em [docs/plugin/GUIDE.md § 10](../../docs/plugin/GUIDE.md)).
O que falta é a **instrução de quando rodá-lo**, que hoje não existe em
lugar nenhum: `skills/plan/SKILL.md` termina no Passo 8 (teste manual de
UI) e nunca menciona `harness finish`; a prática de "rodar depois do
merge" nasceu de convenção informal entre sessões, não de documentação —
por isso cada demanda tropeça na mesma fricção de novo.

1. `skills/plan/SKILL.md` ganha um **Passo 9** explícito: depois que todas
   as tarefas passarem (`harness supervise` devolve `next: null`) e depois
   do Passo 8 (se aplicável), rodar `harness finish --dir <alvo>` **na
   própria branch do contrato**, ANTES de pedir a aprovação humana do
   commit final. Se `finish` reportar `blockers` (ex.: `evidence_stale`),
   resolver ali mesmo (`harness verify <T-ID>` de novo) e rodar `finish`
   outra vez — só então pedir aprovação do commit, já incluindo o
   `progress.md` reescrito no diff revisado.
2. `docs/plugin/GUIDE.md` § 10 ("Encerrar a demanda") ganha uma frase
   deixando explícita a ordem recomendada (na branch do contrato, antes do
   PR) — hoje o texto descreve o que o comando FAZ mas não diz QUANDO
   rodá-lo em relação a push/PR/merge.

## Critérios de aceitação
- `skills/plan/SKILL.md` tem um passo depois do Passo 8 que menciona
  `harness finish` e instrui rodá-lo antes do commit/push/PR (não depois
  do merge): `pytest tests/test_finish_lifecycle_docs.py -k plan_skill -q`
- `docs/plugin/GUIDE.md` § 10 deixa explícita a ordem recomendada (branch
  do contrato, antes do PR): `pytest tests/test_finish_lifecycle_docs.py -k guide_secao_10 -q`
- Suíte completa do escopo tocado não regride:
  `pytest tests/test_finish_lifecycle_docs.py tests/test_docs_enforcement_claims.py -q`

## Não-objetivos
- Não mudar `src/harness/finish.py`/`verify.py` — o comando já não toca
  git e já é seguro rodar em qualquer branch; só falta a instrução de
  quando usá-lo.
- Não resolver a causa raiz do `evidence_stale` por normalização de EOL
  (CRLF↔LF no `git add`/`.gitattributes`) — é um problema separado, já
  mitigado por `.gitattributes` e contornável com um `harness verify`
  extra; fica fora desta demanda (mecânica de docs, não de hashing).
- Não tocar em `AGENTS.md`/`.harness/LIFECYCLE.md` — o lifecycle de 17
  passos ali é por TAREFA (`T-XX`), não por contrato; `harness finish` é
  ação de fim de CONTRATO (pode abranger várias tarefas), e não há
  contradição a corrigir nesses dois arquivos.
- Não afrouxar o floor de segurança nem tocar em `boundary_guard.py`.

## Unknowns
(nenhum)
