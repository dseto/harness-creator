# Parecer MAR — backlog de correção de fricção vs objetivo do harness-creator

## Proveniência

- **Origem:** comitê MAR (Multi-Agent Reflexion), skill `entebate`, pipeline
  `objetivo_x_proposta` (personas cegas Verificador / Cético / Lógico +
  síntese do Juiz).
- **Data:** 2026-07-26.
- **Alvo avaliado:** `docs/project/ROADMAP-dogfood-venv-windows.correction.backlog.md`
  (backlog de correção de fricção do dogfood venv-Windows,
  repo Python com venv no Windows, atrás de proxy corporativo).
- **Critério do usuário, literal:** verificar se as sugestões *"atendem o
  objetivo de flexibilizar o harness-creator para o desenvolvimento não ter
  fricção desnecessária, mas sem perder o objetivo do harness"*.
- **Notas do comitê:** tentativa 1 — Verificador 3 · Cético 2 · Lógico 3 ⇒
  `nota_final` 2, **REESCREVER**. Tentativa 2 — Verificador 4 · Cético 3 ·
  Lógico 4 ⇒ `nota_final` 4, **APROVADO** (amplitude 1, sem rodada extra de
  debate). Este documento é o rascunho v2 aprovado **com as correções
  residuais do consenso já aplicadas**.
- **Trilha completa** (avaliações cegas por persona, consenso do Juiz, pedido
  congelado e rascunhos):
  `…\Temp\claude\C--Projetos-Harness-creator\c6e212b7-7cdd-4d89-bbc4-a9b46fd246a4\scratchpad\mar\etapa_objetivo_x_proposta`.

## Resumo — veredicto por unidade

| Unidade | Veredicto | Razão em uma linha |
|---|---|---|
| **U1** — hooks com `python` nu (fail-open silencioso) | `adaptar` | Bake + check no `doctor` não fecha o fail-open; exige lançador que saia com **exit 2**. |
| **U2** — preflight verifica resolubilidade do comando inferido | `adaptar` | Desfechos WARNING/PASS estão certos, mas executar string de repo cru é custo de eixo B não contabilizado; resolver o token-cabeça no shell-alvo em vez de executar. |
| **U3** — allowlist lida em runtime (fim do bake) | `adaptar` | Remove um passo cerimonial, mas dois parsers divergentes devolvem parte do eixo A como fricção silenciosa; validar a sublista no `compile-session`. |
| **U4** — normalização da forma de invocação | `adaptar` | Maior volume de eixo A, mas o floor deixa de ser literalmente incondicional e `uv run --with` traz rede sem aprovação; muda o fluxo de avaliação, logo não é `implementar`. |
| **U5** — mensagens de deny apontando o escape barato | `implementar` | Mata um ciclo documentado com esforço S sem mover nenhuma regra de guard, floor ou contrato. |
| **U6** — `harness profile set <chave> <valor>` | `implementar` | Troca ambiental deixa de custar um ciclo; enumeração fechada e recusa de `test_glob` mantêm a fronteira ambiente/governança. |
| **U7** — escapes e cmdlets read-only no PowerShell | `adaptar` | Recupera o único caminho que enxerga o venv Windows, mas predicados portados e allowlist aprovada por analogia não estabelecem o eixo B; rederivar. |
| **U8** — emitir `Bash(verify_cmd)` **e** `Bash(verify_cmd:*)` | `implementar` | Tira fadiga de prompt sem mover o que o guard decide; o caso de teste de floor já está declarado dentro da proposta. |
| **U9** — `harness allow-command` na postura A | `rejeitar` (condicional) | Cria ampliação de superfície de **comando** sem gate humano e nenhuma adaptação restitui o gate — condicional à leitura declarada na unidade. |
| **U10** — decisão de postura A/B/C/D e recomendação D | `adaptar` | D depende de medição que **nenhuma** das 11 unidades instrumenta; instrumentar a contagem no lado da CLI. |
| **U11** — sequenciamento em ondas e gate de medição | `adaptar` | Critério de ordenação correto, aplicação erra ao adiar U5 (S, mata ciclo) para a onda 3. |

---

## Método

Cada uma das 11 unidades recebe um veredicto — `implementar` / `adaptar` /
`rejeitar` — com prós e contras **todos etiquetados** por eixo:

- **Eixo A — flexibilizar:** o item remove fricção que não compra governança
  nenhuma?
- **Eixo B — preservar:** o item mantém intacto o objetivo do harness
  (aprovação humana onde ela é o valor, disciplina TDD, floor incondicional,
  superfície de contrato)?

**Regra de rótulo** (uniforme nas 11 unidades):

- `implementar` = o item, **como proposto**, passa nos dois eixos; o que este
  parecer acrescenta são casos de teste, notas ou sugestões **não
  bloqueantes**.
- `adaptar` = o item, como proposto, **falha um eixo** a menos que o desenho
  mude; o parecer nomeia a mudança.
- `rejeitar` = **nenhuma** adaptação preserva os dois eixos.

**Regra eliminatória do pedido**, citada literalmente e resolvida em uma
frase ao final de cada unidade: *"Um item que só atende A (flexibiliza
corroendo governança) ou só atende B (preserva governança sem tirar fricção)
não passa."*

**Convenção de evidência.** Só afirmo o que o pedido contém. Onde infiro
comportamento não declarado, marco **[premissa]** e digo o que acontece com o
veredicto se a premissa cair — a condicionalidade não é descarregada em
obrigação incondicional mais adiante. Recomendações que não são uma das 11
unidades aparecem como **nota subordinada** à unidade correspondente ou na
seção final; **nenhum veredicto se apoia nelas**.

**Proveniência dos achados.** Os achados de código citados aqui são os que a
fonte **afirma ter verificado** — por leitura com `file:line` e/ou por
execução real do `boundary_guard` gerado do HEAD contra um repo sintético,
com payloads `PreToolUse` via stdin. Este parecer avalia o **texto** da
proposta contra o objetivo declarado do produto; **não executou o guard nem
leu o código por conta própria**. Onde uma tabela de execução sustenta um
veredicto — sobretudo em U4, U5 e U7 —, o que a sustenta é a declaração da
fonte, não verificação independente deste parecer.

**Dívida de método, declarada uma vez.** Cada "adaptação exigida" abaixo é
**uma** mudança suficiente para o item passar nos dois eixos, **não a única
mudança necessária**. Não submeti cada remédio proposto ao mesmo teste que
aplico explicitamente a U7 (*o remédio não pode reintroduzir o mal que o item
denuncia*); onde esse teste foi aplicado, está escrito na unidade. Vias
alternativas que produzam o mesmo efeito são admissíveis e não estão
excluídas por este parecer.

---

## U1 — Hooks com `python` nu (fail-open silencioso): **adaptar**

- **Pró (eixo B, decisivo):** o produto é "governança compilada para os
  mecanismos nativos"; um hook que não inicia entrega zero governança
  aparentando entregar cem. A fonte é explícita: apenas exit 2 bloqueia, logo
  interpretador irresolúvel ⇒ tool call passa sem floor, sem proteção de
  segredo, sem bloqueio de push e sem gate de evidência, com uma linha de
  `hook error` como única pista. Fechar isso é pré-condição de todo o eixo B.
