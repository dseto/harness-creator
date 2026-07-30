---
name: assess
description: >-
  Avalia uma user story/demanda contra as quatro fontes de verdade do projeto —
  documentação, código-fonte, histórico do git e contratos anteriores do harness —
  e emite um laudo COERENTE/PRECISA_ESCLARECER/CONFLITANTE/FORA_DE_ESCOPO, cada
  achado com evidência file:line e cada ambiguidade virando pergunta direta.
  Read-only, nunca reescreve a demanda nem cria contrato.
when_to_use: >-
  ANTES de /harness-creator:plan, sempre que uma demanda chegar em linguagem
  natural — especialmente vinda de terceiro (ticket, e-mail, chat) ou quando
  houver dúvida se ela pertence a este repositório, se já foi feita, ou se
  contradiz uma decisão anterior. Também quando o usuário pedir "avaliar essa
  story", "essa demanda faz sentido?", "isso já foi feito?".
argument-hint: "[a user story / demanda em linguagem natural]"
disable-model-invocation: false
---

# Assess — laudo de aderência de uma demanda

Você vai avaliar a demanda (argumento `$0`, ou peça se vazio) contra o que o
projeto **de fato é**, e devolver um laudo. Você **não** escreve contrato,
**não** corrige a demanda e **não** decide se ela vale a pena — isso é
julgamento de produto, e é do humano.

O que você decide é mais estreito e verificável: *esta demanda é executável
neste repositório, sem contradizer o que já foi decidido?*

> Esta skill é o portão da **demanda**, assim como `/harness-creator:preflight`
> é o portão do **repositório**. Rodar antes do `/harness-creator:plan` custa
> uma leitura; descobrir depois custa um contrato inteiro.

## Como executar — dois subagentes, dois modelos

**Recomendação forte: rode a coleta (Passo 2) num subagente `model: "haiku"`,
e o julgamento (Passo 3) + a emissão do laudo (Passo 4) num segundo
subagente no modelo forte, alimentado pelas evidências que o primeiro
trouxe.** Não é regra dura — repo pequeno e demanda óbvia rodam bem inline
—, mas o padrão deveria ser delegar, por dois motivos.

**1. Contexto.** Medido em 6 avaliações reais: cada uma consumiu em média
**~64k tokens e ~17 tool calls** de levantamento (greps, leitura de fonte,
`git log`, contratos anteriores) para produzir um laudo de **~1.2k**. Rodando
inline, ~98% disso vira ruído permanente na sessão principal — sobre um
repositório que pode nem ser o alvo do trabalho seguinte. A coleta (Passo 2)
é justamente essa parte mecânica: grep, glob, `git log`, leitura de arquivo,
sem julgamento nenhum envolvido — por isso é a metade que roda em Haiku, não
em modelo forte. O julgamento (Passo 3/4) é quem decide, e continua caro de
propósito.

**2. Independência — o motivo que importa mais.** A sessão principal é onde o
viés mora: quem acabou de ouvir a demanda descrita com entusiasmo, ou passou a
última hora construindo em direção a ela, não é um bom juiz dela. Um subagente
frio não sabe qual resposta se espera. É o mesmo princípio de produtor ≠
revisor da Fase 4, e do juiz frio que a Fase 5 propõe para o contrato. Rodar o
julgamento num segundo subagente (modelo forte) preserva essa independência
mesmo depois que a coleta trocou de modelo — o que muda de nível não é
*quem* julga, é *quem* busca.

Observado na prática: numa execução inline, o avaliador marcou D3 como `OK`
sem ter o que ler e deixou passar dois defeitos na própria demanda que tinha
ajudado a redigir. Os subagentes frios, sobre a mesma demanda, pegaram os dois.

