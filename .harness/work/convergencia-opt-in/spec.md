---
slug: convergencia-opt-in
approved_by: Daniel Seto
approved_at: 2026-08-09T23:20:38Z
stop_conditions:
  - "2 tentativas de correção estrutural seguidas na MESMA falha, fora do retry transiente"
  - "qualquer regra nova fazer a métrica DECIDIR 'pronto' no lugar do verify_cmd (anti-Goodhart do §4.3) — parar e escalar"
---

# Spec: Sinal de convergência opt-in por tarefa (§4.3 do design)

## Resumo executivo
Hoje toda tarefa do contrato é binária: o `verify_cmd` passa ou não passa.
Mas existem demandas onde "meio pronto" é mensurável e uma iteração pode
**piorar** o artefato — converter um HTML fielmente para PowerPoint até a
similaridade visual passar de 85%, reduzir a contagem de erros de lint de um
legado, subir o número de testes passando numa migração grande. Nesses casos,
sem medir a trajetória, o loop não sabe se está se aproximando ou se
afastando do objetivo, e pode empilhar trabalho em cima de uma versão pior
que uma anterior.

Este contrato dá à tarefa um campo **opcional** de métrica: um comando que
imprime um número. Quando presente, o harness registra o valor a cada
verificação, guarda qual foi o melhor estado até agora, e o disjuntor ganha
dois vereditos novos: **platô** (3 medições sem melhora — inclui oscilação)
manda trocar de abordagem, e **piora** (2 medições seguidas piores que o
melhor) manda voltar ao melhor estado registrado em vez de continuar por
cima. Tarefa sem o campo não muda em nada. A métrica **guia** o loop; quem
decide "pronto" continua sendo só o `verify_cmd`.

## Escopo
Implementa o §4.3 do
[design de loop engineering](../../../docs/reference/loop-engineering-design.md)
como slot opt-in por tarefa, com os contadores K=3 (platô) e J=2 (piora) do
próprio design — não os detectores estatísticos (essa fronteira fica em
Não-objetivos).

**Contrato (`contract.py`).** A tarefa do `Plans.md` ganha dois bullets
opcionais: `metric` (comando que imprime um único número em stdout) e
`target` (expressão de comparação, ex.: `>= 0.85`). Presentes, vão para o
`feature_list.json` como `metric_cmd`/`metric_target`; ausentes, o JSON sai
idêntico ao de hoje. `target` sem `metric` é erro de compilação do contrato.

**Superfície de permissão (`session_permissions.py`).** `_derive_allow_list`
ganha o mesmo tratamento que já dá a `verify_cmd` e aos `extras` do profile
(lint/typecheck/build): todo `metric_cmd` distinto do contrato vira
`Bash(<metric_cmd>)` + `Bash(<metric_cmd>:*)` no `allow` compilado. Sem isso,
o agente que rodar `metric_cmd` manualmente (fora do `harness verify`) toma
prompt de permissão em vez de passar direto — a mesma fadiga silenciosa do
Item 8 do backlog dogfood, já corrigida uma vez para `verify_cmd`; não
recriar o mesmo bug para `metric_cmd`. Passa pelo mesmo filtro final do
runtime floor que toda entrada do `allow` já passa.

**Registro da trajetória (novo módulo `convergence.py`).** Quando a tarefa
tem `metric_cmd`, o `harness verify` roda o comando de métrica após o
`verify_cmd` (passe ou falhe — a trajetória interessa principalmente nos
vermelhos) e grava em `.harness/attempts/<contrato>/<id>-metric.jsonl`:
valor, timestamp, `git rev-parse HEAD` e flag de working tree suja. Saída do
comando que não parseia como número vira falha de ambiente (mesma família do
§8.3), nunca valor zero. O melhor valor até agora e o estado em que ocorreu
ficam deriváveis do próprio rastro (argmin/argmax conforme a direção do
`target`), sem arquivo de estado paralelo.

**Disjuntor (`budget.py`).** `harness budget --feature <id>`, quando há
trajetória registrada, aplica na ordem — piora antes de platô:

- **`stop_worsening`** — as últimas 2 medições são ambas piores que o
  melhor valor já registrado. O veredito nomeia o melhor estado (valor,
  timestamp, commit) e a instrução é retomar dali, não continuar por cima.
  O harness **não** faz checkout nem revert — nomeia o alvo; quem age é o
  agente (ou o humano), como em todo veredito de parada. Nome deliberadamente
  distinto de "regressão" — `regression.py` já usa esse termo para o raio de
  explosão entre tarefas (arquivo compartilhado que derruba outra feature já
  verde), mecanismo diferente; reaproveitar o nome confundiria grep e leitura.
