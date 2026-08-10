---
slug: skips-nunca-silenciosos
approved_by: Daniel Seto
approved_at: 2026-08-10T21:00:00Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd na mesma tarefa"
  - "Detectar os motivos dos skips exigir alterar o verify_cmd do contrato — pare e escale: preservar o texto do contrato é garantia, não preferência"
  - "A suíte deste repositório ficar bloqueada pela T-04 sem que a chave de liberação do harness.yaml a destrave — sinal de que a liberação não funciona, e implementar em volta disso esconde o defeito"
  - "O parser de saída de runner precisar executar o verify_cmd mais de uma vez para decidir — o custo de rodar a suíte duas vezes é proibitivo e a decisão precisa sair da mesma execução"
---

# Spec: nenhum teste pulado passa despercebido

## Resumo executivo

Hoje o harness declara uma tarefa provada quando o comando de teste devolve
sucesso — e comandos de teste devolvem sucesso mesmo quando pularam metade
dos testes. Aconteceu na prática: uma variável de ambiente deixou de estar
setada no meio do trabalho, dezenas de testes pularam em silêncio, e o harness
carimbou a prova de que estava tudo verificado. Ninguém foi avisado.

Depois desta demanda, todo teste pulado aparece. Os que já eram conhecidos e
aprovados continuam passando sem atrito; um teste que começa a pular do nada
para o trabalho e diz o que pulou; e um que pulou porque falta algo do lado de
fora do código — variável de ambiente, credencial, ferramenta não instalada —
para o trabalho já na primeira vez e nomeia o que falta, porque isso não é
código errado, é ambiente incompleto.

Junto vai uma correção de fundo na mesma família: o arquivo de configuração do
harness passa a listar todas as opções que ele aceita, com os valores padrão.
Hoje ele mostra pouco mais da metade, e quem quiser mudar o resto precisa ler
o código-fonte para descobrir que a opção existe.

## Escopo

### O problema, com evidência

`run_verify` decide o verde exclusivamente pelo código de saída do processo
(`src/harness/verify.py:596-597` — `if returncode == 0: break`). Nenhuma linha
do caminho verde olha para o que o runner imprimiu. A prova gravada logo em
seguida (`src/harness/verify.py:647-665`) registra `exit_code`, `verify_cmd`,
`files_hash` e mais nada — não há como, olhando a evidência depois, saber se a
suíte rodou inteira ou pulou tudo.

`pytest`, `dotnet test` e `jest` saem todos com 0 nessa situação. O resultado
observado pelo usuário rodando o harness sobre vários projetos: evidência
carimbada e `passes: true` sobre uma suíte que em boa parte não executou.

Isto é exatamente o modo de falha descrito na §8.3 do design
(`docs/reference/loop-engineering-design.md:307-317`): *"A mais perigosa,
porque não gera feedback no loop — gera silêncio. O agente continua
'funcionando' sem as garantias que acha que tem."*

### O segundo problema, da mesma família

`.harness/harness.yaml` é escrito por um LLM copiando um template em prosa que
vive dentro de `skills/init/SKILL.md:39-62` — não por código. O schema real
(`src/harness/config.py`) tem 11 chaves; o template menciona 6, mais uma
comentada. Nunca aparecem no arquivo gerado:

| chave ausente do template | definição |
| --- | --- |
| `governance.protected_branches` | `src/harness/config.py:38` |
| `governance.branch_per_contract` | `src/harness/config.py:34` |
| `governance.budget.max_tokens_per_session` | `src/harness/config.py:18` |
| `governance.budget.max_green_iterations` | `src/harness/config.py:20` |

As duas primeiras são as de maior consequência para quem usa: uma decide em
que branches o `git commit` é negado, a outra faz a ferramenta trocar de branch
sozinha. Para descobrir que existem, hoje, o usuário lê Python.

Esta correção está NESTA demanda, e não numa separada, porque a liberação de
skip acionável da T-04 mora justamente no `harness.yaml`. Acrescentar uma chave
nova a um arquivo cujo formato o usuário precisa adivinhar reproduziria o
problema que esta demanda existe para consertar — silêncio, mudando só de
superfície.

### Decisões registradas

Estas cinco vieram do laudo do `/harness-creator:assess`, que apontou os furos,
e foram decididas pelo humano antes da escrita deste contrato. Não são
unknowns.

