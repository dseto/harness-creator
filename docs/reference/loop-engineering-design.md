# Design de Loop Engineering — Loop Completo, Eficiente e Sem Over-engineering

> Consolida a taxonomia base (Goal→Action→Observation→Adjustment + componentes de harness)
> com as lacunas identificadas na análise crítica: budget mecânico, spine com decisões e
> lições, protocolo de resume com reconciliação, healing com taxonomia de falhas e
> higiene de contexto. Cada seção declara o mínimo obrigatório e o que é opcional —
> a regra anti-over-engineering é explícita: só se constrói a camada seguinte quando a
> dor da camada atual aparecer de fato.

---

## 1. Escopo e definições

- **Loop**: o ciclo iterativo que o agente segue para concluir uma meta — dita *o que*
  o agente faz e *quando* termina.
- **Harness**: a infraestrutura onde o loop vive — permissões, hooks, ferramentas,
  isolamento, recuperação. Dita *onde* o agente opera e *o que ele não pode fazer*.
- Fronteira de responsabilidade: **invariantes vão para o harness (determinístico);
  julgamento vai para o loop (probabilístico)**. Regra imposta por hook é garantia;
  regra em prompt é pedido.

Este documento desenha o loop. Assume um harness mínimo já existente (seção 10 define
esse mínimo).

---

## 2. Princípios de projeto

1. **Forma mais simples que resolve.** Prompt único > workflow encadeado > loop
   autônomo. Loop autônomo é último recurso, não default. Se a tarefa cabe em uma
   passada com revisão humana, não construa loop.
2. **Ground truth do ambiente, nunca auto-avaliação.** O sinal de correção vem de
   teste, compilador, CI, erro de execução — não da opinião do modelo sobre o próprio
   trabalho.
3. **Estado fora do contexto.** Contexto de conversa é perecível (compaction, sessão
   nova). Tudo que precisa sobreviver à sessão vive em arquivo.
4. **Fail-closed.** Na dúvida, o loop para e escala. Loop que "continua mesmo assim"
   acumula estrago mais rápido do que produz valor.
5. **Um gate humano, legível.** Humano aprova o plano/contrato uma vez, no início.
   Depois disso o loop roda sozinho até a entrega — mas reporta em linguagem natural
   o que fez, não em IDs e JSON cru. Os dois extremos falham: humano aprovando cada
   passo (rendição por fadiga — aprova sem ler) e humano ausente (dívida de
   compreensão — ninguém sabe mais como o sistema funciona).

---

## 3. Anatomia do ciclo (uma iteração)

```
┌────────────────────────────────────────────────────────┐
│  GOAL (fixo na sessão, vem do contrato aprovado)       │
│    ↓                                                   │
│  PLAN   → qual fatia atacar agora, quais arquivos      │
│    ↓                                                   │
│  ACTION → editar, gerar, chamar ferramenta             │
│    ↓                                                   │
│  OBSERVATION → rodar verificação barata (ver §6)       │
│    ↓                                                   │
│  ADJUSTMENT  → verde: registrar e avançar              │
│                vermelho: classificar falha (ver §8)    │
│    ↓                                                   │
│  CHECKPOINT  → atualizar spine (ver §5)                │
└────────────────────────────────────────────────────────┘
```

Regras da iteração:

- **Uma fatia por iteração.** Fatia = menor unidade com critério de verificação
  próprio. Nunca duas fatias em paralelo na mesma sessão — raio de impacto pequeno
  e revisável.
- **Erro entra cru no próximo ciclo.** O feedback para o Adjustment é a mensagem de
  erro exata (stack trace, saída do teste), não um resumo. Resumir erro é jogar fora
  o sinal.
- **Checkpoint é obrigatório, não opcional.** Toda iteração que muda estado do mundo
  (arquivo editado, decisão tomada, falha nova) atualiza a spine antes de continuar.
  Iteração que só lê não precisa.

---

## 4. Condições de parada — semântica + mecânica (as duas, sempre)

A parte mais difícil do design. Um loop precisa de **dois disjuntores independentes**:

