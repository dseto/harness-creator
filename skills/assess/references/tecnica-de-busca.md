# Técnica de busca — D1 (Pertinência)

Carregue no Passo 2, ao buscar os símbolos da demanda no código.

D1 é a dimensão que decide `FORA_DE_ESCOPO`, o único veredito que **bloqueia**
o ciclo. Errar aqui custa nos dois sentidos: um falso negativo barra trabalho
legítimo; um falso positivo carimba de pertinente exatamente o caso que a skill
existe para pegar. As duas armadilhas abaixo foram medidas, não supostas.

---

## 1. Palavra inteira, nunca substring

Medido no repositório `Harness-creator`, com dois termos de uma receita de bolo:

| Termo | `grep` substring | `grep -w` palavra inteira |
|---|---|---|
| `clara` | **47 arquivos** (por `declara`, `declarado`) | 5 (adjetivo em prosa) |
| `assar` | **22 arquivos** (por `passar`, `ultrapassar`) | **0** |

Uma busca ingênua faria uma demanda de confeitaria parecer fortemente aderente
a um plugin de governança de agentes.

**Use `\b<termo>\b`** no `Grep`. E confirme abrindo pelo menos uma ocorrência:
contagem alta com todas as ocorrências dentro de outra palavra é **ausência**,
não presença.

---

## 2. Busque no idioma do CÓDIGO, não só no da demanda

Demanda em português quase sempre encontra código em inglês. Traduza cada
conceito antes de buscar:

| Demanda (pt) | Código (en) |
|---|---|
| jogador | `player` |
| clima / previsão | `weather`, `forecast` |
| escalação | `lineup`, `squad` |
| cliente | `customer`, `client` |
| pedido | `order` |
| pagamento | `payment` |

Buscar só os termos como foram escritos produz um D1 **falso-negativo
silencioso** — você conclui "não existe" sobre um domínio que existe com outro
nome, e bloqueia uma demanda legítima.

---

## 3. Ausência de domínio ≠ ausência de feature

A distinção que separa `FORA_DE_ESCOPO` de uma demanda legítima ainda não
implementada. Exemplo real, mesmo repositório, duas demandas:

| Demanda | `Customer` | `page` / `skip` / `take` | Leitura |
|---|---|---|---|
| paginar a listagem de clientes | 3 arquivos | **0** | domínio existe, feature falta → **legítima** |
| escalação de time de futebol | — | `jogador`, `goleiro`, `astral`: **0** | domínio não existe → `FORA_DE_ESCOPO` |

Zero ocorrência do que a demanda quer **construir** é esperado — é o trabalho.
Zero ocorrência do **domínio inteiro** é o sinal de que a demanda não é sobre
este repositório.

Ao concluir D1 negativo, liste **quais termos você buscou**. "Não pertence ao
projeto" sem isso é inauditável: o leitor não distingue "procurou e não achou"
de "não procurou".
