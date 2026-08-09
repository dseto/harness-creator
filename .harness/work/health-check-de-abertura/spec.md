---
slug: health-check-de-abertura
approved_by: Daniel Seto
approved_at: 2026-08-09T16:57:49Z
stop_conditions:
  - type: consecutive_verify_failures
    n: 3
  - type: same_failure_signature
    n: 2
  - "Se o health check precisar EXECUTAR o `verify_cmd` para dar veredito: parar. Rodar a suíte na abertura é o preço que fez ninguém rodar o `init.ps1`, e um check que custa uma suíte inteira volta a ser opcional na prática — que é o defeito que esta demanda existe para corrigir."
  - "Se algum check quiser CORRIGIR o que encontrou (instalar dependência, recompilar hook, reativar o kill-switch): parar. §8.3 é explícito — falha de infraestrutura nunca tem healing automático; o loop consertar a própria jaula é o comportamento que não se quer premiar."
---

# Spec: Health check de abertura

## Resumo executivo

Hoje a sessão abre sabendo o que foi feito antes, mas não sabe se as
ferramentas de que ela vai precisar respondem. O diagnóstico existe — o
`harness doctor` sabe achar hook morto e versão divergente, o `harness status`
sabe dizer se o harness está desligado —, só que nenhum dos dois fala sozinho:
alguém precisa lembrar de perguntar. E o modo de falha desta classe é
justamente o silêncio, então ninguém pergunta.

Depois desta demanda a sessão abre com um veredito de ambiente. Quando algo
que a demanda precisa não responde, isso aparece antes de a primeira fatia ser
escolhida — não no meio do loop, disfarçado de teste vermelho.

## Escopo

Fecha o **§7.2** (health check na abertura, único passo do protocolo de
retomada ainda sem mecanismo) e a **mitigação preventiva do §8.3** do
[design de loop engineering](docs/reference/loop-engineering-design.md).

O §8.3 é a falha mais perigosa do design pela razão que ele declara: **não
gera feedback no loop — gera silêncio.** O agente continua "funcionando" sem as
garantias que acha que tem. Já aconteceu neste repositório: o guard ficou em
no-op por quatro dias, de 2026-07-24 a 07-28, sem sinal nenhum — quatro dias de
sessões que pareciam governadas e não eram (issue #52).

Três famílias, que o §8.3 nomeia junto e que hoje são diagnosticadas separado:

**1. Ferramenta indisponível.** Nada olha se o executável de cada `verify_cmd`
do contrato existe. Descobre-se no meio do loop, como falha estrutural: o
agente trata "pytest não instalado" como teste vermelho e gasta budget
tentando consertar código que está certo.

**2. Hook morto / governança desalinhada.** O `doctor` já detecta — hook com
interpretador irresolúvel (a tool call passa sem gate nenhum), settings
ausente, `.harness/` compilado com versão diferente da instalada. Só que ele é
sob demanda, e quem não desconfia não roda.

**3. Guard em no-op.** O kill-switch aparece hoje no `reconcile`, misturado às
divergências de estado declarado × real. É outra coisa: não é o registro que
diverge do mundo, é a proteção que não está lá.

O passo 2 do lifecycle manda rodar `.harness/init.ps1` — que instala
dependências e roda a suíte inteira. É caro demais para a abertura, e é por
isso que ninguém roda. O `harness health` não executa nada do contrato: ele
pergunta se responde.

Decisões de desenho que o escopo carrega:

- **`health` não substitui o `doctor`; consome as issues dele.** `doctor`
  continua sendo o laudo completo sob demanda. `health` é o veredito de
  abertura, e reusa `run_doctor().issues` em vez de reimplementar a regra —
  duas regras de saúde são duas regras que divergem, que é a lição que o
  incremento passado compilou.
- **Perguntar, não executar.** Para `<exe> <args>`, o check resolve o
  executável no PATH; para a forma `<exe> -m <módulo>`, ele também confirma que
  o módulo importa. É o que separa "instalado" de "responde" sem pagar o custo
  de rodar o comando.
- **Ambiente quebrado é parada, não conserto.** O laudo classifica como `infra`
  e diz para escalar, no formato obrigatório do §8. Nenhum check corrige o que
  encontra.

## Critérios de aceitação

- `harness health` diz quais ferramentas do contrato não respondem, sem
  executar nenhum `verify_cmd` — prova: `pytest tests/test_health.py -q`
- O mesmo laudo cobre as três famílias do §8.3 (ferramenta, governança,
  kill-switch) numa passada só, classificado como `infra` e com o próximo
  passo declarado — prova: `pytest tests/test_health.py -q`
- A abertura da sessão traz o veredito sozinha, antes da reconciliação, sem
  ninguém precisar lembrar de rodar — prova:
  `pytest tests/test_session_start.py -q`

## Não-objetivos

- **Instalar, recompilar ou reativar qualquer coisa.** Ver stop condition: o
  §8.3 proíbe healing automático de infraestrutura.
- **Substituir o `harness doctor`.** Ele continua como laudo completo sob
  demanda, e vira a fonte da família de governança.
- **Substituir o `.harness/init.sh`/`init.ps1`.** Instalar dependências
  continua sendo trabalho dele; `health` só constata que faltou.
- **§4.3 (sinal de convergência) e §8.1 (falha transiente).** Ficam para
  incrementos próprios.
- **Rodar `verify_cmd`.** Ver stop condition.

## Unknowns

- (nenhum — `harness analyze` fechou o profile sem `unknowns[]`)
