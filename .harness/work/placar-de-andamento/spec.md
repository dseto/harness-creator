---
slug: placar-de-andamento
approved_by: Daniel Seto
approved_at: 2026-08-10T02:34:00Z
stop_conditions:
  - "2 tentativas de correção estrutural seguidas na MESMA falha, fora do retry transiente"
  - "qualquer mudança sair da camada de apresentação — tocar veredito, gate, disjuntor ou fluxo de aprovação — parar e escalar"
---

# Spec: Placar de andamento — o loop legível para quem só quer o resultado

## Resumo executivo
Hoje, durante a implementação, o desenvolvedor vê tool calls passando mas
ninguém responde as quatro perguntas básicas: **onde estou** (qual tarefa de
quantas), **o que está sendo feito agora**, **está indo bem** (tentativa
quantas de quantas, última prova passou?), e **o que vem a seguir**. Quem não
domina os conceitos de harness engineering fica sem leitura nenhuma do
andamento.

Este contrato cria o placar de andamento em três renders da MESMA fonte de
dados (nada de dado novo — só apresentação do que já existe em
`feature_list.json`, `attempts/`, `evidence/` e no rastro de métrica):

1. **`harness status --brief`** — bloco compacto para o agente colar no chat
   a cada iteração: barra de progresso unicode, lista de tarefas com estado,
   última prova (e o erro exato quando falhou), sparkline da métrica de
   convergência quando houver, e o próximo passo. Montado por código —
   o agente cola, nunca redige, então o placar não mente.
2. **`harness status --panel` no terminal** — o mesmo painel com cor ANSI
   (verde/vermelho/âmbar) e `--watch N` para re-renderizar sozinho num
   segundo terminal, estilo `htop`.
3. **Statusline do Claude Code** — uma linha sempre visível na barra do CLI:
   demanda, progresso, tarefa atual, tentativa, último veredito.