Ao delegar, o prompt do subagente **de coleta** (Haiku) precisa conter, no
mínimo: o caminho desta `SKILL.md`, o **caminho absoluto do repositório-alvo**
(ele não herda o seu `cwd`, e avaliar contra o repo errado produz um laudo
plausível e inútil), a demanda literal, e a instrução de devolver as
evidências cruas do Passo 2 (`arquivo:linha` por fonte) — **não** um
veredito. O prompt do subagente **de julgamento** (modelo forte) recebe essa
coleta, o caminho da `SKILL.md` e a demanda literal, e devolve **apenas** o
laudo (Passo 3 + Passo 4).

Rodar inline não invalida nada — só saiba que você está trocando independência
e contexto por uma ida a menos.

## Passo 1 — Registrar a demanda como ela chegou

Cole a demanda **literalmente** no início da sua análise, sem editar, resumir
ou "melhorar". O laudo precisa mostrar o que foi avaliado — se você
normalizar o texto antes, ninguém consegue conferir o veredito depois.

Se vier vazia, peça. Não invente a demanda a partir do contexto da sessão.

## Passo 2 — Levantar as quatro fontes

Colete **antes** de julgar. Cada uma responde a uma pergunta diferente:

**1. Documentação — quais regras já existem?**
```
AGENTS.md · CLAUDE.md · README.md · docs/**
```
Leia os blocos de governança do `AGENTS.md` e a prosa humana acima deles: é
onde moram as regras inegociáveis e as decisões de projeto.

**2. Código-fonte — os símbolos da demanda existem?**
Busque os nomes concretos citados (módulo, função, endpoint, tela, tabela)
com `Grep`/`Glob`. Símbolo citado que não existe em lugar nenhum é o sinal
mais forte de demanda que não pertence a este repositório — ou de nome
trocado, que é uma pergunta a fazer.

> **Carregue `references/tecnica-de-busca.md` antes de buscar.** D1 decide o
> único veredito que bloqueia, e tem duas armadilhas medidas que invertem o
> resultado: substring (`assar` bate em 22 arquivos por causa de `passar`) e
> idioma (demanda em português, código em inglês). O arquivo traz as duas,
> mais como separar "domínio não existe" de "feature ainda não construída".

**3. Histórico do git — já foi tentado?**
```
git log --oneline -30
git log --all --oneline --grep="<termo da demanda>"
```

**4. Histórico do harness — já foi contratado?**
```
.harness/work/*/spec.md        contratos anteriores: escopo e não-objetivos
.harness/feature_list.json     o contrato ATIVO, se houver
.harness/evidence/             o que já foi provado
```
Os **não-objetivos** de um contrato anterior são ouro: dizem o que foi
deliberadamente deixado de fora, e por quê.

## Passo 3 — Avaliar nas quatro dimensões

Uma linha de veredito por dimensão. **Todo achado cita a fonte**
(`arquivo:linha` ou hash de commit).

| # | Dimensão | Pergunta | Fonte |
|---|---|---|---|
| D1 | **Pertinência** | A demanda fala deste sistema? Os símbolos citados existem? | código + docs |
| D2 | **Coerência** | Contradiz alguma regra ou decisão já documentada? | docs + AGENTS.md |
| D3 | **Precedente** | Já foi feito, tentado, ou descartado por decisão? | git + `.harness/work/` |
| D4 | **Executabilidade** | Dá para escrever critério de aceitação com comando de prova? | perfil + testes |

**D4 é o filtro mais produtivo.** Um critério que não admite comando de prova
não é critério, é intenção — e vai virar contrato impossível de verificar no
Passo 3 do `/harness-creator:plan`. Aponte **qual** critério não fecha e **o
que falta** para fechar.

## Passo 4 — Emitir o laudo

Carregue `references/report-template.md` (relativo a esta skill) e siga o
formato exato. O veredito global é o pior caso entre as quatro dimensões.

**Um único veredito interrompe o ciclo. Os outros três seguem.**