### 4.1 Critério de sucesso (semântico, executável)

- Formato: comando que sai 0/≠0 (`pytest -k escopo`, `npm run build`, lint). Nunca
  prosa ("terminar o documento").
- Ruim: "escreva o relatório". Bom: "o relatório contém resumo executivo + 3 seções,
  cada uma com 2 citações, e o validador de estrutura passa".
- Se a tarefa não admite verificação executável, o critério vira checklist binário
  avaliado por um verificador separado (§6) — nunca pelo próprio gerador.

### 4.2 Budget (mecânico, incondicional)

Critério semântico mal escrito + ausência de teto = loop infinito. O budget é o
seguro contra o próprio erro de design:

| Teto | Valor inicial sugerido | Ao estourar |
|---|---|---|
| Tentativas consecutivas na MESMA falha | 3 | parar, registrar diagnóstico, escalar |
| Iterações totais na fatia | 10 | parar, registrar estado, escalar |
| Tempo/custo da sessão | definido por tarefa | parar no próximo checkpoint |

- Estourar budget **nunca é silencioso**: registra na spine o que foi tentado, qual o
  último erro, e devolve controle ao humano com diagnóstico — não com "falhou".
- **Sinal de impossibilidade** também para o loop antes do teto: se o agente conclui
  que o critério é inatingível como especificado (dependência inexistente, requisito
  contraditório), parar imediatamente é acerto, não desistência.

### 4.3 Sinal de convergência (quando a tarefa admite gradiente)

Os disjuntores 4.1/4.2 respondem "chegou?" e "esgotou?". Falta a pergunta que
diferencia um loop saudável de um que gira em falso: **está se aproximando ou se
distanciando do objetivo?**

Aplicável quando o progresso é mensurável em escala contínua — % de similaridade
com um documento-alvo, nº de testes passando, contagem de erros de lint/build,
cobertura, distância de schema. Tarefas binárias (passa/não passa, sem gradiente)
pulam esta seção: forçar métrica onde não há gradiente é over-engineering.

Protocolo:

1. **Medir a cada iteração**, no Observation, com o mesmo instrumento sempre
   (mudar a régua no meio invalida a série). Registrar valor atual e
   melhor-até-agora no `progress.md` (§5.1).
2. **Checkpoint do melhor estado.** Guardar referência ao estado que produziu o
   melhor valor (commit, cópia do artefato). É o ponto de retorno.
3. **Reagir à trajetória**, não só ao valor absoluto:

   | Trajetória | Leitura | Reação |
   |---|---|---|
   | Melhorando | convergindo | continuar |
   | Platô — K iterações (sugestão: 3) sem melhora significativa | estratégia esgotou | tratar como padrão repetido (§8.2): mudar abordagem (registrar em `decisions.md`) ou escalar |
   | Oscilando — valor alterna melhor/pior com variância alta e tendência plana por K iterações | girando em falso (nem converge nem diverge) | tratar como platô: pivotar ou escalar. Caso traiçoeiro: alternância nunca acumula J pioras consecutivas nem K platôs — sem esta linha, oscilação queima o budget inteiro sem disparar gatilho nenhum |
   | Piorando — J iterações (sugestão: 2) consecutivas abaixo do melhor | **divergindo — a "regressão" do loop** | **reverter ao checkpoint do melhor estado** e mudar de estratégia; nunca continuar iterando sobre versão pior que uma já alcançada |

4. **Platô e divergência são stop conditions de pleno direito** — somam-se aos tetos
   de §4.2, não os substituem.

Duas salvaguardas:

- **A métrica orienta, o critério decide.** Métrica é proxy — otimizá-la diretamente
  convida Goodhart (documento 98% similar ao alvo pode estar 98% similar e errado no
  que importa). "Pronto" continua sendo exclusivamente o critério executável de §4.1;
  a métrica só governa a trajetória e a decisão de reverter/pivotar.
