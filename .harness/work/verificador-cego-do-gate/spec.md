---
slug: verificador-cego-do-gate
approved_by: Daniel Seto
approved_at: 2026-08-09T13:51:36Z
stop_conditions:
  - type: consecutive_verify_failures
    n: 3
  - type: same_failure_signature
    n: 2
  - "Se o pacote cego começar a precisar de algo do `spec.md` para ser julgável: parar. Significa que o `desc` das tarefas não é critério de aceitação de verdade, e o conserto é no contrato — nunca abrir exceção no pacote para deixar passar o racional de quem implementou."
  - "Se aparecer a necessidade de o próprio verificador CONSERTAR o que ele reprovou: parar. Fundir os dois papéis economiza uma chamada e custa a independência inteira, que é a única coisa que este incremento entrega."
---

# Spec: O gate de entrega ganha um olho que não implementou

## Resumo executivo

Hoje quem escreve o código é quem declara que o código está pronto. O harness
confere que o teste passou e que a prova é fresca, mas ninguém, em nenhum
momento, olha a entrega com a cabeça limpa — o primeiro olhar independente é o
do humano no Pull Request, quando o trabalho já está inteiro e mudar sai caro.

Passa a existir um passo antes do commit: o harness monta, por comando, um
pacote com o que a demanda prometia entregar e onde ficou o resultado — e
deliberadamente SEM o raciocínio de quem implementou. Um verificador que não
participou lê esse pacote, julga, e devolve um veredito com evidência. O fecho
da demanda passa a exigir esse veredito, fresco: código que mudou depois do
julgamento derruba o veredito e pede outro.

## Escopo

Incremento 5 do [design de loop engineering](docs/reference/loop-engineering-design.md),
**§6 camada 3** + **§9.1 (isolamento de viés)**.

A escada de verificação do §6 tem três camadas. Duas já estão mecanizadas:

| Camada | Quando | Estado no harness |
|---|---|---|
| 1. Sinal rápido | toda iteração | `pytest -k` do escopo — prosa do lifecycle |
| 2. Prova da fatia | ao declarar a fatia pronta | `harness verify` + re-prova incremental (incremento 3) |
| 3. Review profundo | uma vez, antes da entrega | **não existe** |

A camada 3 é a única do design chamada de obrigatória em §9.1: _"O mínimo
obrigatório deste design é UM ponto de independência: o verificador da camada 3"_.
Este contrato constrói exatamente esse ponto, e nada além dele.

Cinco decisões de desenho que o escopo carrega:

1. **O pacote é montado por código, nunca escrito à mão pelo implementador.**
   É este o invariante que dá pra mecanizar. O §9.1 é explícito: _"se o prompt
   do verificador contém a justificativa do implementador, a avaliação já
   nasceu contaminada"_ — e um prompt redigido por quem acabou de implementar
   vaza a justificativa por construção, sem má-fé nenhuma. O pacote sai do
   `feature_list.json`, que já é a projeção limpa do contrato: `desc` (o que
   foi prometido), `files[]` (onde olhar) e `verify_cmd` (a prova).

2. **O que fica FORA é a entrega deste contrato.** Não entram no pacote:
   `spec.md` (carrega as decisões de desenho — o racional do gerador),
   `progress.md` (carrega o histórico de tentativas: saber o que já falhou
   induz o julgamento), `decisions.md`, `lessons.md` e as mensagens de commit.
   O pacote nomeia essa lista para o verificador em texto, porque ele é um
   agente com acesso ao repositório — não dá pra tirar os arquivos do disco.

3. **O veredito prende o hash do estado julgado.** Mesma mecânica da evidência
   de camada 2: veredito gravado com o `files_hash` dos arquivos do contrato.
   Código mudou depois do julgamento → veredito velho, e o fecho cobra outro.
   Sem isso, um "aprovado" de vinte commits atrás fecha a demanda.

4. **Sem dente no `finish`, é template que ninguém preenche.** O §11 lista
   "gates que o humano aprova sem olhar" e "registros que ninguém lê" como
   sinais de over-engineering. O veredito só vale porque `harness finish`
   bloqueia sem ele.

5. **UM verificador, não um painel.** O §9.1 fecha mandando começar
   single-agent com verificador cego no gate e crescer só com dor comprovada.
   Lentes múltiplas (correção / segurança / aderência) ficam fora.

**Limite declarado, e não escondido:** o harness não consegue provar que o
subagente recebeu SÓ o pacote. O que ele garante é que o pacote existe em
disco, foi derivado por código a partir do contrato, e que o veredito está
preso ao estado que julgou. A disciplina do despacho (mandar o arquivo, não
resumir a conversa) é prosa do lifecycle — mecanismo onde dá, prosa onde não
dá, como no resto do projeto.

## Critérios de aceitação

- O harness monta o pacote cego a partir do contrato, com `desc`, `files[]` e
  `verify_cmd` de cada tarefa, e com a lista explícita do que o verificador não
  deve abrir; e o pacote NUNCA contém texto vindo de `spec.md`, `progress.md`,
  `decisions.md` ou `lessons.md` — prova: `pytest tests/test_blind.py -q`
- O veredito é gravado com o hash do estado julgado, veredito novo não apaga o
  anterior, e um veredito cujo hash não bate mais com os arquivos é reportado
  como velho — prova: `pytest tests/test_blind.py -q`
- Montar o pacote e registrar o veredito são comandos de uma linha, que o
  próprio hook de proteção não nega — prova:
  `pytest tests/test_cli.py tests/test_boundary_guard.py -q`
- `harness finish` não fecha demanda sem veredito, com veredito velho ou com
  veredito reprovado, e cada caso diz ao humano o que fazer — prova:
  `pytest tests/test_finish.py -q`
- O ciclo diz quando despachar o verificador, o que mandar e o que não mandar,
  e a documentação do projeto descreve as três camadas de verificação — prova:
  `pytest tests/test_lifecycle.py -q`

## Não-objetivos

- **Painel de verificadores com lentes múltiplas.** §9.1 manda começar com um
  e crescer com dor comprovada. Não há dor comprovada.
- **Despachar o subagente por conta do harness.** O harness monta o pacote e
  registra o veredito; quem despacha é o loop, pela prosa do lifecycle.
  Orquestração de subagente dentro do CLI é outra camada, e não é esta.
- **Encostar em `review.py`.** Aquilo é o state machine por-feature do padrão
  Produtor-Revisor (Fase 4, opt-in de time), com iteração e teto de
  re-submissão. Camada 3 é por DEMANDA, uma passada, no gate. Granularidades e
  ciclos de vida diferentes — juntar os dois faria um herdar as regras do
  outro.
- **Verificador que conserta.** §9.1: quem verificou devolve veredito ao loop,
  que decide. Reprovar não abre permissão de escrita para ninguém.
- **Recarimbar a evidência de camada 2** (a fricção anotada no incremento 4).
  Continua em `lessons.md`, esperando o humano.

## Unknowns

- (nenhum — `harness analyze` fechou o profile sem `unknowns[]`)
