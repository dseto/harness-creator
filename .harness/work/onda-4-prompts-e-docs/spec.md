---
slug: onda-4-prompts-e-docs
approved_by: Daniel Seto
approved_at: 2026-07-30T15:20:00Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd (pytest -k) sem causa óbvia"
  - "qualquer teste do escopo tocado que hoje passa virar vermelho por causa desta mudança"
  - "descoberta de que uma seção supostamente duplicada tem conteúdo unico (ex.: arquitetura vs. uso) — não apagar, e sim voltar ao humano"
---

# Spec: Onda 4 — "prompts e docs"

## Resumo executivo
As instruções (skills) e a documentação (docs/plugin) do harness-creator
repetem o mesmo texto em vários lugares — um trecho de configuração em 5
arquivos, a mesma história do kill-switch em 3 documentos — sem nenhum
ganho de clareza, só custo de manutenção (uma correção precisa lembrar de
todos os lugares) e de tokens (cada skill invocada carrega o texto
repetido). Esta onda também dá o primeiro passo de "usar o modelo certo
para cada trabalho": a skill de avaliação de demandas (`assess`) hoje
delega toda a tarefa — coleta mecânica de evidência E julgamento final —
para o mesmo modelo caro; a coleta pode rodar num modelo mais barato sem
perder qualidade, porque quem julga continua sendo o modelo forte.

## Escopo
Itens **7, 8 e 14** do
[docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md](../../docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md)
(seção 4, "Onda 4 — prompts e docs"):

