---
slug: falha-transiente-e-escalada
approved_by: Daniel Seto
approved_at: 2026-08-09T20:36:30Z
stop_conditions:
  - "2 tentativas de correção estrutural seguidas na MESMA falha, fora do retry transiente"
  - "qualquer regra nova entrar em conflito com D-007/D-008 (o health check pergunta, nunca executa) sem decisão explícita registrada"
---

# Spec: Falha transiente com retry próprio, e escalada em formato fixo

## Resumo executivo
Quando um `verify_cmd` falha por causa passageira — rede caiu, um timeout de
aplicação, uma conexão recusada — a sessão passa a tentar de novo sozinha, um
número pequeno de vezes, sem que isso conte como "tentativa de correção" nem
gaste o orçamento de correção de bug. Se o mesmo tipo de falha passageira
insistir mesmo depois das tentativas, a sessão para e avisa que o problema é
do ambiente, não do código. E toda vez que a sessão para para pedir ajuda, o
aviso ao humano vem sempre no mesmo formato — o que estava sendo tentado, o
que já foi tentado, o erro exato, por que parou, e o que fazer a seguir — em
vez de uma frase solta que muda a cada vez.

## Escopo
Fecha os dois itens pendentes da seção 8 do
[design de loop engineering](../../../docs/reference/loop-engineering-design.md):
§8.1 (falha transiente) e o formato obrigatório de escalada.

**§8.1 hoje não existe.** `harness.verify.run_verify` trata toda falha de
`verify_cmd` do mesmo jeito: grava a tentativa e devolve o controle. Uma
falha de rede (`Connection refused`, `Read timed out`) consome exatamente o
mesmo orçamento de tentativas que um teste vermelho de verdade — e pode
disparar a regra do padrão repetido (§8.2, "a mesma falha 3× = a abordagem
está errada") por um motivo que não tem nada a ver com abordagem.

O que muda: `verify_cmd` que falha com um sinal reconhecidamente transiente
(timeout de aplicação, erro de rede/conexão — não o timeout do PRÓPRIO
processo do `verify_cmd`, que fica fora do escopo, ver Não-objetivos) tenta
de novo sozinho, até 3 tentativas no total, com uma pausa curta entre elas.
Se uma das tentativas passar, nada fica registrado das que falharam antes —
elas não foram correção, foram repetição. Se a 3ª também falhar com sinal
transiente, ela é registrada (uma vez só) e classificada como falha de
ambiente — a mesma resposta do §8.3: parar, não tentar consertar por dentro
do código. Falha comum (teste vermelho, `AssertionError`, etc.) nunca entra
nesse caminho — vai direto para o registro de sempre, sem retry, sem mudança
de comportamento observável.

**O formato de escalada hoje é uma frase livre.** `harness budget` já devolve
um veredito de parada com uma razão em prosa, mas nada obriga o formato que a
§8 pede: fatia+critério, o que foi tentado, o último erro cru, a
classificação, o estado da spine, e a sugestão de próximo passo — nessa
ordem, sempre. Um novo módulo monta esse bloco a partir do que já existe
(contrato, rastro de tentativas, `git status` só-leitura) e o `harness
budget` passa a devolvê-lo pronto sempre que o veredito não for `continue` —
tanto no JSON quanto impresso para quem está rodando no terminal, mesmo
formato de dois canais que `harness health` já usa.

## Critérios de aceitação
- Uma falha com sinal transiente (rede/timeout de aplicação) tenta de novo
  sozinha até 3× com pausa entre tentativas, e se algum retry passar, nada é
  gravado em `.harness/attempts/` das tentativas anteriores — `pytest
  tests/test_verify.py -q`
- Uma falha SEM sinal transiente nunca tenta de novo — vai direto ao registro
  de sempre, uma única execução — `pytest tests/test_verify.py -q`
- Depois de 3 tentativas todas com sinal transiente, a falha é registrada uma
  única vez, classificada como falha de ambiente, e o disjuntor devolve um
  veredito de parada específico para isso (não confundido com padrão
  repetido nem teto de iterações) — `pytest tests/test_budget.py -q`
- `harness budget --feature <id>` devolve, sempre que o veredito não for
  `continue`, um bloco de escalada com as seis partes do §8 na ordem exigida
  — `pytest tests/test_escalation.py -q`
- O passo 10 do lifecycle documenta o retry transiente e instrui usar o bloco
  de escalada gerado, em vez de escrever a mensagem à mão — `pytest
  tests/test_lifecycle.py -q`

## Não-objetivos
- **Timeout do PRÓPRIO processo do `verify_cmd`** (o teto de 600s de
  `_VERIFY_TIMEOUT_SECONDS`) não entra no retry. Reexecutar automaticamente
  um comando que já levou 10 minutos para estourar, até 3×, poderia prender a
  sessão por meia hora sem ninguém perceber — o contrário do espírito de
  "retry direto, backoff simples" do §8.1. Continua levantando `VerifyError`
  como hoje, sem retry.
- **Detecção de flake por assinatura nondeterminística** (mesmo teste, mesma
  linha de código, passa e falha sem motivo aparente) fica fora — não existe
  como distinguir isso de um bug real só pela linha de erro, sem rodar o
  teste várias vezes e comparar. O mecanismo aqui só cobre a manifestação
  RECONHECÍVEL de falha transiente (timeout, erro de rede), não flakiness em
  geral.
- **"Impossibilidade"**, uma das quatro classificações que a §8 lista, não é
  mecanizada aqui — é julgamento ("o requisito não existe", "a dependência
  foi descontinuada") que só a prosa das `stop_conditions` do `spec.md`
  cobre, mesma fronteira já registrada em D-004.
- Não reabre a decisão de `harness health` (D-007/D-008): o health check
  continua só perguntando na abertura da sessão. Este contrato mexe no
  disjuntor DURANTE o loop, não na abertura.

## Unknowns
(nenhum — `analyze` não reportou unknowns, e o escopo vem inteiramente do
design já aprovado do projeto.)