| Veredito | Sinal | Significa | Encaminhamento |
|---|---|---|---|
| `COERENTE` | ✅ **OK** | Pertence, não conflita, é executável | Segue para `/harness-creator:plan` |
| `PRECISA_ESCLARECER` | ⚠️ **WARNING** | Falta clareza, mas nada impede | **Segue** — as perguntas viram insumo do `plan` |
| `CONFLITANTE` | ⚠️ **WARNING** | Contradiz regra ou decisão anterior | **Segue** — o conflito precisa ser decidido no gate humano |
| `FORA_DE_ESCOPO` | ⛔ **BLOQUEIA** | Não é sobre este repositório | **Pare.** Não há o que planejar |

Por que só um bloqueia: um `deny` fácil demais treina o humano a ignorar o
laudo, e um laudo ignorado é pior que nenhum. `PRECISA_ESCLARECER` e
`CONFLITANTE` descrevem demandas **legítimas com trabalho pendente** — quem
decide se esse trabalho vale a pena é o humano, no gate do `plan`, não esta
skill. `FORA_DE_ESCOPO` é diferente em natureza: não é uma demanda difícil, é
uma demanda que não existe neste projeto.

### O warning não pode parecer um OK

Este é o único jeito de a mudança acima dar errado. Ao emitir warning:

- **Diga a palavra `WARNING` no veredito**, não só no template.
- **Nunca termine com "pode seguir" sozinho.** Termine com o que segue
  *junto*: as perguntas em aberto ou o conflito a decidir.
- **Nomeie o custo de ignorar.** "Sem definir a ordenação, o critério de
  paginação vira teste intermitente" — não "recomenda-se esclarecer".

Em `PRECISA_ESCLARECER`, as perguntas são o produto principal. Cada uma
precisa ser **direta e respondível** — "qual o comportamento esperado quando
o campo vem vazio?", não "poderia detalhar melhor os requisitos?".

Em `CONFLITANTE`, o produto é a **decisão que o humano precisa tomar**, posta
com as duas saídas explícitas: ajustar a demanda, ou mudar a decisão anterior
(que é mudança de projeto, e exige atualizar o documento que a registra).

## Passo 5 — Parar

Este é o fim da skill, **em qualquer veredito**. Você não chama
`/harness-creator:plan`, não escreve `spec.md`, não cria
`.harness/work/<slug>/`. Entregue o laudo e devolva o controle.

"Segue" no encaminhamento significa que **o ciclo não está barrado** — não que
você deva continuar sozinho. Quem aciona o próximo passo é o humano.

Nos três vereditos que seguem, feche dizendo o que precisa **viajar junto**
para o `plan`: as perguntas em aberto viram `unknowns` do `spec.md`, e um
conflito não resolvido precisa aparecer no `spec.md` como decisão registrada —
senão ele desaparece entre o laudo e o contrato, que é exatamente onde este
laudo perde a utilidade.

## Regras

- **Read-only, sem exceção.** Nenhuma escrita em disco: nem contrato, nem
  correção de código, nem arquivo de laudo. O laudo vai na conversa.
- **Sem fonte, não é achado.** Todo item do laudo cita `arquivo:linha` ou
  hash de commit. Impressão sem evidência não entra — vira pergunta em
  `PRECISA_ESCLARECER`, que é o lugar honesto dela.
- **Nunca reescreva a demanda para torná-la viável.** Se ela é ambígua, o
  produto é a pergunta, não uma versão consertada por você. Reescrever é
  fabricar escopo que o humano não pediu — e ele aprovaria a sua versão
  achando que era a dele.
- **`FORA_DE_ESCOPO` não é juízo de valor.** Não é "essa demanda é ruim"; é
  "ela não é sobre este repositório". Diga qual símbolo/conceito você
  procurou e não achou.
- **Ausência de conflito não é aprovação.** `COERENTE` significa que você não
  achou impedimento nas quatro dimensões — não que a demanda deve ser feita.
  A decisão de fazer continua sendo do humano, no gate do `plan`.
- **Não substitui o gate de aprovação do `/harness-creator:plan`.** Este laudo
  é insumo para aquela decisão, nunca um atalho para ela.