**1. O baseline nasce de comando explícito, nunca do primeiro verify.**
Nada no fluxo roda a suíte antes da aprovação do contrato — e a decisão D-007
(`.harness/decisions.md`) proíbe exatamente isso no health check, porque um
check que custa uma suíte inteira vira opcional na prática. Sobrava "o primeiro
verify vira baseline", que carimbaria como conhecido justamente o skip que
apareceu no meio do processo: o dano original, com um passo a mais. Portanto o
baseline é gravado por um comando que o humano roda de propósito, depois de
olhar a lista. `harness verify` só compara, nunca escreve baseline.

**2. A identidade de um skip é o par `(nodeid, reason)`.**
Só `nodeid` faria renomear um teste virar bloqueio sem regressão nenhuma; só
`reason` faria dois testes distintos com a mesma frase colapsarem num item, e
aí um skip novo passaria mudo — que é o dano original. Com o par, mudar o texto
do motivo também conta como skip novo, porque motivo diferente é condição
diferente. Renomear um teste bloqueia uma vez e custa uma linha de aprovação;
a assimetria é intencional e está declarada.

**3. O harness NUNCA altera o `verify_cmd` do contrato para obter mais informação.**
`src/harness/verify.py:574-577` garante que o texto do contrato é preservado
intacto e que só o head do comando é normalizado. Acrescentar `-rs` ao pytest
para arrancar os motivos quebraria essa garantia, e o campo `verify_cmd` da
evidência deixaria de descrever o que de fato rodou. Consequência aceita: com
`-q` — que é o que os `verify_cmd` deste repositório usam
(`src/harness/contract.py:97,106`) — o pytest imprime a CONTAGEM de skips mas
não os motivos. Quando houver skip sem motivo visível, isso em si é o sinal: o
harness relata que há N skips sem motivo legível e diz que acrescentar `-rs` ao
`verify_cmd` do contrato os revela. Quem edita o comando é o humano, no
contrato.

**4. A liberação de skip acionável persiste no `harness.yaml`, nunca no contrato.**
O `reason` de `tests/test_integration_minimumapi.py:27` é literalmente
`"fixture externa ... não encontrada"`, que casa a lista de palavras do
classificador da T-04. Se a liberação vivesse no contrato, o humano reaprovaria
esse mesmo skip legítimo em todo contrato futuro — e aprovação repetida é
precisamente como um gate perde efeito e vira carimbo. No `harness.yaml`, que é
config versionada, os skips legítimos deste repositório se declaram uma vez.

**5. Classificar por texto foi rejeitado antes; aqui é aceito, e o contraste fica registrado.**
`.harness/work/falha-transiente-e-escalada/spec.md:75-94` declarou NÃO-OBJETIVO
a detecção de flake por assinatura, porque *"não existe como distinguir isso de
um bug real só pela linha de erro"*. A T-04 usa a mesma técnica — classificador
de texto sobre saída de runner — e o contraste precisa estar escrito para não
ser re-litigado: lá o insumo era a linha de erro de uma falha, texto acidental e
variável; aqui o insumo é o `reason` de um skip, que é texto autoral, escrito
por quem escreveu o teste, e estável entre execuções. Além disso o custo do erro
é assimétrico e assumido: classificar como acionável um skip que era de
plataforma custa uma linha no `harness.yaml`; deixar passar um skip por env var
ausente é o dano que originou esta demanda.

### Correção de escopo herdada do assess

O sub-escopo "zero testes coletados" foi REDUZIDO depois de medição: `pytest`
sai com **5**, não 0, quando nenhum teste é coletado (`no tests ran`). Para o
runner deste repositório o caso já é vermelho hoje. A cegueira permanece para
`dotnet test` e para `jest --passWithNoTests`. Fica tratado como um caso do
parser dentro da T-01, não como tarefa própria.

### Restrição dura de contexto

`src/harness/verify.py:298-301` declara anti-objetivo explícito: *"com
streaming incondicional, toda a saída da suíte entraria no contexto do agente a
cada verify verde — anti-objetivo (economia de contexto)"*. Todo relato desta
demanda — no console (T-01) e na evidência (T-05) — é RESUMO com teto de
tamanho. Despejar o bloco de skips viola o anti-objetivo e não é aceitável como
implementação.

