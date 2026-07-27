# Backlog — achados de teste isento — 2026-07-27

Três rodadas de teste isento contra o `elegant-heisenberg`, cada uma com um
agente que **não sabia** o que tinha sido corrigido na rodada anterior. O que
foi corrigido no mesmo dia está no `docs/reference/CHANGELOG.md`; este
documento é o que ficou **em aberto**, por decisão explícita do usuário.

Método que produziu os achados, para quem for repetir: instalar do zero num
alvo real, provar cada afirmação com comando (`git check-ignore -v` por
artefato, `git ls-files` + grep por path absoluto), castigar os comandos com
entrada ruim, e conferir se todo caminho citado pela documentação **gerada**
existe de fato. Não avisar o agente do que mudou é o que torna o resultado
informativo — um teste que confirma a si mesmo não vale nada.

---

## 1. Cadeia de auto-aprovação de contrato — P0, decisão de arquitetura

**Decisão do usuário (2026-07-27): registrar, não mexer agora.** As opções de
correção mudam o fluxo de trabalho e merecem ser pensadas com calma.

Cada peça é documentada e defensável isoladamente; a composição derruba a tese
central do produto (*"a skill nunca aprova sozinha"*, *"o gate é você"*):

| ação do agente | decisão do guard | por quê |
|---|---|---|
| `Write .harness/work/pwn/spec.md` com `approved_by: Claude` | **allow** | `.harness/work/**` é área de autoria, sempre gravável (GUIDE §5) |
| `Write .harness/work/pwn/Plans.md` | **allow** | idem |
| `Bash harness compile-contract --slug pwn` | **allow** | está no `allow` enumerado da sessão |
| `Bash harness compile-session` | **allow** | idem |

Nada valida que quem preencheu `approved_by` é humano, e o `spec.md` aprovado
não é assinado nem hasheado — então também não há como detectar edição
posterior à aprovação.

Contraste que mostra que o problema é resolvível: `harness disable` **é**
barrado pelo floor (`runtime floor: harness disable / criar o sentinel de
kill-switch`). Aquela porta foi pensada; esta não.

Três direções avaliadas, nenhuma escolhida:

1. **Negar edição do frontmatter aprovado** — o `boundary_guard` passa a negar
   `Write`/`Edit` que introduza ou altere `approved_by`/`approved_at` num
   `spec.md`. A área de autoria continua gravável para o resto do contrato.
   Mais cirúrgico; exige o guard parsear frontmatter.
2. **Tirar `compile-contract` da superfície liberada** — o humano roda no
   próprio terminal, como já acontece com `harness disable`. Mais simples e
   mais forte; custa um passo manual por contrato.
3. **Assinar o `spec.md` aprovado** (hash gravado fora do alcance do agente).
   Resolve também a edição pós-aprovação; é a mais cara.

---

## 2. `verify_cmd` não é validado contra o profile — P1

`docs/plugin/GUIDE.md` dizia que `harness verify` roda o comando *"validado
contra o profile"*. **A frase foi corrigida** (o texto agora descreve o que
existe de fato), mas a validação em si não existe e continua em aberto.

Hoje um contrato aprovado com `verify: echo PWNED > .harness/scratch/x.txt`
executa e grava evidência com exit 0. O runtime floor **funciona** para
rede/push (`verify: curl ...` → `exit 1`, nunca executado, mesmo vindo de
contrato compilado) — a lacuna é só a ausência de cruzamento com o
`repo-profile.json`.

Decisão a tomar: cruzar com `test_command`/`lint_command`/`build_command` do
profile é restritivo demais para monorepo (o `verify_cmd` legítimo do
`elegant-heisenberg` é `npm --prefix frontend run test:ci -- --include=...`,
que não aparece literal no profile). Talvez a regra certa seja "prefixo do
comando tem que bater com um binário conhecido do profile".

---

## 3. `Plans.md` estruturalmente inválido compila com exit 0 — P1

Nenhum destes é recusado hoje:

| entrada | resultado atual | consequência |
|---|---|---|
| Plans.md sem nenhuma tarefa | `"features": 0`, exit 0 | contrato vazio compilado |
| `## T-01` sem colchetes | `"features": 0`, exit 0 | silêncio total — e o TUTORIAL avisa que colchetes são obrigatórios |
| dois blocos `## [T-01]` | `"features": 2`, exit 0 | `verify T-01`, `evidence/<contrato>/T-01.json` e `review/T-01.json` ficam ambíguos |
| ciclo `T-01 ↔ T-02` em `depends` | exit 0 | `harness supervise` nunca devolve feature |
| `depends: T-99` inexistente | exit 0 | idem |

O contraste é que o campo `verify` ausente **é** recusado com mensagem
exemplar, e o erro para `verify_cmd:` em vez de `verify:` também. A validação
estrutural existe, só não cobre estes casos.

