---
slug: disjuntor-enxerga-o-loop
approved_by:
approved_at:
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd na mesma tarefa"
  - "Fazer o hook Stop enxergar o rastro exigir que o arquivo gerado importe o pacote `harness` — pare e escale: o hook roda fora do venv do projeto, e a decisão D-010 já resolveu essa fronteira uma vez"
  - "Fazer o hook Stop enxergar o rastro exigir replicar dentro dele a regra de veredito do `harness budget` (limites, escalada, próximo passo) — pare: o hook enuncia o fato, quem julga é o comando"
  - "A nova regra de extração da linha de erro precisar de uma lista de ruído por ferramenta (nome de biblioteca, nome de framework) para funcionar — pare: uma lista assim é infinita por construção e reabre o mesmo defeito a cada dependência nova do projeto-alvo"
  - "Bloquear glob posicional em verify_cmd derrubar a compilação de um contrato deste repositório que hoje compila — sinal de que a regra pegou caso legítimo, e alargar a exceção sem entender qual é esconde o defeito"
---

# Spec: o loop caro para de ser invisível

## Resumo executivo

Uma sessão real do harness repetiu o mesmo comando de teste dezenas de vezes
esperando resultado diferente. Foram três fases: dezesseis execuções idênticas,
depois mais sete, até alguém perceber que o comando estava errado desde o
começo. O harness tinha as peças para interromper isso — grava um rastro de
tentativas e sabe dizer "você já tentou isso" — e mesmo assim não interrompeu.

Três motivos, todos confirmados na sessão que quebrou. O rastro anotava a linha
errada: capturava o primeiro aviso que a ferramenta imprimia, não o erro, e por
isso trinta e uma tentativas ficaram com a mesma assinatura mesmo quando a causa
da falha mudou. O aviso de fim de sessão mandava tentar de novo sem nunca olhar
o rastro que o próprio harness escrevia. E o comando de teste que originou tudo
— um caminho com curinga passado direto para o programa — foi aceito na hora de
aprovar o contrato, embora seja comprovadamente quebrado.

Depois desta demanda, o rastro passa a anotar o erro de verdade; o aviso de fim
de sessão diz quantas vezes aquilo já falhou e desde quando é a mesma falha,
antes de mandar tentar de novo; e um comando de teste comprovadamente quebrado
não vira contrato aprovado. Junto vão duas correções pequenas da mesma família:
o harness passa a reconhecer o runner de teste do projeto que quebrou, e o
agente aprende a deixar pronto, num arquivo, o ajuste de governança que ele
próprio não tem permissão para aplicar.

## Escopo

A demanda nasceu de uso real, com custo medido. As evidências abaixo vieram da
sessão que quebrou e do código deste repositório; cada item nomeia as duas.

**1. O rastro de tentativas anota a linha errada.**
`extract_failure_line` (`src/harness/attempts.py:146`) devolve a primeira linha
não-vazia do stderr. O docstring promete "primeira linha ÚTIL", mas a função não
filtra utilidade nenhuma — só não-vazio. Qualquer ferramenta que emita um aviso
antes do erro envenena a assinatura de todas as tentativas. Foi o que houve: um
`console.warn` de biblioteca de roteamento saía primeiro no stream e venceu a
corrida em 30 de 31 tentativas, congelando `failure_signature` em
`7c767f466985` mesmo quando a causa real mudou de "o curinga não resolve" para
"erro de tipagem". Consequência: `harness budget` compara hashes de avisos, não
de erros — o disjuntor existe e está cego.

A regra nova, decidida no gate desta demanda: varrer procurando a primeira linha
que **pareça erro**, e só então cair no comportamento atual. Sem lista de ruído
por ferramenta (ver stop conditions — é o desenho que já falhou uma vez).

**2. O aviso de fim de sessão não olha o rastro.**
`build_feedback` (`src/harness/stop_hook.py:258`) monta "Feature(s) em progresso
sem verificacao atualizada: T-XX. Rode `harness verify <id>`" e não tem como
saber que já mandou isso vinte vezes. As peças existem e estão desligadas:
`src/harness/attempts.py` grava falhas consecutivas e assinatura,
`harness budget` (`src/harness/budget.py:203`) emite
`continue`/`stop_same_failure`/`stop_iterations`. Grep por
`attempts|consecutive|budget` em `stop_hook.py` devolve zero. A sessão que
quebrou confirmou o efeito por escrito: *"nunca consultei `harness.cli budget`
durante o loop — só reagi ao stop hook repetindo o comando."*

O hook gerado é standalone e stdlib-only (`src/harness/stop_hook.py:155-164`,
não importa `harness`). A decisão **D-010** já resolveu essa fronteira para a
statusline: o arquivo gerado repete a **leitura** magra, nunca a **regra de
decisão**. Aplicando aqui: o hook lê o `.jsonl` do rastro com stdlib pura e
**enuncia o fato** — quantas tentativas, desde quando é a mesma assinatura — e
aponta `harness budget` para o veredito. Ele não calcula limite, não decide
escalada, não diz "pare".

**3. Comando de teste com curinga posicional é aceito.**
`pnpm test src/**/*.test.ts` foi para o subprocess do harness como argumento
literal — subprocess não expande curinga como um shell POSIX faria, e o runner
leu como filtro literal, achando zero arquivos. Existe `_dry_check_verify_cmd`
(`src/harness/contract.py:640`), mas só roda atrás da flag opcional
`--dry-run-verify` (`skills/plan/SKILL.md:122`), e o aviso sai em stderr sem
bloquear. Foi exatamente o que aconteceu: o aviso não impediu três fases de
loop.