- **Pró (eixo B):** a fonte também estabelece que não há correção possível de
  dentro do Python (declara que `boundary_guard.py:2232-2236` já é fail-closed
  internamente) — o diagnóstico da camada certa está correto, e `sys.executable`
  resolvido no `compile-session` é a âncora que aquele passo já tem.
  **[premissa]** que `sys.executable` no momento do `compile-session` seja o
  interpretador **correto** a bakear: a fonte propõe a captura, mas não declara
  sob qual Python o `compile-session` roda no projeto-alvo. Se a premissa cair,
  o bake pode fixar o interpretador errado — o que **não** afeta este veredicto,
  porque ele se apoia na exigência do lançador fail-closed, e não na eficácia do
  bake.
- **Pró (eixo A), somente sob a adaptação abaixo:** com um lançador
  fail-closed, o modo de falha deixa de ser silencioso e vira um deny legível.
  A própria fonte registra que *"não há evidência que permita afirmar nem
  descartar que ocorreu na sessão real"* — ou seja, hoje o custo é uma dúvida
  não resolúvel sobre todas as sessões passadas. Converter isso em sinal é
  fricção de diagnóstico removida. **Como proposto (bake + check no
  `doctor`), esse ganho de eixo A não existe**: o bake não fecha o fail-open,
  só muda a causa dele.
- **Contra (eixo B):** a detecção proposta é **pull**, não **push** — depende
  de alguém suspeitar e rodar `harness doctor`. E o modo de falha em que ela
  mais importa é justamente o que impede o `session_start` de rodar: o harness
  não tem como avisar por conta própria pelo mecanismo proposto. A
  equivalência que o item declara — mesmo fail-open de hoje, porém agora
  detectável por `harness doctor` em vez de silencioso — só vale para quem roda
  `doctor`.
- **Contra (eixo B):** bakear caminho absoluto pode **aumentar** a frequência
  do fail-open. Hoje ele exige PATH divergente ou stub da Microsoft Store;
  depois, basta recriar o venv — operação rotineira exatamente na população
  afetada (repo Python com venv). A fonte assume esse risco residual, mas o
  trata como equivalente ao de hoje, e ele não é: muda de acidente de
  configuração para consequência de uma operação corriqueira.
- **Contra (eixo A):** o mesmo risco residual cria um ciclo novo — recriou o
  venv, rode `compile-session` de novo. É fricção pequena, mas é fricção
  introduzida por um item cuja justificativa é eixo B.
- **Adaptação exigida:** um **lançador** (`.cmd`/wrapper gerado no
  `compile-session`) que resolve o interpretador e, **se não resolver, sai com
  exit 2** — o único código que bloqueia, conforme a doc que a própria fonte
  cita. Isso transforma fail-open em fail-closed de verdade. O bake de
  `sys.executable` permanece como caminho rápido de resolução e o check no
  `doctor.py` como detecção complementar; nenhum dos dois, sozinho, fecha o
  buraco.
- **Regra eliminatória:** como proposto, o item entrega eixo B e **nada** de
  eixo A — cai na hipótese "preserva governança sem tirar fricção" e não
  passa. Com o lançador fail-closed ele passa a entregar A (bypass silencioso
  vira deny legível) e sobrevive à regra. Daí `adaptar`, não `implementar`.

## U2 — Preflight verifica resolubilidade do comando inferido: **adaptar**

- **Pró (eixo A):** é — conforme a alegação de ROI **da própria proposta** —
  o único item que age **antes de o contrato existir**: os demais reduzem o
  custo de errar, este evita o erro. O fato que a fonte relata sustenta a
  alegação: o analyzer inferiu `pytest`, ninguém verificou que `pytest` nu não
  resolve sem ativar `.venv\Scripts`, o preflight devolveu **READY**, e o
  contrato nasceu com um `verify_cmd` que não executa.
- **Pró (eixo A):** a distinção declarada obrigatória — binário não resolve →
  **WARNING**, nunca FAIL; binário resolve mas o comando falha → **PASS**,
  porque suíte vermelha é o estado esperado em repo pré-TDD — é a leitura
  certa e é o que impede o check de virar ruído. Este é o miolo do item e não
  precisa de nenhum reparo.
- **Pró (eixo B):** WARNING nunca FAIL mantém o preflight como conselho e não
  como portão arbitrário; e o Actionable Fix nomeando as três formas
  candidatas detectadas em disco (`.venv/Scripts/<bin>`, `python -m <bin>`,
  `<bin>` nu) orienta sem mutar nada no repo avaliado.
- **Contra (eixo B), é o que força `adaptar`:** o mecanismo proposto executa,
  com `shell=True`, **uma string inferida do manifesto de um repositório
  cru**, no momento em que — **[premissa]** — **nenhuma governança está
  instalada**: a fonte declara que o item age *antes de o contrato existir* e
  que o preflight é o portão de entrada do ciclo, mas não descreve o estado de
  instalação do guard nesse instante. **[premissa]** Em Node, `npm test` roda o
  que o `package.json` mandar — comportamento do ecossistema, não afirmado pela
  fonte. É ampliação de superfície de execução no ponto de menor proteção do
  ciclo: um custo de eixo B que o item não contabiliza. **O veredicto `adaptar`
  se apoia neste contra**: se a primeira premissa cair (houver camada
  interceptando no momento do preflight), o contra perde peso e o item se
  aproxima de `implementar` — mas não desaparece, porque a string continua
  vindo de manifesto não auditado. Registre-se o peso correto: é custo não
  contabilizado, **não** quebra de contrato — a fonte não declara em nenhum
  ponto que o preflight seja read-only por promessa.
- **Contra (eixo A):** a via de resolução tem um fracasso já documentado pela
  fonte — *"sem `shell=True` todo shim `.cmd` do Windows dá falso 'não
  encontrado' — erro já cometido e corrigido antes"*. Qualquer adaptação que
  troque execução por resolução precisa responder a esse precedente, sob pena
  de reintroduzir falso negativo, que é ruído — a fricção que o item existe
  para matar.