- **Melhora marginal conta como platô.** Definir delta mínimo significativo (ex.:
  <1% por iteração = estagnado); sem isso, o loop justifica infinitas iterações com
  ganhos homeopáticos e consome o budget inteiro convergindo assintoticamente.
  Medir também a melhora ACUMULADA contra o valor inicial, não só contra a
  iteração anterior: "melhorou 2% em 20 iterações" é estagnação que a comparação
  passo-a-passo deixa passar.

Nota de implementação: os contadores K/J são heurística para loops curtos (<6
iterações — o caso típico de fatia de código), onde teste estatístico não tem
poder. Para loops longos com métrica contínua (similaridade de documento, contagem
de erros, RAG), detectores estatísticos de tendência são superiores aos contadores
fixos — ex.: LoopGain (github.com/loopgain-ai/loopgain), que implementa exatamente
esta seção via razão de ganho E(n)/E(n-1), t-test no slope e rollback ao
melhor-até-agora, com adapters para Claude Agent SDK e afins. Mesma limitação
declarada dos dois lados: detecta convergência, não correção — o critério
executável de §4.1 continua sendo o único juiz de "pronto".

---

## 5. Spine — o estado persistente (3 registros, 1 arquivo cada)

O texto base prevê só "progresso". Um loop que sobrevive a interrupções e melhora com
o tempo precisa de **três registros distintos**, porque têm ciclos de vida diferentes:

### 5.1 `progress.md` — estado da execução (vida: a demanda)

O que já foi feito, o que está em andamento, o que quebrou, próximo passo. Formato
mínimo:

```markdown
# Progress — <demanda>
## Fatias
| id | descrição | status | prova |
## Em andamento
<fatia atual, próximo passo concreto>
Métrica de convergência (se houver, §4.3): <valor atual> | melhor até agora: <valor @ iteração>
Tentativas:
  1. <abordagem> → <erro/resultado resumido em 1 linha, com identificador do erro>
  2. <abordagem> → <erro/resultado>
## Quebrado / pendente
<explícito, nunca escondido>
```

- **Histórico de tentativas é obrigatório** para a fatia em andamento: uma linha por
  tentativa (abordagem → erro resultante). Sem ele, a regra do padrão repetido (§8.2)
  só funciona dentro de uma sessão — a sessão seguinte retoma sabendo *onde* parou,
  mas não *o que já falhou*, e repete a tentativa 1 de boa fé.
- Atualizado a **cada checkpoint** (fim de iteração que mudou estado), não só no fim
  da sessão — sessão pode morrer no meio.
- Regenerado a cada demanda nova. Histórico vai para evidência/git, não fica aqui.

### 5.2 `decisions.md` — decisões com porquê (vida: o projeto)

Registro append-only de escolhas que atravessam iterações e demandas:

```markdown
## D-007 — <título curto> (2026-08-08)
Decisão: <o que foi decidido>
Porquê: <a razão, incluindo alternativas descartadas e por quê>
```

- **Por que existe**: spine só de estado registra *o quê*, não *porquê*. Sem isso,
  loop longo re-litiga: a iteração 40 "descobre" e tenta a abordagem que a iteração
  12 descartou por bom motivo — o motivo não foi persistido. Modo de falha clássico
  de agente autônomo.
- Gatilho de escrita: toda vez que o loop descarta uma alternativa por razão não
  óbvia, ou toma decisão que restringe iterações futuras.
- Anti-over-engineering: é um arquivo markdown append-only. **Não** é sistema de ADR
  com template de 12 campos. Três linhas por decisão bastam.

### 5.3 `lessons.md` — fricções para o loop de segunda ordem (vida: o projeto)

```markdown
- [ ] <fricção observada> → <melhoria candidata no harness/skill/critério>
```

- Captura no momento em que a fricção acontece (regra que barrou demais, critério
  ambíguo, ferramenta ruidosa, erro repetido) — uma linha, sem interromper o trabalho.
- **Consumido por humano** em cadência regular (fim de demanda ou semanal): cada item
  vira melhoria no harness, ajuste de skill/documento, ou é descartado.
- Anti-over-engineering: o loop **anota** lições; o loop **não aplica** lições
  sozinho. Auto-modificação do harness pelo próprio agente é a camada mais perigosa
  e quase nunca vale o risco — mantém-se o humano como compilador das lições.

