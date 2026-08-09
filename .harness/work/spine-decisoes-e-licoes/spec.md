---
slug: spine-decisoes-e-licoes
approved_by: Daniel Seto
approved_at: 2026-08-09T12:52:16Z
stop_conditions:
  - type: consecutive_verify_failures
    n: 3
  - type: same_failure_signature
    n: 2
  - "Se a injeção das decisões na abertura da sessão começar a competir por espaço com o aviso de reconciliação e o resumo de progresso: parar e replanejar o corte. Contexto de abertura que vira parede de texto é lido na diagonal, e aí os três registros perdem junto."
  - "Se aparecer qualquer necessidade de o agente EDITAR uma decisão antiga (e não acrescentar uma nova que a supersede): parar. Append-only é a garantia inteira deste contrato; um arquivo que pode ser reescrito não prova que a razão registrada é a razão original."
---

# Spec: Os outros dois registros da spine — decisões e lições

## Resumo executivo

O harness registra o que já foi feito, mas não **por que** foi decidido assim,
nem **o que atrapalhou** no caminho. O efeito prático: uma sessão dali a duas
semanas "descobre" e tenta de novo a abordagem que já tinha sido descartada por
bom motivo — porque o motivo nunca foi escrito em lugar nenhum que ela leia. E a
fricção que apareceu ontem (regra que barrou demais, mensagem confusa, erro
repetido) se perde, então o harness não melhora com o uso.

Passam a existir dois arquivos, escritos por comando e nunca reescritos: um de
decisões com o porquê, outro de fricções observadas. As decisões recentes chegam
sozinhas no começo da próxima sessão. As lições ficam esperando o humano no fecho
da demanda — quem decide o que vira melhoria é ele, não o agente.

## Escopo

Incremento 4 do [design de loop engineering](docs/reference/loop-engineering-design.md),
§5.2 e §5.3. A spine do design tem TRÊS registros com ciclos de vida diferentes;
o harness mecaniza só o primeiro (`.harness/progress.md`, vida = a demanda).
Faltam os dois cuja vida é o PROJETO:

- `.harness/decisions.md` — `## D-00N — <título> (data)` + `Decisão:` +
  `Porquê:`. Gatilho: descartar uma alternativa por razão não óbvia, ou tomar
  decisão que restringe iterações futuras.
- `.harness/lessons.md` — `- [ ] <fricção> → <melhoria candidata>`. Gatilho:
  a fricção acontecendo, uma linha, sem interromper o trabalho.

Quatro decisões de desenho que o escopo carrega:

1. **Comando, não edição à mão.** O `boundary_guard` já barra escrita em
   `.harness/**` fora de `work/` e `scratch/` — plano de controle não se
   auto-amplia. Então não existe a opção "o agente edita o markdown": ou há
   verbo (`harness decide`, `harness lesson`), ou os arquivos não são
   escritos. O verbo também é quem numera e datar sem colisão, que é
   justamente o que se erra escrevendo à mão.
2. **Append-only, sem exceção.** Decisão registrada não é editada nem apagada;
   mudou de ideia, registra-se outra que a supersede. Um arquivo reescrevível
   não prova que a razão registrada é a razão original — e a única coisa que
   este registro tem a oferecer é essa prova.
3. **As decisões chegam sozinhas na abertura.** O `SessionStart` injeta as mais
   recentes, do mesmo jeito que já injeta o aviso de reconciliação. Depender de
   o agente lembrar de ler é o defeito que os incrementos 1, 2 e 3 corrigiram
   três vezes.
4. **O agente anota a lição; o humano compila.** O loop NUNCA aplica lição
   sozinho. Auto-modificação do harness pelo próprio agente é a camada mais
   perigosa do design e não vale o risco — por isso as lições aparecem no fecho
   da demanda como lista para o humano, e nada mais acontece com elas.

## Critérios de aceitação

- Uma decisão registrada ganha id sequencial e data sem colidir com as
  anteriores, e nenhuma escrita nova altera uma linha já gravada:
  `pytest tests/test_spine.py -q`
- `harness decide` e `harness lesson` funcionam por linha de comando e não são
  negados pelo próprio hook de proteção:
  `pytest tests/test_cli.py -q`
- Os dois arquivos nascem com a sessão compilada, com o esqueleto certo, e
  recompilar nunca apaga o que já foi registrado:
  `pytest tests/test_templates.py -q`
- A sessão nova começa sabendo das decisões recentes, sem precisar procurá-las, e
  nunca perde o contexto por causa dessa leitura:
  `pytest tests/test_session_start.py -q`
- O fecho da demanda entrega ao humano a lista de lições em aberto:
  `pytest tests/test_cli.py -q`
- O ciclo documentado diz QUANDO registrar decisão e QUANDO registrar lição, e a
  documentação do projeto descreve os três registros:
  `pytest tests/test_lifecycle.py -q`

## Não-objetivos

- **Não é ADR com template de 12 campos.** Três linhas por decisão bastam; o
  design diz isso explicitamente.
- **O agente não aplica lição nenhuma.** Não fecha `- [ ]`, não edita o harness
  a partir do que anotou, não abre issue. Anota; o humano compila.
- **Não injeta lições na abertura da sessão.** O design é explícito: `lessons`
  não bloqueia retomada. Elas são para o humano, em cadência dele.
- **Não muda `progress.md`.** Ele é o terceiro registro, já existe, e tem outro
  ciclo de vida (nasce de template, é reescrito a cada demanda).
- **Não bloqueia nada.** Nem sessão, nem fecho, nem commit. Ausência de decisão
  registrada não é bloqueador — não há como uma máquina julgar se faltou
  registrar uma razão.
- **Não deduz decisão** a partir de diff, commit ou conversa.

## Unknowns

- Nenhum. O `harness analyze` deste repositório devolveu `unknowns: []`
  (`test_command: pytest`, evidência `pyproject.toml`).