- **Adaptação exigida:** preservar os dois desfechos (WARNING/PASS) e o
  Actionable Fix, e trocar o mecanismo por **resolução do token-cabeça no
  shell que o agente vai usar** — `where` / `Get-Command` / `command -v`
  invocados **no shell-alvo**. **[premissa]** que sejam esses os utilitários
  que tratam shim `.cmd` quando invocados de dentro do shell-alvo: a fonte só
  declara o precedente inverso (resolver **fora** do shell produziu falso "não
  encontrado"), não nomeia o utilitário correto. Sob essa premissa, a adaptação
  responde ao precedente: o problema anterior foi resolver fora do shell, não
  resolver em vez de executar. **[premissa]** que o token vindo do repo entre
  como **argumento** do resolvedor e nunca como comando executado — é o que
  mantém a regra que o contra enuncia, e é propriedade do desenho aqui
  proposto, não da fonte. Limitação declarada abertamente: essa via confirma o
  binário, **não** a presença do módulo em `python -m <mod>`, nem cobre
  `npm test`, que não tem `<bin>` único a resolver; nesses casos o check deve
  emitir WARNING informativo com as formas candidatas, sem fingir veredicto.
- **Regra eliminatória:** como proposto, o item entrega A com um custo de B
  não contabilizado ("flexibiliza corroendo governança") e não passa; com a
  resolução no shell-alvo ele entrega o mesmo sinal de A sem executar nada do
  repo cru, e passa nos dois eixos. Daí `adaptar`.

## U3 — Allowlist lida em runtime (fim do bake): **adaptar**

- **Pró (eixo A):** o argumento de custo é da própria fonte e é declarado como
  achado de leitura de código: o guard **já lê dois JSONs do disco a cada tool
  call**, então ler um terceiro arquivo é custo marginal nulo — o bake é
  acidente de implementação, não decisão de performance. Para o **usuário**
  editando o YAML no terminal próprio, a fonte declara que o ciclo cai de 3
  operações para 1, sem CLI nova e sem mudança de postura.
- **Pró (eixo A):** no ciclo relatado (`disable` → editar → `compile-session`
  → `enable`, quatro passos), o runtime-read remove o passo
  `compile-session` — que é o passo que existe apenas para propagar um dado
  que já está em disco.
- **Pró (eixo B):** nenhuma postura muda por si — quem podia editar o YAML
  continua sendo quem podia antes. E o fail-safe declarado é o correto:
  erro de leitura ou de parse **sempre reduz para vazio**, nunca amplia.
- **Contra (eixo A, invertido) — dois parsers criam um modo de divergência
  novo, e é este contra que sustenta o veredicto.** O parser mínimo é
  propositalmente burro (não entende aspas, flow style `[a, b]` nem comentário
  inline); o parser completo usado pelo `compile-session` entende. Resultado
  previsível: o usuário escreve `extra_allowed_commands: [ruff check, mypy]`,
  o compile aceita, o `settings.json` emite as regras, e o guard lê lista
  vazia e nega. O sintoma é *"declarei e continua negado"* — exatamente a
  classe de fricção opaca que este backlog existe para matar. O item trata a
  degradação como segura, e ela é; o que ele não trata é que **degradação
  segura ainda é fricção**, e fricção silenciosa é a pior espécie.
- **Contra (eixo B), condicional e não decisivo:** hoje o bake funciona como
  trava temporal — mesmo que alguém escreva no `harness.yaml`, a mudança só
  vale após um `compile-session`. Com runtime-read, a escrita passa a valer na
  tool call seguinte. **[premissa]** Este contra só tem força se (i) o deny de
  `Write .harness/harness.yaml` for por superfície de contrato e (ii)
  `harness task add-file` aceitar paths sob `.harness/` — nenhuma das duas
  coisas é declarada pela fonte. **Hipótese alternativa, igualmente aberta:**
  se o ciclo observado já inclui `compile-session`, a trava temporal **não
  tranca** quem consegue compilar; ela só vincula um ator que escreve o YAML e
  não pode compilar. Nesse caso U3 remove uma etapa cerimonial, não uma trava
  efetiva, e o contra desaparece. **E, decisivamente para o escopo:** se a
  rota `add-file .harness/…` existir, ela é furo **hoje**, independentemente
  de U3 — logo a trava incondicional de escrita em `.harness/` é assunto
  próprio, não condição deste item. Ver nota subordinada abaixo. **O veredicto
  `adaptar` não se apoia neste contra**; apoia-se no contra de divergência de
  parsers, que não depende de premissa nenhuma.
- **Adaptação exigida:** o `compile-session` valida a sublista
  `governance.extra_allowed_commands` contra a **gramática do parser mínimo** e
  falha ruidosamente (ou normaliza para bloco `- item`) quando o YAML usa
  sintaxe que o runtime não entende. Sem isso, o silêncio entre os dois
  parsers vira o próximo ciclo de tentativa-e-erro. A bateria declarada pelo
  próprio item (testar o parser burro contra YAML que ele NÃO entende,
  provando que degrada para vazio) permanece necessária, mas não é suficiente:
  ela prova a segurança, não elimina a fricção.
- **Nota subordinada (não é uma das 11 unidades, nenhum veredicto se apoia
  nela):** vale verificar, com custo baixo, se o deny de escrita em
  `.harness/harness.yaml` é por superfície de contrato e se `add-file` aceita
  paths sob `.harness/`. Se as duas respostas forem "sim", existe hoje uma rota
  de auto-ampliação independente deste backlog, e ela merece item próprio.
- **Regra eliminatória:** o item entrega A (remove um passo que não compra
  governança) e é neutro em B (fail-safe reduz, nunca amplia) — não cai em
  nenhuma das duas hipóteses de eliminação. O que impede `implementar` é que,
  como proposto, ele **devolve parte do A que promete**, na forma de
  divergência silenciosa entre os dois parsers.

## U4 — Normalização da forma de invocação: **adaptar**

- **Pró (eixo A, o maior volume):** ataca a causa-raiz correta, e a evidência
  é a tabela que a fonte **afirma ter produzido** por execução real do guard do
  HEAD (este parecer não a reproduziu): `allow pytest -q` mas
  `deny python -m pytest -q`, `deny .venv/Scripts/pytest.exe -q`,
  `deny ruff check .` com `python -m ruff` declarado. Num venv Windows a forma
  **correta** é exatamente a que o guard nega. Travar a *forma* em vez do
  *binário* é fricção pura: `pytest -q` e `.venv/Scripts/pytest.exe -q` têm o
  mesmo poder, então a negação não compra governança nenhuma — só obriga a
  descobrir por tentativa-e-erro qual grafia passa, e a fonte atribui a isso
  3 dos 7 itens do relato original.
- **Pró (eixo B):** os invariantes 2 e 3 estão certos e são bem escolhidos —
  normalizar não amplia allowlist (`python -m pip install evil` vira
  `pip install evil`, que continua não prefixando `pip install -e .`), e
  `python -m http.server` / `python -m venv` continuarem exigindo declaração é
  a leitura correta. O desdobramento de diretório restrito a prefixos de venv,
  com recusa explícita de basename genérico (`./scripts/deploy.sh` **não**
  vira `deploy.sh`), evita o erro de colisão óbvio.
- **Pró (eixo B) — a camada que torna o item seguro:** o guard de comando é
  **default-deny por allowlist**, não "tudo passa menos o floor". A tabela de
  execução que a fonte declara sustenta isso: `deny ruff check .` mesmo com
  `python -m ruff` declarado, `deny .venv/Scripts/pytest.exe -q` mesmo com
  `pytest -q` no `verify_cmd`. Um comando normalizado só chega a algum lugar
  se **prefixar uma entrada da allowlist** — e U8 declara que o filtro de
  floor remove entradas de floor da allowlist, de modo que `git push` ou
  `twine upload` não podem estar lá. Qualquer exploração da normalização exige
  portanto uma condição adicional.
- **Contra (eixo B) — erosão do invariante incondicional:** o invariante 1
  (*"normalização roda depois do floor, que continua vendo o comando bruto"*)
  protege contra a normalização criar caminho novo, mas deixa o simétrico
  descoberto: o floor **nunca inspeciona** as três formas normalizadas.
  **[premissa]** Se o floor casa por **sequência de tokens** — forma de
  casamento que a fonte não declara para o floor, embora declare
  `seg_tokens[:len(seq)] == seq` para o match de allowlist —, então
  `.venv/Scripts/git.exe push origin main` não contém o token `git` e
  `uv run twine upload dist/*` não começa por `twine`. Isso é erosão de um
  invariante que o objetivo do produto declara **incondicional** (*"nega, sob
  qualquer configuração"*): mesmo que a camada default-deny torne a exploração
  condicional, a promessa do floor deixa de ser literalmente verdadeira, e o
  floor é justamente a peça que não deveria depender de outra. **A adaptação
  (1) abaixo depende desta premissa**; se a forma de casamento do floor for
  outra e já cobrir as três formas, a adaptação (1) perde objeto — mas a
  adaptação (2) permanece, e com ela o rótulo `adaptar`.
- **Contra (eixo B) — `uv run` com flags intermediárias, reclassificado:** a
  regra `uv run <bin> …` é a mais ambígua das três: `uv run --with <pacote>
  pytest` não tem `<bin>` na posição seguinte a `run`, e a fonte não define o
  comportamento. O rascunho anterior tratava isso como lacuna de definição
  (eixo A); a classificação correta é **eixo B**. `--with <pacote>` traz
  **instalação vinda da rede** para dentro de um comando que a normalização
  faria passar como forma equivalente ao `verify_cmd` aprovado — e o objetivo
  declarado do produto diz que **rede sempre pede aprovação**. Enquanto o
  comportamento de `uv run` com flags intermediárias não estiver definido, o
  item não pode ser declarado neutro no eixo B. Secundariamente, a indefinição
  também reintroduz, em escala menor, a tentativa-e-erro que o item existe para
  eliminar — mas esse é o custo menor dos dois.
- **Adaptação exigida (é mudança de desenho, não caso de teste):**
  1. **Avaliar o floor sobre o comando bruto *e* sobre o normalizado**, com
     deny se qualquer um casar — custo computacional nulo, já que a
     normalização foi computada, e restaura a literalidade do invariante do
     produto. Casos: `.venv/Scripts/git.exe push`, `uv run twine upload`,
     `python -m twine upload`, `.venv/bin/curl …` — todos deny.
  2. **Fechar a definição de `uv run` com flags intermediárias antes de
     implementar**, decidindo explicitamente o que a normalização faz com
     `uv run --with <pacote> <bin>`.

  Por que isso não é "caso de teste": (1) contradiz o invariante 1 declarado
  pela proposta — o floor deixa de ver **apenas** o comando bruto e passa a ver
  também a forma normalizada. Isso é mudança do **fluxo de avaliação** de uma
  camada que o objetivo do produto declara incondicional, não verificação de um
  comportamento já desenhado. E (2) é bloqueante por enunciado — "antes de
  implementar" é precisamente o que separa `adaptar` de `implementar` na régua
  fixada no Método.
- **Regra eliminatória:** o item entrega A no maior volume, mas **como
  proposto** o eixo B não está preservado — a promessa literal do floor deixa
  de valer para as formas normalizadas e `uv run --with` abre caminho de rede
  sem aprovação. Cai na hipótese "flexibiliza corroendo governança" enquanto o
  desenho não mudar; com a avaliação dupla do floor e a definição de `uv run`
  fechada, passa nos dois eixos. Daí `adaptar`.

## U5 — Mensagens de deny apontando o escape barato: **implementar**

- **Pró (eixo A):** esforço S para matar uma classe inteira de ciclo. A
  mensagem manda "replaneje via `/harness-creator:plan`" quando
  `harness task add-file` já existe (`cli.py:57`), já está liberado no guard e
  já resolve — a fonte **afirma ter verificado por execução**: declarar o path
  via `add-file` faz o mesmo `Write` virar `allow`. Criar um `verify-env.sh` na
  raiz custou um ciclo inteiro exatamente por isso: cobrou-se o preço mais alto
  disponível pelo problema mais barato.
- **Pró (eixo A):** o `task_id` do contrato ativo **pré-preenchido** na
  mensagem é o detalhe que separa "existe um comando" de "cole isto" — é o que
  transforma a correção de conhecimento em ação, e é barato porque o guard já
  conhece o contrato ativo.
- **Pró (eixo A):** o deny de branch protegida hoje sugere `compile-session`,
  que não resolve nada quando o problema é estar em `main`; o agente do
  projeto-alvo diagnosticou errado, atribuindo o deny à tokenização da
  mensagem de commit. Apontar `git checkout -b <tipo>/<slug>` e dizer
  explicitamente que a mensagem não é o problema elimina ciclos gastos sobre
  uma causa inexistente.
- **Pró (eixo B):** o item não muda **nada** do que é permitido — só o que é
  comunicado; nenhuma regra de guard, floor ou contrato se move. E a refutação
  da hipótese errada que a fonte **afirma ter feito por execução** (em branch
  não-protegida, `git commit -m`, `-F -`, multi-linha e `git commit` nu são
  todos allow; em `main`, todos deny) tem valor próprio: fixada como teste de
  regressão, impede que o diagnóstico errado volte.
- **Contra (eixo B), explicitamente não decisivo:** ensinar `task add-file` na
  mensagem aumenta a frequência de uso de um caminho que amplia superfície de
  **arquivo** sem novo toque humano. Aplico aqui a mesma régua que apliquei em
  U3 e U6, uma única vez: o risco não é propriedade de U5 — o comando já
  existe e já está liberado, então a postura não muda. O risco, se existir,
  está em **`add-file` aceitar paths sob `.harness/`**, que é propriedade do
  `add-file` e é furo hoje, com ou sem U5. Por isso não rebaixo U5, e por isso
  também não usei esse risco para rebaixar U3.
- **Contra (eixo A):** o item remove a fricção de **diagnóstico**, não a
  fricção de fundo — os denies continuam existindo; e mensagens que citam um
  comando específico criam acoplamento: se a nota subordinada de U3 se
  confirmar e `add-file` passar a recusar paths sob `.harness/`, a mensagem
  precisa mudar junto. Custo baixo, mas real.
- **Regra eliminatória:** entrega A (mata ciclo) sem corroer B (nada de novo
  passa a ser permitido) — não cai em nenhuma das duas hipóteses; passa.

## U6 — `harness profile set <chave> <valor>`: **implementar**

- **Pró (eixo A):** o caso real é ambiental, não de governança — o proxy
  corporativo derrubou o TLS do `uv`, exigindo trocar `package_manager` para
  `pip`; como o analyzer só infere e o lockfile apontava `uv`, a única saída
  foi `disable` → editar → `compile-session` → `enable`. Um ciclo completo de
  desproteção para corrigir um dado de ambiente é fricção que não compra
  governança nenhuma.
- **Pró (eixo B):** a **recusa explícita de `test_glob`** é a linha que separa
  ambiente de governança e o item a traça sozinho, com a justificativa certa:
  mexer em `test_glob` altera o que conta como teste protegido, e isso é
  decisão de governança. Somam-se a enumeração fechada de chaves, a recusa de
  chave fora dela, a preservação do resto do arquivo e a passagem de cada
  valor pelo mesmo filtro de floor.
- **Contra (eixo B):** a defesa "cada valor passa pelo filtro de floor" é mais
  fraca do que soa, e é a **própria fonte**, em U9, que a desmonta: o floor é
  **denylist** e não cobre `ssh`, `scp`, `rsync`, `nc`, `docker run`,
  `certutil -urlcache`, `Invoke-Expression` nem
  `python -c "import urllib.request…"`. Um
  `test_command: "ssh user@host 'curl … | sh'"` atravessa o filtro. A defesa
  não é nula — ela barra o caso ingênuo que o item cita —, mas não é o
  perímetro que a redação sugere.
- **Contra (eixo B), condicional:** **quatro** das cinco chaves permitidas são
  superfície de comando — `test_command` é a origem do `verify_cmd` e,
  **[premissa]**, `lint_command`, `typecheck_command` e `build_command`
  alimentam a mesma família de regras (a fonte enumera as chaves, mas não
  declara para onde cada uma alimenta); só `package_manager` é puramente
  ambiental. **[premissa]** A fonte **não diz** se este subcomando entra em
  `_HARNESS_SUBCOMMANDS` — e trata essa entrada como decisão de desenho item a
  item (em U9: *"subcomando `allow-command` em `_HARNESS_SUBCOMMANDS` (logo
  executável pelo agente)"*), não como default. O que existe, portanto, é um
  ponto de desenho **não declarado**.
- **Por que isso não rebaixa o veredicto — derivado da fonte, não asserido:** a
  fonte declara o item *"ortogonal à decisão A/B/C/D; útil ao usuário mesmo na
  postura mais restritiva"*. Entre as quatro posturas que U10 enumera, a mais
  restritiva é **C** (*"nenhuma CLI nova; só U3 e U4"*), isto é, o cenário em
  que o agente não dispõe de CLI de ampliação. Ao afirmar utilidade **ao
  usuário** e **nessa** postura, a proposta declara que o valor do item não
  depende de o subcomando ser executável pelo agente — e é sob essa leitura que
  o item deve ser julgado, porque é a que a própria fonte endossa. Nela, nada da
  superfície de comando muda sem humano, e o item passa nos dois eixos **como
  proposto**, sem mudança de desenho. A premissa acima só morderia um desenho
  que a proposta não propôs; por isso ela não sustenta nem derruba o veredicto,
  e o que falta é explicitação, não correção.
- **Nota de desenho obrigatória (não bloqueia o veredicto pela derivação
  acima, mas precisa ser escrita no item):** declarar explicitamente que as
  quatro chaves de comando **não** entram em `_HARNESS_SUBCOMMANDS` — ou, se
  entrarem, que herdam **integralmente** as mitigações 1-5 de U9 (≥2 tokens,
  recusa de flags de eval, teto por contrato, escopo por contrato, log fora da
  superfície de escrita do agente).
- **Regra eliminatória:** entrega A (troca ambiental deixa de custar um ciclo)
  e preserva B (enumeração fechada, `test_glob` de fora, filtro de floor) —
  não cai em nenhuma das duas hipóteses; passa. A nota de desenho é conteúdo a
  declarar, não desenho a mudar.

## U7 — Escapes e cmdlets read-only no PowerShell: **adaptar**

- **Pró (eixo A):** o diagnóstico é o mais fino do backlog e a evidência é a
  que a fonte **afirma ter produzido por execução real** —
  `deny [PS] pytest -q | Select-Object -First 5`,
  `deny [PS] $env:PATH = '.venv\Scripts'; pytest -q`. Pipeline é a forma
  idiomática do PowerShell e nunca vai prefixar uma allowlist derivada de
  `verify_cmd`, então o caminho PS é inutilizável sob contrato ativo; isso
  empurra tudo para a Bash tool, que é justamente a que não enxerga o venv
  Windows. Parte da fricção que os outros itens tratam é consequência disso.
- **Pró (eixo B):** excluir atribuição a `$env:*` está certo — muda o ambiente
  de execução dos comandos seguintes e reabriria por outra porta o problema de
  PATH que U4 resolve de forma controlada. Excluir `ForEach-Object` pelo
  motivo declarado (executa scriptblock arbitrário) também está certo.
- **Pró (eixo B):** a correção factual do relato original (`$()` e crase **não**
  são bloqueados no PS; quem nega é a segmentação) é higiene de evidência e
  reduz o escopo do item em vez de aumentá-lo.
- **Contra (eixo B), decisivo e ancorado na fonte:** **portar**
  `_is_readonly_shell_segment` e `_is_safe_cd_segment` do Bash é a parte mais
  arriscada do item, e é a única que a proposta aceita sem exame. São
  predicados de **segurança** escritos contra outra tokenização; reaproveitá-los
  num shell diferente é reaproveitar o veredicto sem reaproveitar as premissas
  que o produziam. **[premissa externa]** As diferenças concretas que tornam
  isso arriscado (`cd` ser alias de `Set-Location`, `;` ter outra semântica de
  separação) não são verificáveis contra a fonte; o ponto estrutural — um
  predicado de segurança precisa ser **rederivado** para a gramática em que vai
  rodar — não depende delas.
- **Contra (eixo B):** a allowlist de cmdlets mistura read-only de verdade com
  execução de scriptblock. **[premissa externa]** `Where-Object` aceita
  `-FilterScript` e `Sort-Object` aceita expressão de propriedade em
  scriptblock — ambos executando código pelo mesmo mecanismo que motivou a
  exclusão de `ForEach-Object`; a fonte só declara a exclusão deste último.
  Se a premissa cair, este contra cai — mas o contra anterior, que não depende
  dela, mantém o veredicto.
- **Contra (eixo B):** liberar pipeline sem tratar **redirecionamento** (`>`,
  `Tee-Object`) libera escrita em arquivo por um caminho que a lista de
  exclusões não menciona.
- **Contra (eixo A):** qualquer remédio do tipo "recusar segmento de cmdlet que
  contenha `{`" tem dois defeitos simétricos: aplicado a dois cmdlets e não
  aos demais, é inconsistente; aplicado a todos, quebra
  `Select-Object @{Name=…;Expression={…}}`, que é sintaxe idiomática e
  read-only. Falso positivo dessa natureza é exatamente a classe de fricção
  que este backlog existe para matar — o remédio não pode reintroduzir o mal
  que o item denuncia.
- **Adaptação exigida:** (1) **rederivar** os dois escapes contra a
  tokenização do PowerShell, em vez de portá-los, tratando-os como código de
  segurança novo (com os testes correspondentes); (2) adotar **uma única
  regra** de scriptblock, uniforme para todos os cmdlets da allowlist,
  verificada cmdlet a cmdlet contra a documentação do PowerShell — e, se essa
  verificação não estiver disponível no momento da implementação, **reduzir a
  allowlist** aos cmdlets que comprovadamente não aceitam scriptblock em
  parâmetro algum, em vez de aprovar por analogia; (3) tratar redirecionamento
  e `Tee-Object` explicitamente como escrita, fora do escopo read-only; (4)
  casos de teste nos dois sentidos: `| Where-Object { Invoke-Expression $x }`
  → deny **e** propriedade calculada read-only → allow.
- **Regra eliminatória:** entrega A (recupera o único caminho que enxerga o
  venv Windows nativamente), mas o B **como proposto** não está estabelecido —
  predicados portados sem rederivação e allowlist aprovada por analogia. Cai na
  hipótese "flexibiliza corroendo governança" enquanto o desenho não mudar;
  com a rederivação e a regra uniforme, passa. Daí `adaptar`.

## U8 — Emitir `Bash(verify_cmd)` **e** `Bash(verify_cmd:*)`: **implementar**

- **Pró (eixo A):** fadiga de prompt é fricção invisível — não aparece em
  relato porque não é deny, só atrito. O caso é concreto:
  `pytest -q tests/test_api.py` é allow no `boundary_guard` mas não casa
  `Bash(pytest -q)` do `settings.json`, então vira prompt. E a assimetria é
  claramente acidente: as regras vizinhas de git e da CLI do harness usam a
  forma prefixada, `extra_allowed_commands` também; só o `verify_cmd` ficou
  exato. Esforço S.
- **Pró (eixo B):** o item **encolheu ao ser verificado** contra a doc oficial
  de permissions — a suspeita de que as demais regras estariam erradas foi
  declarada falsa, e o escopo diminuiu em vez de crescer. (U1 e U7 também
  registram correções redutoras; o que é próprio de U8 é declarar o
  encolhimento como resultado explícito da verificação.) Verificar antes de
  mexer numa regra de permissão é a disciplina que o eixo B pede.
- **Contra (eixo B):** a fonte **não** formula, em posição categórica, a tese
  de que alinhar a regra não afrouxa nada porque o `settings.json` não seria o
  enforcement real. O que ela contém é uma ressalva **estreita**, aplicada só à
  folga do `git commitfoo`: *"folga inofensiva, já que o enforcement real é o
  `boundary_guard`"*. O ponto deste contra é que essa ressalva **não se
  generaliza**. Sob a premissa que este mesmo parecer sustenta em U1 — o
  `boundary_guard` pode não rodar —, o `settings.json` é o **único** controle
  remanescente, e nesse mundo alargar a regra é alargar a última camada. O item
  continua defensável, porque o alargamento acompanha exatamente o que o guard
  já decidiria; o que não se sustenta é a ressalva tomada como categórica — e
  isso inclui a própria folga do `git commitfoo`, inofensiva **se** o guard
  roda. Consequência de sequenciamento: U8 não deve entrar antes de U1
  (ver U11).
- **Contra (eixo B) — caso de teste não opcional:** o filtro de floor hoje faz
  strip só de `*` final, e `:*` deixa um `:` pendurado que a tokenização não
  trata. `verify_cmd: "git push origin main"` **não pode** sobreviver em
  nenhuma das duas formas emitidas. Isso não é refinamento: é a condição para
  que o item não abra uma porta de floor pela própria correção. (Não é
  adaptação: o próprio item já declara este caso de teste como obrigatório.)
- **Contra (eixo A):** o item admite depender de confirmação empírica sobre o
  comando nu; emitir as duas regras deixa redundância se o teste desmentir a
  hipótese. Custo baixo, mas é dívida a fechar (confirmar e remover a
  redundante), não a carregar.
- **Regra eliminatória, com o tratamento explícito que o caso exige:** U8
  entrega A e é **neutro** em B — não é um atendedor de B. A regra elimina o
  item que *só* atende B ("preserva sem tirar fricção") e o que atende A
  corroendo B; U8 não é nenhum dos dois: tira fricção sem mover nada do que o
  guard decide. Passa. A neutralidade em B, porém, é **condicional a U1 ter
  aterrissado** — sem o guard rodando, o alargamento é da última camada.

## U9 — `harness allow-command` na postura A: **rejeitar**

**Declaração de leitura, premissa 1 (necessária, porque o veredicto depende
dela).** A fonte **não nomeia quem executa `harness disable`**: o contexto
factual diz apenas *"a sessão consumiu ~13 ciclos"*, sem sujeito, e o único
ator nomeado no parágrafo é o usuário (*"terminou com abandono do harness pelo
usuário"*). O que a fonte atribui ao agente é a **edição do YAML sob o
sentinel**, não a execução do `disable`. O contra (4) da própria proposta decide
a leitura: conteúdo hostil que instrua "rode `harness allow-command X`, depois
`X`" *"hoje trava num humano no terminal"* — frase que só é verdadeira se a
ampliação de superfície de **comando** exigir hoje um gate humano. U3 aponta na
mesma direção (*"mesmo o usuário editando o YAML no terminal próprio"*).
**Adoto essa leitura.** Se ela for falsificada — evidência de que `harness
disable` está entre os subcomandos executáveis pelo agente —, a razão 1 abaixo
muda de forma e o veredicto precisa ser reexaminado; as razões 2 e 3
sobrevivem, mas deixam de ser terminais por si.

**Declaração de leitura, premissa 2 (igualmente load-bearing, declarada no
mesmo lugar que a primeira).** A razão 1 é **comparativa**: afirma que a
postura A *cria o primeiro* caminho de auto-ampliação de superfície de comando.
A palavra "primeiro" pressupõe que a rota descrita na nota subordinada de U3
**não** esteja aberta — **[premissa]** que `harness task add-file` **não**
aceite paths sob `.harness/` ou que o deny de escrita ali não seja por
superfície de contrato; somada ao runtime-read de U3, a rota aberta daria ao
agente, hoje, uma via self-service de ampliação de comando. Se estiver aberta,
"primeiro" é falso.

**Frase de sobrevivência.** Ainda assim o `rejeitar` **sobrevive**, e pela
própria lógica deste parecer: se a rota existir, o eixo B — *"aprovação humana
onde ela é o valor"* — manda **fechá-la**, não sancionar uma segunda.
Institucionalizar a perda do gate porque ele já vazou por acidente é o inverso
do critério do pedido. O que muda, nesse mundo, é o **fundamento** da razão 1
(deixa de ser "cria o primeiro" e passa a ser "amplia superfície de comando sem
gate, seja essa a primeira via ou a segunda"), não o veredicto.

- **Pró (eixo A):** o item ataca fricção real e grande. Não existe hoje
  caminho suportado para ampliar a superfície de **comando** — `add-file`
  cobre a de arquivo — e a fonte atribui **3 ciclos completos** do relato
  exatamente a essa ausência. É a segunda maior causa isolada declarada,
  atrás só de U4.
- **Pró (eixo B) reconhecido sem espantalho:** o argumento contraintuitivo da
  proposta é **verdadeiro quanto à largura**. Com o sentinel de `disable`
  presente o `boundary_guard` vira no-op completo — sem floor, sem proteção de
  segredo, sem bloqueio de push, sem gate de evidência — e a sessão real abriu
  ~13 dessas janelas. Uma mutação estreita, filtrada e logada é, em largura,
  incomparavelmente melhor que isso, e um registro auditável é mais que o
  registro nenhum de hoje.
- **Contra (eixo B) — RAZÃO 1, decisiva:** o que decide não é a largura, é o
  **gate** — e o eixo B do pedido é literalmente *"aprovação humana onde ela é
  o valor"*. Sob a leitura adotada (premissas 1 e 2), a janela larga de hoje é
  aberta por um humano que sabe que a está abrindo; a postura A **não
  substitui** um caminho de auto-ampliação existente: ela **cria o primeiro**.
  E aí o contra que a própria proposta declara como o mais sério — **prompt
  injection com caminho self-service** — deixa de ser um risco entre outros e
  vira o argumento terminal: conteúdo não confiável (issue, README de
  dependência, página web) que instrua a sequência "amplie e depois execute"
  passa a não travar em ninguém. As mitigações 1-5 **encarecem, não impedem**.
- **Sobre a força real das mitigações, sem escolher a leitura conveniente:** a
  mitigação (1) recusa "interpretador nu e token único", e o texto admite as
  duas leituras quanto a `docker run` (`docker` está na lista de recusados, mas
  são dois tokens) — não construo argumento sobre esse exemplo ambíguo. Basta
  um não ambíguo: `harness allow-command certutil -urlcache …` ou
  `harness allow-command scp <src> <dst>` — dois ou mais tokens, sem flag de
  eval, fora da lista de interpretadores recusados, dentro do teto e do
  contrato, e **fora do floor** por confissão da própria fonte.
- **Contra (eixo B) — RAZÃO 2, corroborante:** "sujeito ao floor" é fraco por
  confissão da fonte — o floor é **denylist** e não cobre `ssh`, `scp`,
  `rsync`, `nc`, `docker run`, `certutil -urlcache`, `Invoke-Expression` nem
  `python -c "import urllib.request…"`. A própria proposta conclui que *"na
  prática A reduz o guard de comando a 'floor apenas'"*, o que é o oposto do
  objetivo declarado do produto (superfície aprovada por humano antes de o
  agente agir).
- **Contra (eixo B) — RAZÃO 3:** a auditoria é **post-hoc** — registra, não
  impede. Num cenário de injeção, o registro documenta o incidente depois de
  ele ter ocorrido.
- **Contra (eixo A):** pela própria estimativa da proposta em U10, U3+U4
  cortam ~70% da demanda por comando novo — e, se cortarem, *"A resolve pouco
  e custa os contras acima"*. O ganho de eixo A do item é, por reconhecimento
  da fonte, o resíduo depois das ondas 2-3.
- **Regra eliminatória:** o item entrega A ao preço de B — amplia a superfície
  de comando sem toque humano. Cai direto na hipótese "flexibiliza corroendo
  governança" e não passa. E não é `adaptar` porque as mitigações 1-5 **são** a
  tentativa de adaptação já feita pela própria proposta: elas elevam o custo do
  ataque sem restituir o gate, que é o que o eixo B protege. Nenhuma adaptação
  preserva os dois eixos ⇒ `rejeitar`.
- **Escopo:** esta unidade julga o **desenho do item na postura A**. A escolha
  entre A/B/C/D pertence a U10 e é tratada lá.

## U10 — A decisão de postura A/B/C/D e a recomendação D: **adaptar**

- **Pró (eixo B):** decidir uma ampliação de superfície **com dado**, depois
  de U3+U4 cortarem a demanda, é a postura metodologicamente correta — é o que
  impede o item mais perigoso de entrar por impressão. A estimativa de ~70% é
  honestamente marcada como estimativa, e a proposta declara qual é o dado que
  falta (o número de ciclos de um dogfood futuro num repo Python com venv).
- **Pró (eixo A):** D **não segura** a flexibilização que importa — a fonte
  declara que U1–U8 seguem sem dependência da decisão. O que fica em suspenso é
  apenas a ampliação de superfície de comando, isto é, exatamente a parte cuja
  pressa custaria eixo B.
- **Contra (eixo A e eixo B):** D depende de **medição** e **nenhuma das 11
  unidades instrumenta contagem**. Sem contador, D degenera em adiar
  indefinidamente (perde-se o A que a decisão destravaria) ou em decidir por
  impressão (perde-se o B que a decisão protege) — que é precisamente o que D
  existe para evitar.
- **Adaptação exigida:** instrumentar a contagem **no lado da CLI** —
  `harness disable`, `enable` e `compile-session` gravam registro de cada
  invocação. Este é o ponto que **sobrevive ao cenário medido**: os ciclos que
  interessam ocorrem com o harness **desligado**, então qualquer contador
  hospedado nos hooks (`stop_hook`, `session_start`) mediria justamente a
  janela em que os ciclos não acontecem. Registre-se que o eco de estado no
  `stop_hook` citado pela fonte é **proposta condicional à postura A**
  (mitigação 5 de U9), não capacidade existente — não estimo esforço para esta
  adaptação, porque a fonte não dá base para estimar.
- **Sobre a estimativa de ~70%, com a evidência que existe:** a fonte permite
  uma decomposição parcial — 3 dos 7 itens do relato vêm de U4, ~3 ciclos vêm
  da causa de U9, 1 ciclo vem do caso de U5 (`verify-env.sh`) e 1 ciclo do caso
  de proxy que motivou U6. Isso **corrobora a direção** da estimativa (as
  causas atacadas por U3-U6 dominam o relato), mas **não verifica o número**:
  a decomposição mistura duas unidades de medida (itens do relato e ciclos) e
  não soma aos ~13 ciclos declarados. Tratar ~70% como ordem de grandeza
  plausível, não como cifra.
- **Tensão com U9, declarada, e a condicionalidade que ela herda:** como a
  postura A está rejeitada por razão de eixo B (e não por falta de dado), D
  fica reduzida na prática a **"decidir entre B e C com dado"**. Isso é
  coerente — e barateia o gate, porque B vs C é uma escolha de muito menor
  consequência do que A vs o resto. **Essa redução vale enquanto valer a
  leitura declarada em U9** (ampliação de superfície de comando hoje exige gate
  humano). Se essa leitura for falsificada — evidência de que `harness disable`
  está entre os subcomandos executáveis pelo agente —, a rejeição de U9 volta a
  exame e a onda 5 volta a ser *"decidir A/B/C com dado"*. O veredicto
  `adaptar` de U10, porém, **não** depende disso: apoia-se na ausência de
  instrumentação de contagem, que é independente da postura escolhida.
- **Regra eliminatória:** como proposta, D entrega B (protege contra
  ampliação por impressão) e não entrega A por si — cai na hipótese "preserva
  governança sem tirar fricção", já que o mecanismo que fecharia o gate e
  destravaria a decisão não existe em unidade nenhuma. Com o contador na CLI,
  o gate passa a ser fechável e D entrega também A (uma postura decidida em
  vez de moratória permanente). Daí `adaptar`.

## U11 — Sequenciamento em ondas e gate de medição: **adaptar**

- **Pró (eixo A):** o critério declarado — `(severidade, fricção eliminada ÷
  esforço)` — é o correto para este tipo de backlog, e as ondas 1 e 2 o
  aplicam bem no essencial: os dois itens de severidade ALTA independentes
  (U1, U2) primeiro, e em seguida os dois que a própria fonte identifica como o
  volume da fricção (U3, U4).
- **Pró (eixo B):** o gate entre a onda 3 e a onda 5 — dogfood real em repo
  Python **com venv**, contando os ciclos, antes de decidir A/B/C — é a peça
  que impede o item mais perigoso de entrar por impressão. É proteção de eixo B
  embutida no próprio sequenciamento.
- **Pró (eixo B):** a ordem já satisfaz uma dependência que este parecer
  identificou: U1 está na onda 1 e U8 na onda 3, e a neutralidade de eixo B de
  U8 depende de o guard efetivamente rodar (ver U8). Nesse ponto não há o que
  corrigir.
- **Contra (eixo A):** U5 está na onda 3, atrás de dois itens M, sendo esforço
  S, não movendo nenhuma regra de permissão e matando um ciclo inteiro
  documentado (`verify-env.sh`). Pelo critério declarado pela própria proposta
  (fricção eliminada ÷ esforço), ele deveria estar na onda 1.
- **Contra (eixo A), dirigido ao critério e não à sua aplicação:** a onda 4
  para U7 é **coerente** com o critério — a fonte registra que U7 *"não estava
  nos 7 itens do relato"*, logo fricção observada zero e esforço M. A crítica
  legítima é ao critério: fricção *observada* subestima um caminho que foi
  abandonado por inutilizável. A fonte diz que o caminho PowerShell é
  inutilizável sob contrato ativo e que isso empurra tudo para a Bash tool —
  ninguém relata atrito numa estrada que parou de usar. Se o critério medisse
  fricção evitada por desvio, U7 subiria.
- **Contra (eixo B):** o item que este parecer rejeita (U9) permanece na onda 5
  atrás do gate, o que está certo; mas o texto do sequenciamento trata a onda 5
  como "decidir A/B/C", enquanto U10, aqui, reduz a decisão a B vs C. O
  sequenciamento precisa refletir isso para não reabrir A por inércia de
  redação — **e precisa registrar junto a condicionalidade**: a redução a B vs
  C vale enquanto valer a leitura declarada em U9 (hoje a ampliação de
  superfície de comando exige gate humano). O que a falsificaria: evidência de
  que `harness disable` está entre os subcomandos executáveis pelo agente. Se
  cair, a onda 5 volta a ser "decidir A/B/C com dado".
- **Adaptação exigida (nova ordenação):**
  - **Onda 1:** U1 (adaptado, lançador fail-closed) · U2 (adaptado, resolução
    no shell-alvo) · **U5 promovido** (S, mata ciclo, não move postura).
  - **Onda 2:** U3 (adaptado, com a validação no `compile-session`) · U4
    (adaptado: floor avaliado sobre o comando bruto **e** normalizado, e a
    definição de `uv run` com flags intermediárias fechada **antes** de
    implementar).
  - **Onda 3:** U6 (com a nota de desenho declarada) · U8 · instrumentação de
    contagem na CLI (adaptação de U10).
  - **Onda 4:** U7 (adaptado: escapes rederivados, regra de scriptblock
    uniforme, redirecionamento tratado).
  - **Onda 5:** gate de medição e decisão **entre B e C** com o número em mãos
    — ou entre **A, B e C**, se até lá a leitura declarada em U9 tiver sido
    falsificada.
  - **Verificação barata, junto da onda 1** (nota subordinada de U3, não é
    unidade e não fundamenta veredicto): checar se o deny de escrita em
    `.harness/harness.yaml` é por superfície de contrato e se `add-file` aceita
    paths sob `.harness/`. Se as duas respostas forem "sim", há furo hoje,
    independente deste backlog, e ele vira item próprio antes da onda 2 —
    que é quando o runtime-read de U3 tornaria a rota imediata. Esta é também a
    verificação que resolve a **premissa 2** de U9.
- **Regra eliminatória, aplicada de forma derivada:** o sequenciamento não
  entrega eixo nenhum por si — ele ordena a entrega das outras unidades, e por
  isso é julgado pelo efeito: adiar payoffs baratos de A atrás de itens caros
  desperdiça A, e antecipar itens com custo de B antes de suas condições
  corrói B. Como proposto, ele incorre na primeira metade (U5 na onda 3), então
  não passa sem mudança de desenho. Daí `adaptar`.

---

## Veredicto geral

**A proposta atende o objetivo declarado do produto, com correção obrigatória
em sete unidades (U1, U2, U3, U4, U7, U10, U11) e uma rejeição (U9,
condicional à leitura declarada naquela unidade).**

Ela acerta o diagnóstico onde mais importa: a maior parte da **fricção
relatada** — os 7 itens do relato original e os ~13 ciclos da sessão, ambos
**dados observados** — vem de restrições que **não compram governança
nenhuma**. (O dado que a proposta declara **faltante** não é esse: é a
contagem de ciclos de um dogfood **futuro**, em repo Python com venv, depois
das ondas 2-3 — exatamente o número que o gate de U11 existe para produzir.)
Travar a *forma* de invocação em vez do binário (U4) nega
`.venv/Scripts/pytest.exe -q` e permite `pytest -q`, que têm exatamente o mesmo
poder. Exigir recompilação para propagar uma lista que poderia ser lida do
disco (U3) cobra um passo cerimonial. Mandar replanejar quando existe um
comando de uma linha já liberado (U5) cobra o preço mais alto disponível pelo
problema mais barato. Declarar READY sem verificar resolubilidade (U2) põe no
contrato um `verify_cmd` que não executa. Remover essas quatro coisas
flexibiliza sem tocar em aprovação humana, TDD ou floor — é eixo A puro. U1, U7
e U8 são o outro lado: fecham buracos e recuperam um caminho, com U1 sendo
pré-condição de o eixo B existir de fato.

**Onde a proposta pede mais cuidado do que se dá:** três dos itens que
flexibilizam trazem um custo de eixo B que eles próprios não contabilizam —
executar string de repo cru antes de qualquer governança (U2), criar formas de
comando que o floor nunca inspeciona e admitir `uv run --with` trazendo rede
sem aprovação (U4) e aprovar por analogia uma allowlist de cmdlets que executa
scriptblock (U7). Nenhum desses custos é fatal, e nenhum exige abandonar o
item; todos exigem que a correção seja escrita junto com a funcionalidade, e
não depois.

**A rejeição de U9 é condicional, e a condição está nomeada.** Ela depende da
leitura, declarada e adotada em U9, de que **hoje a ampliação de superfície de
comando exige um gate humano** — leitura que a fonte não afirma diretamente,
mas que é a única que torna verdadeiro o contra (4) da própria proposta
(*"hoje trava num humano no terminal"*). **O que a falsificaria:** evidência de
que `harness disable` está entre os subcomandos executáveis pelo agente, ou de
que `harness task add-file` aceita paths sob `.harness/` (que, somado ao
runtime-read de U3, já daria hoje uma via self-service). Se a leitura cair, o
fundamento comparativo da razão 1 muda — mas o `rejeitar` se mantém, porque
pela própria lógica deste parecer a resposta correta a uma rota aberta é
**fechá-la, não sancionar uma segunda**.

**Risco a verificar antes da onda 2 (não é tese verificada; é hipótese com
teste definido).** Existe a possibilidade de que itens individualmente
defensáveis somem uma rota de auto-ampliação que nenhum deles cria sozinho:
se o deny de `Write .harness/harness.yaml` for por superfície de contrato
**e** `harness task add-file` aceitar paths sob `.harness/`, então o
runtime-read de U3 faz uma allowlist escrita valer na tool call seguinte, sem
humano e sem log. **A fonte não estabelece nenhuma das duas condições**, e a
segunda, se verdadeira, já é furo hoje, sem U3. Por isso este risco não
rebaixa nenhum veredicto: ele vira uma verificação de custo baixo na onda 1
(descrita em U11), e um item próprio somente se confirmado.

**Observação de segunda ordem sobre a própria métrica de priorização.** Se o
fail-open de U1 **ocorreu** na sessão real — e a fonte declara explicitamente
que não há evidência para afirmar nem para descartar —, então parte das tool
calls passou sem guard, e a contagem de fricção que ordena as ondas e sustenta
a estimativa de ~70% está parcialmente contaminada: denies que não
aconteceram não viraram ciclos. Isso **não** invalida os achados de código, que
a proposta **afirma ter verificado** por leitura com `file:line` e por execução
real do guard do HEAD contra repo sintético — verificação que este parecer não
reproduziu; invalida parcialmente a **métrica de priorização**. É mais uma
razão para a instrumentação de contagem exigida em U10 vir antes do gate, e
não depois.

### Contagem final

- `implementar` — **3**: U5, U6, U8.
- `adaptar` — **7**: U1, U2, U3, U4, U7, U10, U11.
- `rejeitar` — **1**: U9 — **condicional à leitura declarada na própria
  unidade**, a saber, que a ampliação de superfície de **comando** hoje exige
  gate humano. **O que a falsificaria:** evidência de que `harness disable`
  está entre os subcomandos executáveis pelo agente, ou de que
  `harness task add-file` aceita paths sob `.harness/`. Se a leitura cair, a
  razão 1 deixa de ser comparativa e a unidade precisa ser reexaminada; as
  razões 2 e 3 sobrevivem, mas deixam de ser terminais por si — e o `rejeitar`
  se re-funda em "fechar a rota, não sancionar uma segunda".

Total: **11 unidades**.

---

## Observações fora do escopo da proposta

Nenhum veredicto acima se apoia nestes pontos; ficam registrados por
honestidade de método.

1. **Quem executa `harness disable`.** A fonte não nomeia o ator. Adotei em U9
   a leitura de que a ampliação de superfície de comando hoje exige um gate
   humano, porque é a única leitura que torna verdadeiro o contra (4) da
   própria proposta (*"hoje trava num humano no terminal"*). O que falsificaria
   essa leitura: evidência de que o `disable` está entre os subcomandos
   executáveis pelo agente. Se cair, a razão 1 do `rejeitar` de U9 muda de
   fundamento e a unidade precisa ser reexaminada — e, nesse mundo, restringir
   o `disable` passaria a ser um item legítimo, que hoje o pedido não contém e
   que portanto não proponho como fundamento de nada.
2. **A rota de escrita em `.harness/`.** Descrita como nota subordinada em U3,
   declarada como premissa 2 em U9 e agendada como verificação na onda 1 em
   U11. É hipótese com teste definido, não achado.