---

## 6. Verificação — barata por iteração, cara no gate

Custo de verificação multiplica pelo número de iterações. Estratificar:

| Camada | Quando roda | O quê | Custo |
|---|---|---|---|
| 1. Sinal rápido | toda iteração | lint, typecheck, teste do escopo afetado (`pytest -k`) | segundos |
| 2. Prova da fatia | ao declarar fatia pronta | `verify_cmd` da fatia + re-prova incremental (abaixo) | s–min |
| 3. Review profundo | uma vez, antes da entrega | suíte relevante completa, verificador separado, review humano | min+ |

Regras:

- **Re-prova incremental (proteção contra regressão de código entre fatias).** A
  camada 1 só verifica o escopo afetado — a fatia 5 pode quebrar a fatia 2 e ninguém
  perceberia até o gate final, muitas iterações depois, quando o diagnóstico fica
  caro. Correção: ao declarar uma fatia pronta (camada 2), rodar também os
  `verify_cmd` das fatias já done que **compartilham arquivos** com a fatia atual —
  a interseção, não a suíte inteira. Custo proporcional ao acoplamento real; pega a
  regressão quando o diff suspeito tem uma iteração de tamanho.
- **Nunca rodar camada 3 dentro do loop de iteração.** Suíte completa a cada volta
  explode custo e latência sem ganho de sinal.
- **Verificador ≠ gerador.** Na camada 3, quem avalia não é quem gerou: subagente com
  contexto limpo, ou modelo/persona distinta. Motivo técnico: o contexto do gerador
  contamina o julgamento — verificador limpo pega o que o gerador racionalizou.
- **Prova registrada.** Verificação verde da camada 2 gera evidência (timestamp,
  comando, hash do estado verificado). Marcar fatia como "done" sem evidência fresca
  quebra a garantia que o loop existe para dar. Evidência com hash também detecta o
  caso "o código mudou depois da prova".

---

## 7. Resume — protocolo de retomada com reconciliação

Ter spine não basta; o protocolo de leitura é o que torna o resume confiável. Toda
sessão nova (ou retomada pós-interrupção) executa, **nesta ordem**:

1. **Carregar governança** (regras do harness, este design).
2. **Health check do ambiente** — dependências instaladas, ferramentas respondem.
   Ambiente quebrado é falha de infra (§8.3), não motivo para "tentar mesmo assim".
3. **Ler a spine** — `progress.md`, `decisions.md` (lessons não bloqueia retomada).
4. **RECONCILIAR estado declarado × estado real.** O passo que o texto base omite e
   que separa resume confiável de resume ingênuo:
   - `git log` / estado dos arquivos × o que o progress alega ter feito;
   - evidências registradas × fatias marcadas como done (hash ainda bate?);
   - working tree × expectativa de tree limpa.
   **Divergência detectada → não continuar.** Registrar a divergência, corrigir o
   registro (o mundo é a verdade, a nota é a alegação) ou escalar se a divergência
   indicar estado corrompido.
5. **Escolher exatamente uma fatia pendente** e entrar no ciclo (§3).

Encerramento simétrico: toda sessão termina com working tree limpa, spine atualizada
e nada não-registrado — o handoff (para a próxima sessão ou para o humano) parte de
estado previsível.

---

## 8. Falhas e healing — taxonomia com respostas distintas

"Autocorrigir até passar" só cobre um dos três tipos de falha. Tratar os três de
forma diferente é o que o texto base não faz:

### 8.1 Falha transiente (timeout, rede, flake)

- Resposta: retry direto, com limite próprio (2–3) e backoff simples.
- Não conta como "tentativa de correção" — nada foi corrigido, só repetido.
- Mesmo erro transiente 3× → reclassificar como infra (§8.3).

### 8.2 Falha estrutural (teste vermelho, lógica errada)

- Resposta: o loop de autocorreção clássico — erro cru entra no próximo Adjustment,
  agente corrige, re-verifica. Limitado pelo budget (§4.2).
