---
slug: onda-2-contexto-veridico
approved_by: Daniel Seto
approved_at: 2026-07-30T14:20:00Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd na mesma tarefa"
  - "qualquer verify_cmd exigir tocar arquivo fora do files[] declarado sem usar `harness task add-file`"
  - "qualquer mudança proposta alterar a semântica do kill-switch (killswitch.py) além de torná-lo visível — para e devolve ao humano"
---

# Spec: Onda 2 — contexto verídico (AGENTS.md, injeção de sessão, progresso, kill-switch visível)

## Resumo executivo
O contexto que todo agente recebe no início de uma sessão neste projeto tem
pedaços que não descrevem mais a realidade: metade do `AGENTS.md` descreve
uma arquitetura de sandbox/container que não existe no Windows, e o rastro
de progresso acumula anotações duplicadas ou de contratos antigos. Esta onda
corrige isso — o texto que o agente lê passa a ser 100% verdadeiro — e
resolve um segundo problema, independente mas urgente: quando o kill-switch
está desligado, ninguém percebe até rodar um comando manual, o que já causou
4 dias de proteção inativa sem ninguém notar (issue #52). Depois desta onda,
a primeira mensagem de qualquer sessão já avisa isso sozinha.

## Escopo
Quatro frentes, cada uma com arquivos e prova próprios:

1. **AGENTS.md (parte manual, prosa)** — remove afirmações que não são mais
   verdade: promessa de "contêiner isolado sem rede" (não existe no host
   Windows), ferramentas `read_file`/`write_file`/`run_terminal` (não são
   ferramentas nativas do Claude Code), `ContextManager` e pacotes
   `tools/verification/context/telemetry/routing/` (não existem em
   `src/harness/`, que hoje é módulos Python soltos + `governance/` e
   `teams/`). Reescreve para a realidade atual: hooks `PreToolUse`/
   `SessionStart` do Claude Code, `boundary_guard.py` como floor de
   segurança.
2. **AGENTS.md (bloco GERADO por `compiler.py`)** — hoje repete, em texto
   fixo (sem interpolar `harness.yaml`), os itens "escopo mínimo" e "sem
   segredos" que já vivem na parte manual — a mesma regra dita duas vezes
   no mesmo arquivo, por dois mecanismos diferentes. O bloco gerado passa a
   carregar só o que de fato deriva da config (TDD/política de aprovação,
   `test_command`, orçamento).
3. **Hook `SessionStart` — matcher e visibilidade do kill-switch** — hoje
   registrado com `matcher: "*"`, o que reinjeta o mesmo contexto a cada
   `compact` da sessão (não só no início) — restringe para
   `startup|resume|clear`. Separadamente (US-1 do
   `docs/project/USER-STORY-p0-friccao-ciclo-2026-07-30.md`): quando
   `.harness/harness.disabled` existir, o texto injetado passa a avisar
   isso de forma visível — desde quando e o comando pra reativar — em vez
   de ficar mudo até alguém rodar `harness status` de propósito.
4. **`.harness/progress.md` — nota automática sem duplicação nem lixo de
   contrato antigo** — `append_progress_note` grava uma linha nova a cada
   `harness verify` bem-sucedido, mesmo quando é a MESMA feature verificada
   de novo (ex.: depois de uma correção de evidência stale) — isso
   desperdiça o teto de 10 entradas com repetição. Separadamente,
   `install_templates` copia a seção "Última atualização" inteira ao trocar
   de contrato, sem checar se as entradas antigas ainda fazem sentido —
   uma nota que cita um caminho de evidência que não existe mais persiste
   como se fosse atual. Corrige as duas: dedupe por `feature_id` ao
   adicionar, e filtro por existência do arquivo de evidência citado ao
   carregar entradas antigas (na virada de contrato e no append).

## Correção em relação ao laudo original
O laudo (`docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md`, item
6) também afirmava que "`harness finish` encerra a demanda sem zerar o
bloco" de progresso automático. Ao verificar antes de escrever este
contrato ([finish.py:280](../../../src/harness/finish.py#L280)),
`sweep_disposables` já reescreve `.harness/progress.md` por completo via
`render_closed_progress` — que não tem bloco `harness:auto` nenhum no
template de demanda encerrada. Essa parte já está correta hoje; não entra
como tarefa. O problema real (dedupe + entrada órfã sobrevivendo a uma
TROCA de contrato, não a um fecho) é o que a Escopo item 4 acima cobre.

## Critérios de aceitação
- AGENTS.md (parte manual) não cita mais `ContextManager`, `read_file`,
  `write_file`, `run_terminal`, `sandbox`/`contêiner isolado`, nem os
  pacotes `tools/`, `verification/`, `context/`, `telemetry/`, `routing/`.
  Prova: `pytest tests/test_docs_enforcement_claims.py -q` (tabela
  `_FORBIDDEN_CLAIMS` ganha as entradas novas desta onda).
- Bloco gerado do `AGENTS.md` (entre `<!-- harness:begin -->` e
  `<!-- harness:end -->`) não repete mais os itens "escopo mínimo"/"sem
  segredos" em texto fixo — só conteúdo derivado do `harness.yaml`. Prova:
  `pytest tests/test_compiler.py -q`.
- Hook `SessionStart` registra `matcher: "startup|resume|clear"` em vez de
  `"*"`. Prova: `pytest tests/test_session_start.py -q`.
- Com `.harness/harness.disabled` presente, o `additionalContext` do
  `SessionStart` inclui, de forma legível (não só dentro de um campo JSON
  aninhado sem destaque), que o harness está desativado, `disabled_at`, e o
  comando `harness enable`. Sem o sentinel, a saída não muda em relação ao
  comportamento atual. Prova: `pytest tests/test_session_start.py -q`.
- `append_progress_note` não duplica uma entrada para o MESMO `feature_id`
  — reverificar a mesma feature atualiza/substitui a linha anterior dela em
  vez de somar outra. `install_templates`, ao trocar de contrato, só
  carrega para o novo `progress.md` as entradas da seção "Última
  atualização" cujo caminho de evidência citado ainda existe em disco.
  Prova: `pytest tests/test_templates.py -q`.

## Não-objetivos
- Não implementa nenhum item das Fases 5-7 do `docs/roadmap-autonomous.md`.
- Não altera a lógica do kill-switch (`killswitch.py`) nem o invariante de
  que o agente não pode se autorreativar — só lê o estado já exposto por
  `is_disabled`/`status` para exibi-lo.
- Não adiciona bloqueio novo — o kill-switch continua fail-open enquanto
  desativado; esta onda só torna o estado visível.
- Não muda o teto de 10 entradas do bloco automático do progresso (só
  dedupe/filtro do que entra nele).
- Não mexe no floor de segurança, nem em semântica de `deny` do
  `boundary_guard.py`.
- Não toca `guard_test_runner.py`/geração de hooks de teste (item já
  resolvido na Onda 1).

## Unknowns
(nenhum — profile já confirmado na Onda 1: Python, `pytest`, `ruff check .`,
sem novos símbolos fora de `src/harness/`+`tests/` nesta demanda)
