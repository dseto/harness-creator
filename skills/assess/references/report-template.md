# Template do laudo — `/harness-creator:assess`

Formato exato da saída. Apresente na conversa, **não** grave em disco.

Ordem fixa: demanda literal → veredito → dimensões → perguntas →
encaminhamento. O veredito vem cedo porque é o que o leitor busca primeiro.

---

## Template

````markdown
## Demanda avaliada

> <a demanda LITERAL, como chegou — sem editar, resumir ou normalizar>

## Veredito: <COERENTE ✅ OK | PRECISA_ESCLARECER ⚠️ WARNING | CONFLITANTE ⚠️ WARNING | FORA_DE_ESCOPO ⛔ BLOQUEIA>

<Uma frase dizendo o porquê. Se não for COERENTE, esta frase precisa dizer o
que exatamente está pendente — não "há problemas a resolver".>

<Sempre na mesma linha do veredito, o sinal: ✅ OK / ⚠️ WARNING / ⛔ BLOQUEIA.
Só FORA_DE_ESCOPO bloqueia; os outros três seguem.>

## Dimensões

| # | Dimensão | Veredito | Achado (com fonte) |
|---|---|---|---|
| D1 | Pertinência | OK / FALHA / n/a | <símbolo X existe em `arquivo:linha`> ou <procurei X, Y, Z — nenhum existe> |
| D2 | Coerência | OK / FALHA / n/a | <contradiz `arquivo:linha`: "<citação curta da regra>"> |
| D3 | Precedente | OK / FALHA / n/a | <já feito em `<hash>`> / <não-objetivo em `.harness/work/<slug>/spec.md:NN`> |
| D4 | Executabilidade | OK / FALHA / n/a | <critério "<qual>" não admite comando de prova> |

**Os três estados são distintos, e confundi-los é o erro mais fácil aqui:**

- `OK` — você **verificou** e não achou impedimento. Afirma trabalho feito.
- `FALHA` — você achou impedimento, com fonte.
- `n/a` — você **não avaliou**, e diz por quê. Dois casos legítimos: (a) uma
  dimensão anterior já reprova e seguir não muda o veredito; (b) a fonte não
  existe no projeto (repo sem histórico, sem contrato anterior).

Nunca escreva `OK` para o caso (b). "Não havia o que ler" não é "verifiquei e
está limpo" — é a mesma confusão que a regra "sem fonte, não é achado" existe
para evitar, só que invertida: aqui o risco é carimbar de aprovado o que
ninguém olhou.

## Perguntas que precisam de resposta

<Só quando houver. Numeradas, diretas, respondíveis. Cada uma diz por que
importa — sem isso o leitor não sabe o custo de responder errado.>

1. **<pergunta direta>**
   Por que importa: <o que muda no contrato conforme a resposta>

## Encaminhamento

<Uma das quatro, conforme o veredito:>

- ✅ **COERENTE — segue.** Sem impedimento nas quatro dimensões. Próximo
  passo: `/harness-creator:plan`. (Isto não é aprovação da demanda — o gate
  continua no Passo 5 daquela skill.)

- ⚠️ **PRECISA_ESCLARECER — segue com pendência.** O ciclo não está barrado,
  mas <N> perguntas seguem em aberto. Elas precisam virar `unknowns` no
  `spec.md`, ou ser respondidas na entrevista do `plan` — se ficarem só neste
  laudo, o contrato nasce com o mesmo furo. Custo de ignorar: <o que quebra
  concretamente, ex.: "o critério de paginação vira teste intermitente">.

- ⚠️ **CONFLITANTE — segue com decisão pendente.** A demanda contradiz
  <fonte:linha>. O ciclo não está barrado, mas alguém precisa decidir, e a
  decisão tem duas saídas — nenhuma delas é "seguir sem escolher":
  (a) ajustar a demanda para caber na decisão vigente; ou
  (b) mudar a decisão anterior — que é mudança de projeto, exige atualizar
  <o documento que a registra> e não cabe no escopo desta demanda.
  Registre a escolha no `spec.md`, senão o conflito some entre este laudo e o
  contrato.

- ⛔ **FORA_DE_ESCOPO — pare.** Esta demanda não é sobre este repositório.
  Confira se foi colada no projeto certo. Não há o que planejar: seguir para o
  `plan` produziria um contrato bem formatado sobre um sistema que não existe
  aqui.
````

---

## Regras de preenchimento

**Fonte obrigatória.** Toda célula "Achado" cita `arquivo:linha` ou hash de
commit. Se você não tem fonte, o veredito da dimensão não é FALHA — é uma
pergunta em `PRECISA_ESCLARECER`. Suspeita sem evidência apresentada como
achado é o modo mais fácil de o laudo perder credibilidade inteira.

**D1 negativo precisa listar o que foi procurado.** "Não pertence ao projeto"
sem dizer quais símbolos você buscou é inauditável — o leitor não consegue
distinguir "procurou e não achou" de "não procurou".

**Citação curta e literal em D2.** Ao apontar contradição, cite a regra em até
uma linha, entre aspas. Parafrasear a regra que você está usando para reprovar
a demanda é como o projeto acabou com duas versões contraditórias da mesma
política.

**Não empilhe achado especulativo.** Um achado forte com fonte vale mais que
seis palpites. Se a dimensão está OK, escreva OK e siga.

**Perguntas: no máximo cinco.** Acima disso a demanda não está ambígua, está
ausente — e o veredito honesto é dizer que ela precisa ser reescrita pelo
autor, não fatiada em vinte perguntas.

---

## Exemplo preenchido — o caso que motivou a skill

````markdown
## Demanda avaliada

> Bata as claras em neve, acrescente o açúcar aos poucos e leve ao forno
> pré-aquecido a 180°C por 40 minutos.

## Veredito: FORA_DE_ESCOPO ⛔ BLOQUEIA

Nenhum conceito da demanda existe neste repositório, que é um plugin de
governança de agentes em Python.

## Dimensões

| # | Dimensão | Veredito | Achado (com fonte) |
|---|---|---|---|
| D1 | Pertinência | FALHA | Procurei `clara`, `açúcar`, `forno`, `receita`, `assar` em `src/`, `tests/` e `docs/` — zero ocorrências. O repo é descrito como plugin do Claude Code em `README.md:5` |
| D2 | Coerência | n/a | não avaliada — D1 já reprova |
| D3 | Precedente | n/a | não avaliada — D1 já reprova |
| D4 | Executabilidade | FALHA | Nenhum critério admite comando de prova; não há `verify_cmd` possível para "bata as claras em neve" |

## Encaminhamento

FORA_DE_ESCOPO — esta demanda não é sobre este repositório. Confira se foi
colada no projeto certo.
````

Repare no que o exemplo **não** faz: não tenta converter a receita numa
demanda de software plausível ("implementar módulo de receitas"), e não
pergunta se o usuário quer que ela seja adaptada. Ambas as saídas fabricariam
escopo que ninguém pediu — e o contrato resultante seria aprovado parecendo
legítimo.