- Regra do padrão repetido: se a tentativa N produz o **mesmo erro** da tentativa
  N-1, a abordagem está errada, não a execução — mudar de estratégia conta como
  decisão (registrar em `decisions.md`) ou escalar.

### 8.3 Falha de infraestrutura (hook morto, tool indisponível, guard em no-op)

- A mais perigosa, porque **não gera feedback no loop — gera silêncio**. O agente
  continua "funcionando" sem as garantias que acha que tem.
- Resposta: **nunca healing automático, sempre parada + escalada.** Loop não conserta
  o próprio harness — consertar a própria jaula é exatamente o comportamento que não
  se quer premiar.
- Mitigação preventiva (harness, não loop): health check no início da sessão (§7.2)
  e componentes de governança que declaram estado ("estou ativo") verificável — um
  guard silenciosamente desligado precisa aparecer em algum status, senão semanas de
  sessões viram evidência contaminada.

### Escalada — formato obrigatório

Toda escalada ao humano entrega diagnóstico, não sintoma:

```
O que estava sendo tentado (fatia + critério)
O que foi tentado (abordagens, em ordem)
Último erro (cru)
Classificação (transiente esgotado / estrutural no teto / infra / impossibilidade)
Estado da spine (atualizada? tree limpa?)
Sugestão de próximo passo, se houver
```

---

## 9. Higiene de contexto

Loop longo morre mais por contexto podre do que por lógica ruim. Práticas mínimas:

- **Contexto novo por demanda.** Não arrastar a conversa de uma demanda para a outra;
  a spine existe para isso.
- **Subagentes como isoladores de contexto**, não (só) como divisão de trabalho:
  exploração suja (ler 30 arquivos para achar um) roda num subagente; só a conclusão
  volta ao contexto principal. O mesmo vale para o verificador da camada 3.
- **Just-in-time em vez de tudo-no-prompt.** Carregar documento/skill quando a
  iteração precisa, não tudo no início "por garantia".
- **Compaction-aware.** Assumir que qualquer conteúdo do contexto pode sumir a
  qualquer momento; se importa, está na spine (regra do §2.3 aplicada).

### 9.1 Subagentes — papéis distintos, sem viés herdado

Subagentes servem a dois propósitos que não se confundem:

**a) Isolamento de contexto** (acima): manter o contexto principal limpo.

**b) Isolamento de viés**: garantir que quem julga não herdou as premissas de quem
produziu. Um agente que gerou o artefato — ou que apenas *leu* o raciocínio do
gerador — já está contaminado: tende a validar as mesmas suposições que produziram
o erro. Papéis típicos:

| Papel | Recebe | NÃO recebe | Devolve |
|---|---|---|---|
| Explorador | pergunta de busca | hipóteses do orquestrador sobre a resposta | fatos com localização (file:line), sem recomendação |
| Implementador | fatia + critério + fatos do explorador | histórico de tentativas de OUTRAS abordagens em curso | diff + resultado da verificação |
| Verificador | artefato + critério de aceitação | raciocínio do implementador, justificativas, "por que fiz assim" | veredito + evidência, sem consertar |

Regras de ausência de viés:

- **Avaliação cega**: o verificador recebe o artefato e o critério — nunca a
  conversa que o produziu. Se o prompt do verificador contém a justificativa do
  implementador, a avaliação já nasceu contaminada.
- **Um papel por agente, na mesma tarefa**: quem implementou não verifica; quem
  verificou não conserta (devolve o veredito ao loop, que decide). Fundir papéis
  economiza uma chamada e custa a independência — troca ruim.
- **Veredito com evidência**: verificador que só diz "reprovado" gera re-tentativa
  cega; veredito aponta o quê e onde, e o erro entra cru no Adjustment (§3).
- **Diversidade quando o risco justifica**: para entregas críticas, verificadores
  com lentes distintas (correção, segurança, aderência ao critério) pegam modos de
  falha que N cópias do mesmo verificador não pegam.