1. **Item 7 (parcial — ver correção abaixo)**: o bloco de instrução sobre
   `PYTHONPATH`/`ModuleNotFoundError` está duplicado, quase palavra por
   palavra, em 5 `SKILL.md` (`plan`, `preflight`, `init`, `audit`, `team`).
   Cada um repete a mesma justificativa ("não vale checar antes, o comando
   real já falha com o mesmo sinal"). Reduz a 1 linha por skill + a
   justificativa completa 1 vez em `docs/plugin/GUIDE.md`.
2. **Item 8**: `skills/assess/SKILL.md` recomenda delegar os Passos 1–4
   (coleta das 4 fontes E julgamento das 4 dimensões E emissão do laudo) a
   um único subagente, sem indicar modelo — hoje isso roda no modelo da
   sessão principal (caro) mesmo para trabalho mecânico de grep/glob/git
   log. Explicita o roteamento: coleta (Passo 2) delega a um subagente
   **Haiku**; julgamento (Passo 3, D1–D4) e emissão do laudo (Passo 4)
   continuam no modelo forte, porque exigem avaliação, não só busca.
3. **Item 14 (parcial — ver correção abaixo)**: a "anedota" do kill-switch
   (guard ficou em no-op por 4 dias sem ninguém notar, `harness status` é a
   única fonte de verdade) é contada por inteiro em 3 documentos —
   `GUIDE.md` §11, `TUTORIAL.md` §B.7, `ARCHITECTURE.md` §9 — cada um com o
   mesmo aviso reescrito com palavras diferentes. Consolida numa fonte
   (`GUIDE.md` §11, já é o mais completo) e os outros dois passam a
   apontar para ela, preservando o que É próprio de cada um (o passo a
   passo do `TUTORIAL` continua ensinando os comandos; o raciocínio
   arquitetural do `ARCHITECTURE` sobre por que não há paradoxo de
   segurança continua intacto — só a anedota repetida sai).

## Correção em relação ao laudo original
- **Item 7**: o laudo lista também "gate REGRA DURA 2×", seções `## Regras`
  em 6 skills, e "assess declara read-only 4× no mesmo arquivo" como parte
  da mesma duplicação. Ao verificar antes de escrever o contrato: (a)
  "REGRA DURA" aparece em `plan`/`team`/`preflight`, mas cada ocorrência
  marca um gate de aprovação **diferente** (aprovar contrato vs. aprovar
  arquitetura de time vs. nunca aplicar fix sozinho) — é reforço de um
  padrão, não cópia do mesmo texto; (b) as 6 seções `## Regras` reafirmam
  as regras da PRÓPRIA skill, não repetem as de outra; (c) `assess` hoje
  só tem 2 menções a "read-only" (frontmatter + seção `## Regras`), não 4 —
  contagem do laudo já não bate com o estado atual do arquivo (pode ter
  mudado em onda anterior). Nenhum desses três é duplicação real de texto
  entre arquivos — mexer neles é reescrita de estilo com risco de tirar
  ênfase de um gate de segurança, fora do espírito "mecânico, baixo risco"
  das ondas anteriores. Mantido fora do escopo (ver Não-objetivos). Só o
  bloco `PYTHONPATH` (duplicação literal, palavra por palavra, em 5
  arquivos) entra nesta onda.
- **Item 14**: o laudo também cita "diagrama do ciclo em 2 versões já
  divergentes" e "tabela do preflight reescrita em 4 lugares" como parte do
  mesmo item. Ambos exigem decidir qual versão é a correta (o diagrama
  discorda entre si, então uma reescrita simples de delegação não resolve
  — resolve esconder a divergência) — isso é julgamento de conteúdo, não
  dedup mecânico, e fica fora desta onda. Só a anedota do kill-switch
  (texto idêntico em espírito, sem divergência de fato entre as 3 cópias)
  entra.

## Critérios de aceitação
- O bloco `PYTHONPATH` nos 5 `SKILL.md` vira 1 linha cada, e a
  justificativa completa aparece 1 única vez, em `docs/plugin/GUIDE.md`:
  `pytest tests/test_prompt_docs_dedup.py -k pythonpath -q`
- `skills/assess/SKILL.md` roteia a coleta (Passo 2) para um subagente
  Haiku e mantém o julgamento (Passo 3/4) no modelo forte, com a menção a
  "Haiku" presente na seção de delegação ("## Como executar") e ausente da
  seção de julgamento (Passo 3/4) — prova de que está associada à coleta,
  não ao julgamento: `pytest tests/test_prompt_docs_dedup.py -k assess_model -q`
- A anedota "quatro dias" do kill-switch aparece em exatamente 1 dos 3
  documentos (`GUIDE.md`), e `TUTORIAL.md`/`ARCHITECTURE.md` continuam
  citando o comando `harness disable`/`enable` e apontando para o
  `GUIDE.md` para o aviso completo:
  `pytest tests/test_prompt_docs_dedup.py -k killswitch -q`
- Suíte completa do escopo tocado não regride:
  `pytest tests/test_prompt_docs_dedup.py tests/test_docs_enforcement_claims.py -q`

## Não-objetivos
- Não tocar em "REGRA DURA" (2 ocorrências, gates distintos), nas 6 seções
  `## Regras`, nem nas 2 menções a "read-only" em `assess` — ver correção
  acima.
- Não tocar no diagrama do ciclo (`docs/plugin/ARCHITECTURE.md` vs. outro)
  nem na tabela do preflight (4 lugares) — divergência real que exige
  decisão de conteúdo, não dedup mecânico.
- Não mudar o formato do laudo do `assess` (`report-template.md`) nem as 4
  dimensões (D1–D4) — só onde cada uma roda, não o que avalia.
- Não criar um segundo subagente/handoff formal para o `assess` — a skill
  continua com uma recomendação de delegação (não regra dura), só mais
  específica sobre modelo.
- Não tocar em nenhum outro item do laudo (1, 2, 3–6, 9–13, 15–17) — todos
  já cobertos pelas Ondas 1–3 ou fora desta onda.
- Não afrouxar o floor de segurança, não tocar em `boundary_guard.py`.

## Unknowns
(nenhum — profile já confirmado nas ondas anteriores; sem pergunta nova ao
usuário nesta onda)
