---
name: team
description: Desenha e gera, para o projeto-alvo, um time de agentes com revisão de qualidade independente embutida — análise de domínio -> proposta de padrão com justificativa -> aprovação da arquitetura do time (único toque humano da Fase 4) -> geração dos artefatos -> validação (harness audit-team).
when_to_use: Quando o usuário quer montar/criar um time de agentes para o projeto, pede "desenhar arquitetura de time", "configurar produtor-revisor", "gerar agentes e skills do time", ou é redirecionado aqui vindo de audit-team com findings sobre o time ainda não configurado. Roda UMA VEZ por projeto (setup do time) — diferente de /harness-creator:plan, que roda por demanda.
argument-hint: "[descrição do domínio/demanda em linguagem natural]"
disable-model-invocation: false
---

# Desenhar time de agentes -> arquitetura aprovável

Você vai desenhar, para o projeto-alvo, um time de agentes com revisão de
qualidade independente embutida — o padrão Produtor-Revisor (ou outro do
catálogo, quando fizer mais sentido para o domínio) — seguido do gate único
de aprovação humana da arquitetura e da geração dos artefatos.

## Pré-requisito (só se os comandos abaixo falharem)

Não rode uma checagem de import à parte. Se `harness.cli` der
`ModuleNotFoundError`, ISSO que indica falta de `PYTHONPATH`; só então rode
com `$env:PYTHONPATH = "${CLAUDE_PLUGIN_ROOT}\src"` (PowerShell) e repita o
comando.

## Passo 1 — Desenhar a arquitetura (dry-run)

```
python -m harness.cli team design --dir <alvo> --description "<descrição do domínio/demanda em linguagem natural>"
```

Isso não escreve nada em disco — só analisa o domínio e recomenda um padrão.
A saída JSON traz `pattern`, `justification` e `roles`.

## Passo 2 — Apresentar a recomendação

Mostre ao usuário, numa única síntese curta:

- **Padrão recomendado** (`pattern`) e a **justificativa** (`justification`).
- **Papéis** do time (`roles`).

Se o usuário **discordar** da recomendação, repita o Passo 1 citando o nome
do padrão desejado — e leve esse nome diretamente para o `--pattern` do
Passo 4 (o `team generate` aceita `--pattern` explícito, independente do que
`team design` recomendou).

## Passo 3 — Gate de aprovação da arquitetura (REGRA DURA)

Apresente ao usuário, de forma explícita:

- o padrão escolhido;
- os papéis do time;
- o modo de execução (`mode`, padrão `subagents` — a alternativa
  `agent-teams` usa a fila de mensagens nativa, recurso **experimental** do
  Claude Code).

Peça **aprovação EXPLÍCITA** da arquitetura do time antes de gerar qualquer
arquivo.

> **Este é o único gate desta skill, e é tão duro quanto o de
> `skills/plan/SKILL.md`: a skill NUNCA gera o time por inferência.** Só
> prossiga para o Passo 4 depois que o humano confirmar, em palavras claras,
> que aprova o padrão + papéis + modo apresentados. Se o usuário pedir
> ajustes, volte ao Passo 1/2 e repita este gate até a aprovação explícita.

## Passo 4 — Gerar os artefatos do time

Só depois da aprovação explícita (Passo 3), rode:

```
python -m harness.cli team generate --dir <alvo> --pattern <nome> [--mode subagents|agent-teams] [--max-review-iterations N]
```

- `--pattern`: nome do padrão aprovado (do catálogo `teams/patterns/`:
  `producer-reviewer`, `supervisor`, `pipeline`, `expert-pool`,
  `fan-out-fan-in`, `hierarchical-delegation`).
- `--mode`: default `subagents`; use `agent-teams` só se foi isso que o
  usuário aprovou no Passo 3.
- `--max-review-iterations`: default `3` — teto de iterações do ciclo
  produtor-revisor antes de escalar ao humano.

Mostre ao usuário os artefatos gerados (a saída JSON lista os paths reais):
agentes em `.claude/agents/`, skills em `.claude/skills/`, `AGENTS.md`
(`agents_md`), o detalhe do time (`team_detail`, ex. `.harness/TEAM.md`) e o
manifesto (`manifest`, ex. `.harness/team/manifest.json`).

## Passo 5 — Validar o time gerado

```
python -m harness.cli audit-team --dir <alvo>
```

Saída: JSON com `score` (0-100) e `findings` (severity/code/message/fix).
Exit code 1 = `score < 60` (algum finding crítico, ex. papel órfão, revisor
com ferramentas além do papel, drift no bloco gerenciado dos agentes).

- Apresente o score em destaque e a tabela de findings (severidade, problema,
  correção), traduzindo `message`/`fix` para o contexto do projeto — sem
  despejar JSON cru.
- Se houver finding **crítico**, explique ao usuário que é preciso corrigir
  antes de considerar o time operacional — não declare o setup concluído com
  um finding crítico em aberto.
- Sem findings: diga que o time está saudável e pare. Não invente melhoria.

## Passo 6 — Ciclo operacional (nenhuma ação nova do humano a partir daqui)

Explique ao usuário que, a partir deste ponto, o ciclo produtor-revisor roda
sem novo toque humano:

1. O **produtor** implementa a tarefa do `feature_list.json`.
2. `python -m harness.cli verify <feature_id> --dir <alvo>` roda o
   `verify_cmd` e grava evidência fresca — e já aciona automaticamente a
   submissão para revisão (`on_feature_verified`), sem precisar de
   `review ... submit` manual depois.
3. `python -m harness.cli supervise --dir <alvo>` (o supervisor) devolve a
   próxima feature pronta a trabalhar, respeitando dependências do
   `Plans.md`.
4. O **revisor** aprova ou rejeita a partir da evidência e do diff real:
   `python -m harness.cli review <feature_id> approve --dir <alvo> --note "..."`
   ou `python -m harness.cli review <feature_id> reject --dir <alvo> --note "..."`.
5. Rejeição devolve a tarefa ao produtor — o ciclo repete até aprovação **ou**
   até o `--max-review-iterations` estourar sem aprovação, caso em que escala
   ao humano via stop condition do contrato.

> Deixe explícito: estourar o limite de iterações **NUNCA** força aprovação
> automática — só escala ao humano.

## Regras

- Nunca gere o time (Passo 4) sem aprovação explícita da arquitetura no
  Passo 3 — nunca por inferência, nunca porque "parece óbvio que vai
  aprovar".
- Nunca invente um padrão fora do catálogo (`team design` só recomenda os 6
  padrões já existentes em `src/harness/teams/patterns/`).
- Esta skill roda **uma vez** por projeto (setup do time) — diferente de
  `/harness-creator:plan`, que roda por demanda a cada nova feature.
- Se `team generate` sair com erro (`TeamError`), mostre a mensagem ao
  usuário e volte ao Passo 1/2 — não tente contornar com artefatos escritos
  à mão.
- Depois de corrigir findings de `audit-team`, rode a auditoria de novo e
  mostre o score atualizado antes de declarar o time operacional.