Anti-over-engineering: subagente **custa** — latência e tokens multiplicados,
coordenação. O mínimo obrigatório deste design é UM ponto de independência: o
verificador da camada 3 (§6). Explorador separado entra quando a exploração poluir
o contexto principal (§9); painéis com lentes múltiplas só em entrega crítica.
Começar single-agent com verificador cego no gate; crescer só com dor comprovada.

---

## 10. O harness mínimo que este loop pressupõe

Ordem de construção correta: **harness de segurança → loop → harness de
conveniência**. ("Construa o loop primeiro" vale para depurar lógica com dados de
brinquedo; dar autonomia real sem jaula é como a primeira iteração já faz estrago.)

Mínimo obrigatório antes de rodar o loop com autonomia:

1. **Permissões/deny fail-closed** — superfícies destrutivas barradas por hook
   determinístico, não por instrução. Calibração: barrar o mínimo necessário — deny
   excessivo empurra o operador para desligar tudo (kill-switch), que é desproteção
   total.
2. **Critério executável** — pelo menos um comando de verificação funcionando (§6.2).
3. **Health check** — script que confirma ambiente utilizável (§7.2).
4. **Isolamento de escrita** — branch/worktree próprio; nunca direto na principal.

Conveniências (worktrees paralelos, cron/agendamento, métricas, PR automatizado)
vêm depois, quando a operação do loop mostrar necessidade.

---

## 11. Guia anti-over-engineering — escada de maturidade

Construir tudo acima de uma vez é o over-engineering que este design proíbe. Subir
degrau **apenas quando a dor do degrau atual aparecer**:

| Nível | O que tem | Suba quando… |
|---|---|---|
| 0 | Prompt + revisão humana | a tarefa se repetir e a revisão virar gargalo |
| 1 | Loop com critério executável + budget + progress.md | sessões começarem a ser interrompidas/retomadas |
| 2 | + protocolo de resume com reconciliação + taxonomia de falhas | o loop re-litigar decisões ou repetir becos sem saída |
| 3 | + decisions.md + verificador separado na entrega | fricções recorrentes ficarem invisíveis |
| 4 | + lessons.md com cadência humana de consumo | múltiplos loops/projetos em paralelo |
| 5 | + worktrees paralelos, agendamento, métricas | (parar aqui; auto-modificação do harness fica fora) |

Sinais de que se passou do ponto: templates com campos que ninguém preenche;
registros que ninguém lê; gates que o humano aprova sem olhar; healing automático de
coisas que falharam uma vez. Cada um desses é peso morto — remover é melhoria.

---

## 12. Checklist de conformidade (resumo executável do design)

**Por iteração**
- [ ] Uma fatia só; arquivos dentro do raio declarado
- [ ] Verificação camada 1 rodou; erro entrou cru no ajuste
- [ ] Métrica de convergência medida (se a tarefa tem gradiente); trajetória avaliada:
      platô K× → pivotar; oscilação (variância alta, tendência plana) → pivotar;
      piora J× → reverter ao melhor checkpoint
- [ ] Checkpoint: progress.md atualizado se algo mudou — incluindo linha de tentativa
      (abordagem → erro) e valor da métrica

**Por fatia**
- [ ] Critério executável definido antes de começar
- [ ] Prova (camada 2) registrada com timestamp + hash antes do "done"
- [ ] Re-prova incremental: verify_cmd das fatias done que compartilham arquivos
- [ ] Decisão não-óbvia → linha em decisions.md

**Por sessão**
- [ ] Abertura: governança → health check → spine → reconciliação → uma fatia
- [ ] Budget vivo: teto de tentativas, iterações e tempo definidos
- [ ] Encerramento: tree limpa, spine atualizada, quebrado documentado

**Por demanda**
- [ ] Gate humano único no início (contrato aprovado, legível)
- [ ] Entrega: verificador separado, em avaliação CEGA (artefato + critério, sem o
      raciocínio do gerador) + relato em linguagem natural com link para a prova
- [ ] Fricções da demanda anotadas em lessons.md; consumo agendado

**Nunca**
- [ ] Loop consertando o próprio harness
- [ ] Fatia "done" sem evidência fresca
- [ ] Escalada sem diagnóstico
- [ ] Camada de maturidade construída antes da dor existir