### Casos de teste reais dentro deste repositório

A suíte deste próprio repositório tem dois skips legítimos, que precisam
continuar passando depois de tudo isto e servem de caso real:

- `tests/test_verify.py:663` — `skipif(not _is_windows())`, motivo
  `"normalização só se aplica ao cmd.exe"`.
- `tests/test_integration_minimumapi.py:26` — fixture externa, motivo
  `"fixture externa ... não encontrada"` (o que casa o classificador da T-04, de
  propósito: é o caso que prova que a liberação do `harness.yaml` funciona).

## Critérios de aceitação

- O parser reconhece skips e o caso de zero testes coletados na saída de pytest,
  `dotnet test`, jest e go, por padrão de texto, sem presumir runner —
  `pytest tests/test_skips.py -q`
- `harness verify` relata contagem de skips em toda execução, verde ou vermelho,
  sem flag; o relato tem teto de tamanho e, quando os motivos não estão visíveis
  na saída, diz isso e indica acrescentar `-rs` ao `verify_cmd` do contrato —
  `pytest tests/test_verify_skips.py -q`
- Existe comando explícito que roda a suíte, mostra os skips ao humano e grava o
  baseline; `harness verify` nunca escreve baseline —
  `pytest tests/test_skips_baseline.py -q`
- Skip presente na execução e ausente do baseline derruba o verify pelo mesmo
  caminho do vermelho de hoje (nada gravado em disco, classificação structural);
  skip já no baseline passa mudo; skip que sumiu só informa; a identidade é o par
  `(nodeid, reason)` — `pytest tests/test_skips_delta.py -q`
- Skip cujo motivo indica falta de ação do usuário bloqueia na primeira execução,
  sem esperar delta, com veredito INFRA nomeando o que falta; a liberação lida de
  `verification.allowed_skips` do `harness.yaml` destrava os dois skips legítimos
  deste repositório — `pytest tests/test_skips_actionable.py -q`
- A evidência gravada contém o resumo de skips, com teto de tamanho —
  `pytest tests/test_skips_evidence.py -q`
- O `harness.yaml` é gerado por código a partir de `HarnessConfig`, com toda
  chave do schema presente e comentada; o teste importa `HarnessConfig.model_fields`
  e falha se qualquer chave ficar de fora — `pytest tests/test_config_template.py -q`
- As contagens derivadas na documentação (subcomandos do CLI, módulos do pacote)
  continuam batendo com o código depois do módulo e do verbo novos —
  `pytest tests/test_docs_derived_facts.py -q`

## Não-objetivos

- **Fazer o harness rodar a suíte por conta própria em qualquer momento fora do
  `verify_cmd`.** O baseline (T-02) roda a suíte porque o humano pediu, com um
  comando explícito. Nada nesta demanda executa suíte na abertura de sessão nem
  no health check — D-007 já decidiu isso, e o motivo (check caro vira opcional)
  não mudou.
- **Alterar o `verify_cmd` do contrato para arrancar mais informação do runner.**
  Decisão registrada nº 3 acima. Se os motivos não aparecem, o harness diz que
  não aparecem; quem muda o comando é o humano.
- **Classificar teste com falha (não pulado) por texto do erro.** Continua
  NÃO-OBJETIVO, como `.harness/work/falha-transiente-e-escalada/spec.md:75-94`
  decidiu. Esta demanda toca só o texto de `reason` de skip.
- **Detectar teste que "passou mas não deveria" (asserção vazia, teste tautológico).**
  É outro modo de falha, precisa de outra técnica, e misturar os dois faria as
  duas coisas mal.
- **Bloquear todo skip.** A restrição conhecida é dura: a suíte deste repositório
  tem skips legítimos, e tratar todo skip como falha quebra o próprio harness.
- **Migrar `.harness/harness.yaml` de projetos já existentes para o formato
  completo da T-06.** A T-06 muda o que é GERADO daqui em diante; reescrever
  arquivos já em disco em projetos governados é mudança de outra natureza, com
  risco de sobrescrever ajuste manual do dono do repo.

## Unknowns

- Nenhum. O `analyze` deste repositório devolveu `unknowns: []`
  (`.harness/repo-profile.json`), e as cinco perguntas abertas pelo
  `/harness-creator:assess` foram respondidas pelo humano e estão registradas
  acima como decisões.