E uma quarta frente só de texto: as mensagens que o harness já emite para o
humano (escalada, finish, vereditos do disjuntor) passam a falar **resultado**
("a prova falhou: AssertionError…", "mesmo erro 3 vezes — trocando de
estratégia") em vez de jargão de mecanismo, mantendo o stdout JSON intacto
para máquina.

## Escopo
Camada de apresentação, ponta a ponta. Nenhum gate, veredito, disjuntor ou
fluxo muda de comportamento — mudam os RENDERS e os TEXTOS.

**Painel (`panel.py`, novo).** Monta o placar a partir do estado real:
tarefas prontas/total, tarefa em andamento (descrição funcional, não só o
id), tentativa atual vs teto do disjuntor, veredito e primeira linha do erro
da última prova, trajetória da métrica (série recente + melhor + alvo) quando
a tarefa tem `metric_cmd`, próximo passo derivado do estado (prova vermelha →
"corrigir e re-rodar", verde → "registrar evidência", etc.), e o estado do
kill-switch que o `harness status` de hoje já mostra. Render puro: consome as
funções de leitura que já existem (`attempts.summarize`,
`convergence.summarize_trajectory`, `supervisor.dispatch_next`,
`budget.check_budget`, `killswitch.status`) e não escreve nada em disco.

**Superfície de saída do `status` (regra dura).** `harness status` sem flag
continua imprimindo o MESMO JSON no stdout de hoje, byte por byte: é a fonte
de verdade estruturada declarada em `session_start.py` (o aviso de
kill-switch aponta o comando para isso) e o que a issue #52 estabeleceu como
único lugar que conta a verdade sobre o harness desligado. O placar entra por
flag: `--brief` (markdown + unicode + emoji, sem ANSI — o chat do Claude Code
não renderiza ANSI) e `--panel` (ANSI só quando stdout é TTY; em pipe sai
texto puro). `--watch N` implica `--panel` e re-renderiza a cada N segundos.
`--brief` e `--panel` juntos é erro de uso.

**Statusline (`statusline.py`, novo + `cli.py`).** O `compile-session` passa
a chamar `install_statusline(target_dir)` — mesmo padrão de
`install_session_start`/`install_stop_hook`: grava
`.harness/hooks/statusline.py` (lê os mesmos arquivos e imprime UMA linha),
registra a entrada `statusLine` no settings machine-local via
`prepare_managed_settings`/`write_managed_settings`, com o interpretador
ABSOLUTO bakeado por `hook_launcher.hook_command`, e guarda o comando em
`.harness/compiled-state-session.json` para que recompilar não duplique nem
deixe entrada órfã. Não entra em `compiler.py`: aquele módulo hoje não gera
hook nenhum (`hook_files`/`hook_entries` saem vazios desde a onda 3), e cada
hook do harness mora no seu próprio módulo com o seu `install_`.

O Claude Code entrega ao comando de statusline um JSON no stdin com dados da
própria sessão (custo acumulado, contexto); quando presentes, a linha mostra
também o custo — é render de dado que o CLI já empurra, não coleta. Campo
ausente ou stdin vazio → a linha sai sem custo, nunca quebra.

**Lifecycle (`lifecycle.py`).** Instrução nova: na abertura de cada iteração
(antes de rodar a prova), na transição de fatia e em qualquer parada, o
agente roda `harness status --brief` e cola a saída no chat, como está.
Proibição explícita de redigir o placar de cabeça — placar auto-relatado é
self-report, e o repositório já estabeleceu que self-report não vale.

**Vocabulário de resultado (`escalation.py`, `finish.py`, `budget.py`).** O
canal humano é o **stderr** (é como `harness budget` já separa: JSON no
stdout, bloco de escalada no stderr). Nesse canal, jargão vira resultado:
"fatia/contrato" → "tarefa N de M / plano aprovado", "verify_cmd
verde/vermelho" → "a prova passou/falhou (+ o que falhou)",
`stop_same_failure` → "o mesmo erro se repetiu 3 vezes: a abordagem está
errada, não a execução", `stop_plateau` → "3 medições sem melhora: girando em
falso". `harness finish` hoje não tem canal humano nenhum (só JSON): ganha um
— resumo em stderr do que fechou e, quando há `blockers`, o que exatamente
falta em linguagem de resultado. O stdout JSON dos três comandos permanece
byte-idêntico ao atual.

**Documentação do plugin (`TUTORIAL.md`, `GUIDE.md`, `ARCHITECTURE.md`).** O
placar precisa existir onde o humano procura o que a ferramenta faz, não só
no `README.md`: o tutorial ganha os três renders no material de comando e a
statusline na tabela de artefatos gerados; o guia, a distinção entre `harness
status` (JSON, kill-switch) e o placar opt-in; a arquitetura, `panel.py` e
`statusline.py` na tabela de camadas e a statusline no mapa de hooks. A
**Versão e CHANGELOG (`v0.34.0`).** Por decisão explícita do humano nesta
demanda, o bump entra no PR em vez de ficar como chore posterior na `main`: as
três fontes manuais (`__init__.py`, `plugin.json`, `marketplace.json`), os
marcadores de versão da documentação que `test_version_sync` enumera, e a
entrada de CHANGELOG descrevendo o placar.

## Critérios de aceitação
- `harness status --brief` imprime o placar com progresso X/N, lista de
  tarefas com estado, tarefa atual com tentativa n/teto, última prova com a
  primeira linha do erro quando falhou, e próximo passo — tudo derivado dos
  arquivos de estado, sem ANSI — `pytest tests/test_panel.py -q`
- Tarefa com rastro de métrica mostra série recente, melhor valor e alvo no
  placar; sem rastro, a linha não aparece — `pytest tests/test_panel.py -q`
- `harness status` SEM flag imprime no stdout o mesmo JSON de hoje (chaves
  `disabled`, `sentinel`, `friction` e o aviso de governança parcial quando
  aplicável), sem uma linha de painel; `--brief` e `--panel` juntos saem com
  erro de uso — `pytest tests/test_panel.py -q`
- `harness status --panel` usa ANSI apenas quando stdout é TTY; com stdout em
  pipe a saída é texto puro; `--watch N` re-renderiza no intervalo pedido —
  `pytest tests/test_panel.py -q`
- `compile-session` grava `.harness/hooks/statusline.py` (uma linha: demanda,
  progresso, tarefa, tentativa, último veredito, e o custo da sessão quando o
  stdin do Claude Code o fornecer; sem o campo, a linha sai sem custo) e
  registra a entrada `statusLine` no settings machine-local com interpretador
  absoluto; recompilar duas vezes não duplica nem deixa entrada órfã —
  `pytest tests/test_statusline.py -q`
- O lifecycle instrui colar `harness status --brief` na abertura de cada
  iteração, na transição de fatia e em parada, e proíbe redigir placar de
  cabeça — `pytest tests/test_lifecycle.py -q`
- `TUTORIAL.md`, `GUIDE.md` e `ARCHITECTURE.md` documentam os três renders do
  placar (`--brief`, `--panel`/`--watch`, statusline), a statusline entra na
  tabela de artefatos gerados do tutorial e no mapa de hooks da arquitetura, e
  `panel.py`/`statusline.py` entram na tabela de módulos —
  `pytest tests/test_docs_placar.py -q`
- `.harness/attempts/` é tratado como artefato gerenciado do harness: o rastro
  de tentativas sujo não vira `tree_residue` em `harness finish` nem impede a
  criação da branch do contrato, do mesmo modo que a evidência e o veredito
  cego já não impedem — `pytest tests/test_branching.py -q`
- A versão sobe para v0.34.0 nas três fontes manuais (`__init__.py`,
  `plugin.json`, `marketplace.json`) e em todos os marcadores de versão da
  documentação, com a entrada de CHANGELOG do placar —
  `pytest tests/test_version_sync.py -q`
- Canal humano (stderr) de escalada, finish e disjuntor fala resultado (sem
  `verify_cmd`/slug/veredito cru sem tradução) e `finish` passa a ter esse
  canal; o stdout JSON dos três permanece byte-idêntico ao atual —
  `pytest tests/test_escalation.py tests/test_finish.py tests/test_budget.py -q`

**Rastro de tentativas não é resíduo (achado do próprio dogfood).** Fechar
esta demanda esbarrou num defeito que ela mesma expôs: `.harness/attempts/` não
está entre os prefixos que o harness reconhece como artefato SEU
(`branching.HARNESS_MANAGED_PREFIXES` isenta `.harness/evidence/` e
`.harness/blind-review/`, e para aí). Depois do primeiro commit de uma demanda,
qualquer `harness verify` seguinte suja um arquivo tracked que o `finish` passa
a chamar de "trabalho de outro contexto" — e `harness task add-file` recusa
`.harness/**`, corretamente. Toda demanda longa trava no fecho pelo rastro que
o próprio harness escreve.

Isto TOCA o gate de fecho, ou seja, cai na stop condition deste contrato: foi
escalado e autorizado explicitamente pelo humano antes de qualquer linha ser
escrita. O escopo é uma entrada na tupla e o teste que a fixa — nenhuma regra
de decisão do `finish` muda.

## Não-objetivos
- **Painel HTML / navegador** — fora do primeiro corte; os três renders de
  terminal cobrem a dor. Se sobrar dor visual, vira contrato próprio.
- **Daemon, servidor ou processo residente** — `--watch` é um loop de
  re-render no terminal do DEV, nada roda sozinho em background.
- **Narração por tool call** — a cadência é fronteira de iteração, transição
  de fatia e parada. Placar a cada tool call é ruído que mata o sinal.
- **Dado novo** — o placar é render puro do que já existe. Nenhum arquivo de
  estado novo, nenhum campo novo no contrato, nenhum hook de coleta.
- **Trocar a saída default de `harness status`** — o JSON do stdout é
  consumido como estado estruturado e não muda; o painel é opt-in por flag.
- **Consumo de tokens por tarefa/demanda no placar** — exige o medidor da
  Fase 6 do roadmap (ledger + PostToolUse lendo o transcript), que é COLETA.
  Fica declarado como slot: quando o ledger existir, o painel ganha a linha.
  O que entra agora é só o custo de sessão na statusline, que o Claude Code
  já fornece pronto no stdin.
- **Mudança de comportamento em gate/veredito/fluxo** — se uma melhoria de
  texto exigir mudar lógica, ela sai deste contrato (stop condition).
- **ANSI no canal do chat** — o chat renderiza markdown, não ANSI; o
  `--brief` nunca emite escape codes.

## Unknowns
- O formato exato da entrada `statusLine` no settings do Claude Code
  (nome da chave, forma do `command`, encoding no Windows) e o schema do JSON
  que o CLI entrega no stdin (nome exato dos campos de custo/contexto) devem
  ser confirmados contra a documentação oficial no momento da implementação —
  mesmo padrão de verificação que o repo já usou para os schemas de hook.
  Campo que a doc não confirmar entra como opcional-silencioso, nunca como
  dependência.
