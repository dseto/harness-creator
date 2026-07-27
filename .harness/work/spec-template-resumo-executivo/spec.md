---
slug: spec-template-resumo-executivo
approved_by: Daniel Seto
approved_at: 2026-07-23T21:30:00Z
stop_conditions:
  - "3 falhas consecutivas do comando de verificação"
---

# Spec: template de spec.md ganha seção "Resumo executivo" por padrão

## Resumo executivo

O template `spec.md` documentado em
`skills/plan/references/contract-templates.md` — o formato EXATO que a
skill `/harness-creator:plan` segue ao escrever contratos — pula direto do
frontmatter de aprovação pro `## Escopo` técnico, sem nenhuma seção em
linguagem simples pra quem não é técnico entender objetivo/resultado
esperado. Nas 3 últimas demandas implementadas nesta sessão (issues
#9/#11/#12), essa seção só existiu porque o usuário pediu manualmente toda
vez ("Resumo executivo... para um product owner com quase nenhum
background técnico"). Esta mudança coloca a seção no template, como
padrão, pra parar de depender de pedido explícito repetido.

## Escopo
Editar `skills/plan/references/contract-templates.md`: inserir uma nova
seção `## Resumo executivo` no template `spec.md` (bloco markdown dentro
do arquivo), posicionada logo após o título (`# Spec: <título da
demanda>`) e antes de `## Escopo`. Placeholder guiando o que entra ali:
objetivo em linguagem simples, o que muda do ponto de vista de quem usa
(não de quem implementa), e o resultado esperado — sem jargão técnico.

## Critérios de aceitação
- `## Resumo executivo` aparece no template `spec.md` documentado, antes
  de `## Escopo`.
  Prova: `python -c "text = open('skills/plan/references/contract-templates.md', encoding='utf-8').read(); assert '## Resumo executivo' in text; assert text.index('## Resumo executivo') < text.index('## Escopo')"`

## Não-objetivos
- Não altera `src/harness/contract.py` — `parse_spec` só lê o frontmatter
  YAML, nunca as seções do corpo do markdown; nenhum acoplamento de código
  com essa seção nova.
- Não altera o template `Plans.md` nem a granularidade de tarefas.
- Não retroage nos contratos `.harness/work/*` já existentes desta sessão.

## Unknowns
(nenhum)