Decidido no gate: curinga em argumento **posicional** derruba
`compile-contract` com exit 1 e mensagem que nomeia o comando, o argumento e a
saída. Curinga **dentro de flag** (`--include=**/*.spec.ts`, que o Angular
expande sozinho) continua passando — não é o caso quebrado.

**4. O detector de "zero testes coletados" é cego para o runner do projeto.**
`src/harness/skips.py:67-81` cobre pytest, dotnet, jest e go. Não cobre vitest.
E o padrão de jest (`\bNo tests found\b`) **não casa** a saída real observada,
`No test files found, exiting with code 1` — a palavra `files` no meio quebra o
match.

**5. O agente descreve a edição de governança em vez de deixá-la pronta.**
A mensagem de deny do plano de controle (`src/harness/boundary_guard.py:2724`)
estava correta e o bloqueio permanece intacto — a sessão que quebrou confirmou:
*"foi clara e nunca sugeriu scratch/ — eu deveria ter oferecido preparar o
arquivo corrigido em `.harness/scratch/` pra você copiar, em vez de só descrever
a edição em texto."* É o mesmo padrão já aprovado em
`.harness/work/atritos-do-ciclo/spec.md:64-84`: o floor permanece, e o deny
passa a nomear uma terceira saída — dizendo explicitamente que ela não é do
agente.

Fronteira que esta demanda precisa fechar, levantada na avaliação: hoje
`.harness/scratch/**` é declarado como área de *artefato temporário de
verificação* (`README.md:123-129`, `src/harness/boundary_guard.py:2749`). Usá-la
como canal de proposta de governança amplia o propósito declarado. A demanda
declara a ampliação em vez de fazê-la em silêncio: scratch passa a ser o lugar
do **artefato que o agente prepara para o humano** — verificação, e proposta de
edição que o agente não pode aplicar. O que **não** muda: nada em scratch é
aplicado por ninguém automaticamente, e o agente continua sem permissão de
escrever em `.harness/harness.yaml` por qualquer caminho.

## Critérios de aceitação

- A extração da linha de falha prefere a linha que parece erro à primeira linha
  não-vazia: dado um stderr que começa com aviso e traz o erro depois, a linha
  devolvida é a do erro; sem nenhuma linha que pareça erro, o comportamento
  atual (primeira não-vazia) permanece; sem saída nenhuma, continua string
  vazia. Prova: `pytest tests/test_attempts.py -q`
- Duas falhas com avisos iniciais iguais e erros finais diferentes produzem
  assinaturas DIFERENTES — que é o defeito exato observado. Prova:
  `pytest tests/test_attempts.py -q`
- O hook Stop, quando há rastro de tentativas para a feature pendente, inclui no
  aviso quantas tentativas já houve e há quantas a assinatura é a mesma, e cita
  `harness budget` como o comando do veredito; sem rastro, o texto permanece o
  de hoje. Prova: `pytest tests/test_stop_hook.py -q`
- O arquivo de hook GERADO (não uma cópia da lógica) produz esse texto quando
  executado por subprocess com um rastro no disco, e não importa o pacote
  `harness`. Prova: `pytest tests/test_stop_hook.py -q`
- `compile-contract` sai com exit 1 quando algum `verify_cmd` tem curinga em
  argumento posicional, e a mensagem nomeia a tarefa, o comando e o argumento
  ofensor; `verify_cmd` com curinga dentro de flag (`--include=...`) compila
  normalmente. Prova: `pytest tests/test_contract.py -q`
- A saída `No test files found, exiting with code 1` é reconhecida como zero
  testes coletados. Prova: `pytest tests/test_skips.py -q`
- O deny do plano de controle nomeia `.harness/scratch/` como o lugar de deixar
  a proposta de edição pronta para o humano, e diz que aplicá-la não é do
  agente; o AGENTS.md gerado ensina o mesmo gesto. Prova:
  `pytest tests/test_boundary_guard.py tests/test_lifecycle.py -q`

## Não-objetivos

- **Reprovar o verde sobre zero testes coletados.** O buraco existe no código
  (`src/harness/verify.py:532` relata em stderr e grava campo de evidência, mas
  nunca derruba o verde) e vale para runner que saia 0 com zero testes. Não
  entra: no caso observado o runner saiu 1 e o harness ficou vermelho
  corretamente. Sem evidência, não vira tarefa — fica registrado aqui para
  quando houver caso.
- **Separar `test_glob` de `verify_cmd` na entrevista do plan.** A premissa
  estava errada: `test_glob` não aparece no Passo 3 de `skills/plan/SKILL.md`,
  está no Passo 2.
- **Checar divergência entre `harness.yaml` e `repo-profile.json`.** Já
  entregue: `reconcile_test_glob` (`src/harness/profile_edit.py:149`) roda no
  `compile-session`, com a decisão registrada "a governança vence"
  (`src/harness/profile_edit.py:160`). Reabrir isso é re-litigar o achado F7 sem
  evidência nova.
- **Afrouxar o bloqueio de escrita em `.harness/harness.yaml`.** O floor
  permanece intacto. O que muda é o que a mensagem oferece e o que o agente
  aprende a fazer com o bloqueio — nunca quem pode escrever.
- **Fazer o hook Stop bloquear a sessão.** Ele continua devolvendo
  `additionalContext` e nunca `decision: "block"`.
- **Lista de ruído por ferramenta na extração da linha de erro.** Ver stop
  conditions: é o desenho que já falhou uma vez, e cada dependência nova do
  projeto-alvo reabriria o defeito.

## Unknowns

- Nenhum. O profile deste repositório saiu sem `unknowns[]`
  (`.harness/repo-profile.json`): python, pip, `pytest`, `tests/**/*.py`,
  `ruff check .` — todos com evidência em `pyproject.toml`/`tests/conftest.py`.