---

## 4. Frontmatter: `slug` ignorado, `approved_at` no futuro aceito — P2

- O `slug` do frontmatter (presente no template do TUTORIAL) **nunca** é
  confrontado com o `--slug` da linha de comando: `slug: COMPLETAMENTE-OUTRO`
  compila sem reclamar. Ou os dois batem, ou o campo do frontmatter não devia
  existir no template.
- `approved_at: 2099-12-31T23:59:59Z` passa. O formato é validado desde
  2026-07-27, a plausibilidade não — e é uma trilha de auditoria.
- `stop_conditions:` como string em vez de lista passa sem warning. É dela que
  o lifecycle (passo 10) diz ler o disjuntor do loop de autocorreção.

---

## 5. Evidência órfã do layout antigo não é detectada — P2

A evidência passou a ser escopada por contrato
(`.harness/evidence/<contrato>/<id>.json`) em 2026-07-27. Um alvo que veio da
0.17.x fica com os dois layouts convivendo: os arquivos flat
(`.harness/evidence/T-01.json`) continuam versionados, ninguém mais os lê, e
`harness audit-runtime` devolve **score 100, zero findings** com eles em disco.

Encaixa no mesmo balde do item 6: nenhum comando detecta resíduo de instalação
anterior.

---

## 6. Nada detecta resíduo de instalação anterior — P2

Apareceu nas **três** rodadas. Com `claude-progress.md`, `init.sh` e `init.ps1`
da 0.17.x ainda na raiz do alvo, e o bloco `harness:lifecycle` antigo mandando
rodar `init.sh` da raiz:

- `harness audit` → score 85, nenhum finding sobre isso;
- `harness doctor` → só a divergência de versão do cache de plugin.

Os agentes só acharam os três arquivos cruzando o inventário do TUTORIAL com o
fonte, à mão. Como a premissa do produto é "instalação sempre do zero, nunca
migrada", não existe caminho de limpeza — mas então alguém precisa **avisar**
que existe resíduo. `harness doctor` é o lugar natural.

Correlato (A5 da 2ª rodada): o `claude-progress.md` antigo (13 KB, histórico de
6 contratos) não tem migração para `.harness/progress.md` — evapora numa
reinstalação. A doc garante que o progresso "nunca é sobrescrito", o que é
verdade para o arquivo novo e falso para o antigo.

---

## 7. Comandos que respondem como se o repo fosse governado — P2

| comando | repo sem `.harness/` | problema |
|---|---|---|
| `harness disable --dir .` | exit 0, **cria** `.harness/harness.disabled` | único comando que escreve em alvo sem harness |
| `harness status --dir .` | `{"disabled": false}` | "ativo" e "não existe" ficam indistinguíveis |
| `harness audit-team --dir .` | `score: 100`, finding `info`, exit 0 | CI que gate por score aprova repo ingovernado |
| `harness team design --dir .` | recomenda padrão de time | a doc diz que ele analisa o `repo-profile.json`, que não existe |

---

## 8. Kill-switch ausente das docs de usuário — P2

`grep -rn "harness disable" docs/plugin/ skills/` só bate na linha do
inventário de artefatos. Nem o GUIDE nem o TUTORIAL descrevem o kill-switch.

Agrava: com o sentinel presente, o `boundary_guard` responde `allow | harness
desativado pelo usuario` para **tudo**, inclusive `Bash curl http://evil.com` —
o floor "inegociável" some. É defensável como kill-switch consciente, mas um
mecanismo que anula a garantia mais forte do produto não pode ficar fora das
duas docs de usuário.

---

## 9. Itens menores — P3

- **Lifecycle gerado cita `feature_list.json` sem prefixo.** Passos 4 e 13 do
  bloco gerenciado dizem `Ler feature_list.json`; o arquivo é
  `.harness/feature_list.json`. Os passos 2, 3 e o ponteiro final usam
  `.harness/` corretamente — inconsistência dentro do mesmo bloco.
- **`harness review <id> approve` vaza nome de função interna** e é o único
  erro do CLI sem "fix": `erro: record_decision: transição inválida a partir
  do estado 'pending'` não diz que o caminho para `in_review` é `harness
  verify`.
- **`--timeout` negativo é aceito** — `--timeout -5` produz "excedeu o timeout
  de -5s". `--timeout abc` já sai 2 corretamente.
- **`harness doctor` sai 1 por drift do cache de plugin**, que é estado da
  máquina e não do repositório — inutilizável como gate de CI por repo. Talvez
  separar "saúde do repositório" de "saúde da instalação" em exit codes
  distintos.
- **O bloco gerenciado do `AGENTS.md` migra de posição** numa reinstalação (do
  topo para o fim, abaixo da prosa humana). A prosa é preservada intacta, mas o
  `git diff` fica ruidoso.