- **`stop_plateau`** — as últimas 3 medições não superam o melhor valor.
  Oscilação (alterna melhor/pior sem acumular) cai aqui por construção: a
  janela olha "superou o melhor?", não "piorou em sequência". Instrução:
  trocar de abordagem ou escalar.
- `target` atingido aparece como campo informativo no JSON (`target_met:
  true`), mas NÃO muda o veredito nem marca a tarefa: `passes` continua
  vindo só de `harness verify`. É o anti-Goodhart do §4.3 como invariante.

Os vereditos existentes (`stop_same_failure`, `stop_iterations`,
`stop_transient_exhausted`) têm precedência sobre os novos (`stop_worsening`,
`stop_plateau`): falha repetida é sinal mais forte que trajetória.

**Escalada (`escalation.py`).** Quando a tarefa tem métrica, o bloco de
escalada das seis partes ganha, na parte do estado, a linha da trajetória:
série recente, melhor valor e onde ele ocorreu — o humano vê a curva, não só
o último erro.

**Lifecycle.** Passos 9 e 10 documentam o campo opcional, os dois vereditos
novos e a regra de ouro (métrica guia, `verify_cmd` decide).

## Critérios de aceitação
- Tarefa com bullets `metric`/`target` compila para
  `metric_cmd`/`metric_target` no `feature_list.json`; sem os bullets o JSON
  é byte-idêntico ao atual; `target` sem `metric` é `ContractError` nomeando
  a tarefa — `pytest tests/test_contract.py -q`
- `metric_cmd` de cada feature vira `Bash(<metric_cmd>)` +
  `Bash(<metric_cmd>:*)` no `allow` compilado, mesmo padrão de `verify_cmd`;
  contrato sem `metric_cmd` não muda o `allow` atual —
  `pytest tests/test_session_permissions.py -q`
- Com `metric_cmd`, cada `harness verify` acrescenta uma medição ao rastro
  (valor, timestamp, commit, flag de árvore suja); saída não-numérica é
  falha de ambiente, não valor; sem `metric_cmd`, nenhum arquivo de métrica
  é criado — `pytest tests/test_convergence.py -q`
- Duas medições seguidas piores que o melhor → veredito `stop_worsening`
  nomeando o melhor estado; três medições sem superar o melhor (incluindo
  série oscilante) → `stop_plateau`; `target` atingido seta `target_met`
  sem alterar veredito nem `passes` — `pytest tests/test_budget.py -q`
- Vereditos existentes prevalecem sobre os de trajetória quando ambos
  disparariam — `pytest tests/test_budget.py -q`
- Bloco de escalada de tarefa com métrica inclui a trajetória (série
  recente, melhor valor, onde ocorreu) — `pytest tests/test_escalation.py -q`
- Passos 9 e 10 do lifecycle documentam métrica opt-in, os dois vereditos e
  a regra "métrica guia, critério decide" — `pytest tests/test_lifecycle.py -q`

## Não-objetivos
- **Detectores estatísticos** (t-test de tendência, slope_log, variância —
  estilo LoopGain) ficam fora: exigem ≥6 iterações e são degrau acima na
  escada de maturidade (§11). Contadores K=3/J=2 cobrem os loops curtos que
  existem hoje; subir o degrau só com dor comprovada.
- **Revert automático**: o harness nunca executa `git checkout`/`revert` por
  conta própria. `stop_worsening` nomeia o melhor estado; agir é do agente
  sob as regras de sempre (ou do humano). Mesma fronteira de D-005: o
  mecanismo não fabrica nem desfaz estado que não produziu.
- **Métrica como critério de pronto**: `target_met` jamais vira `passes`.
  Similaridade 92% com `verify_cmd` vermelho é tarefa NÃO concluída.
- **Múltiplas métricas por tarefa** e agregação ponderada — uma métrica por
  tarefa; quem precisa compor, compõe dentro do próprio comando de métrica.
- **K e J configuráveis** no primeiro corte: constantes do design (3 e 2).
  Configurar antes da primeira demanda real usar é ajuste sem dado.

## Unknowns
(nenhum — o desenho vem inteiro do §4.3 do design aprovado; a validação
externa contra o LoopGain já foi feita e está registrada no próprio design.)
