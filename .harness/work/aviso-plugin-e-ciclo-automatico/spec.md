---
slug: aviso-plugin-e-ciclo-automatico
approved_by: Daniel Seto
approved_at: 2026-08-09T00:29:38Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste (pytest)"
  - "O aviso de plugin bloquear, negar ou alterar o resultado de qualquer tool call — ele e estritamente informativo"
  - "O aviso aparecer em repositorio que nunca instalou o plugin por marketplace (installed_plugins.json ausente)"
  - "A mudanca remover ou enfraquecer o gate de aprovacao do CONTRATO — ele passa a ser o unico gate humano do ciclo"
  - "O commit automatico passar a ocorrer com `harness finish` reportando blockers, ou com verify_cmd vermelho"
  - "Qualquer automacao tentar abrir, aprovar ou mergear o PR"
---

# Spec: parar de exigir do humano o que o harness já sabe

## Resumo executivo

**Problema hoje:** o ciclo interrompe a pessoa três vezes pedindo coisas que
ela já decidiu ou que a ferramenta já sabe.

Ela precisa *descobrir sozinha* que as skills do harness estão
desatualizadas — quando o plugin instalado no Claude Code fica para trás do
pacote da máquina, nada avisa. Precisa *pedir duas vezes*: depois de aprovar o
contrato, o ciclo para e espera um "pode implementar". E precisa *aprovar de
novo* no fim, para um commit de trabalho que já foi verificado tarefa a
tarefa.

**O que vamos entregar:** a sessão passa a começar avisando quando o plugin
está velho, com o comando exato e o aviso de reiniciar. Aprovar o contrato
passa a disparar o ciclo inteiro — implementação, commit e push na branch da
feature — sem nenhuma confirmação intermediária. E o Pull Request, que
continua sendo do humano, chega pronto: o harness entrega o comando e a
descrição completa, bastando colar.

**Como saber que funcionou:** entre "aprovado" e o PR pronto para abrir não
há mais nenhuma pergunta. O que protege continua protegendo: o contrato só
anda com aprovação humana, o commit só acontece com todas as provas verdes, e
nada chega à `main` sem alguém abrir e mergear o PR.

## Escopo

Três mudanças independentes, no mesmo contrato por decisão do usuário
(2026-08-09): um ciclo, um PR. Não compartilham código; compartilham a causa —
o humano fazendo o trabalho que o harness deveria fazer.

### Parte A — aviso do cache de plugin desatualizado

Completa a cobertura das 3 camadas de distribuição de
`src/harness/doctor.py:6-18`:

| Camada | Hoje | Depois |
|---|---|---|
| 1. pacote pip | manual, reportada pelo `doctor` | inalterada |
| 2. `.harness/` compilado | **auto-corrige** (v0.31.0) | inalterada |
| 3. cache de plugin do Claude Code | só no `doctor`, sob demanda | **avisa na abertura da sessão** |

Bloquear a camada 3 foi avaliado e **descartado**, por quatro razões
registradas aqui para a decisão não ser refeita por engano:

1. **Auto-trava no release.** Bumpar o pip torna o cache obsoleto no mesmo
   instante; um deny nessa condição tornaria o próprio commit de bump a
   última ação possível no repositório.
2. **Não existe superfície estreita para negar.** Skills são arquivos de
   prompt, não tool calls — não passam pelo `PreToolUse`.
3. **Não há conserto dentro da sessão.** `claude plugin update` exige rede e
   reinício; um deny ficaria de pé até a sessão morrer, e empurraria a pessoa
   para `harness disable` — kill-switch é desproteção total.
4. **Skill desatualizada não fura gate nenhum.** O enforcement vive nos hooks
   (camada 2) e na CLI (camada 1), ambos correntes.

**Onde a informação nasce.** O hook `SessionStart` é stdlib-only e roda com
`-S`, então não importa `harness`. Ele já dispara `python -m
harness.autoupdate` a cada sessão (v0.31.0): esse payload JSON ganha o estado
do cache de plugin, e a comparação reutiliza o que `harness.doctor` já sabe
ler de `installed_plugins.json`. Nenhum subprocesso novo.

**Texto do aviso** (ASCII, como todo o script gerado; versão e id do plugin
preenchidos em runtime):

```
## ACAO NECESSARIA: as skills do harness estao desatualizadas

O plugin instalado no Claude Code esta na versao 0.30.0, mas o pacote
instalado nesta maquina e 0.31.0. As skills /harness-creator:* desta
sessao vem da copia ANTIGA.

Rode este comando no SEU terminal (fora do Claude Code):

    claude plugin update harness-creator@harness-creator-local

Depois REINICIE a sessao do Claude Code. As skills sao carregadas no
inicio da sessao, entao a atualizacao NAO vale para esta sessao aqui.

Isto nao bloqueia nada: os hooks de protecao e a CLI ja estao em 0.31.0.
O que esta atrasado sao os textos das skills.
```

Decisões: `HARNESS_AUTO_UPDATE=0` **não** silencia o aviso (a variável desliga
a ação, não a informação); kill-switch silencia (o hook já devolve o banner de
desativado); `installed_plugins.json` ausente não avisa (caso normal de
`--plugin-dir`/pip); plugin à frente do pacote não avisa (`claude plugin
update` não corrige cache adiantado).

### Parte B — o ciclo corre de ponta a ponta depois da aprovação

Hoje o ciclo tem **três** paradas humanas: aprovar o contrato, pedir a
implementação, aprovar o commit. Passa a ter **uma**.

`src/harness/lifecycle.py:134-149` (passos 15 e 16 do Agent Session Lifecycle,
que geram `AGENTS.md` e `.harness/LIFECYCLE.md`) declara hoje que "o agente
NUNCA commita sem sinal verde do humano". Esse gate é **instrucional, não
imposto** — o `boundary_guard` só barra commit em branch protegida; na branch
do contrato, `git commit` e `git push` já passam. A mudança é no texto que
governa o comportamento, não no guard.

O que passa a valer:

- **Commit automático**, na branch do contrato, assim que `harness finish`
  sair com `blockers: []`.
- **Push automático** da branch do contrato para ela mesma. O runtime floor já
  restringe exatamente a isso: sem `--force`, sem refspec explícito, nunca de
  branch protegida.
- **PR continua manual.** O agente NUNCA abre, aprova ou mergeia PR.

O que **não** muda:

- O gate de aprovação do contrato continua sendo gate, e passa a ser o único.
  `approved_by`/`approved_at` seguem proibidos de auto-preenchimento.
- As paradas que o `boundary_guard` impõe continuam — commit em branch
  protegida, push de tag, comando fora da superfície.
- O passo 15 não desaparece: deixa de ser "pare e peça aprovação" e passa a
  ser "apresente o que será commitado", preservando a visibilidade do diff.

**Pré-condições duras do commit automático**, escritas porque são o que
substitui o gate humano: `harness finish` com `blockers: []` (o que já implica
toda tarefa com `passes: true` e evidência fresca) e nenhum `verify_cmd`
vermelho. Sem as duas, o agente para e chama o humano.

### Parte C — o PR chega pronto

Comando novo `harness pr-draft`, que usa o que o contrato já tem estruturado
(slug, tarefas, `verify_cmd`, evidência) para montar o trabalho braçal do PR:

- grava o corpo em `.harness/scratch/pr-body.md` — diretório de escrita
  liberada e auto-ignorado pelo git — com o título sugerido, a tabela de
  tarefas com suas provas, o resumo de evidência, e as seções de racional para
  o agente preencher;
- imprime, em JSON, o caminho do corpo e o **comando exato** de `gh pr create`
  com `--body-file`, pronto para colar.

A divisão é deliberada: o comando gera o que é **fato derivável do contrato**,
e o agente preenche o **racional** (o que mudou, por quê, quais decisões de
desenho) — que não é derivável e é justamente a parte valiosa da descrição.
Corpo em arquivo, e não em `--body` inline, porque acentuação em linha de
comando no PowerShell 5.1 corrompe multi-byte.

## Critérios de aceitação

- Uma função reutilizável devolve as instalações de plugin atrás do pacote
  instalado, cada uma com o comando exato de correção, e lista vazia quando o
  arquivo está ausente, ilegível, em dia ou à frente, provado por
  `pytest tests/test_doctor.py -q`
- O payload de `python -m harness.autoupdate` carrega esse estado mesmo sem
  recompilação e mesmo com `HARNESS_AUTO_UPDATE=0`, provado por
  `pytest tests/test_autoupdate.py -q`
- O contexto injetado no início da sessão traz o cabeçalho de ação, as duas
  versões, o comando `claude plugin update <id>` e a exigência de reiniciar; e
  nada disso aparece com o plugin em dia, provado por
  `pytest tests/test_session_start.py -q`
- Fluxo ponta a ponta com `installed_plugins.json` real em disco: o hook roda
  de verdade, o aviso chega ao contexto e a saída do hook segue íntegra,
  provado por `pytest tests/e2e/test_autoupdate_flow.py -q`
- `harness pr-draft` grava o corpo em `.harness/scratch/pr-body.md` com a
  tabela de tarefas e as seções de racional, e imprime o comando `gh pr
  create` com `--body-file`; falha com mensagem clara sem contrato compilado,
  provado por `pytest tests/test_pr_draft.py -q`
- O lifecycle gerado declara commit e push automáticos condicionados a
  `harness finish` com `blockers: []`, mantém a apresentação do diff e mantém
  o PR como ação humana, provado por `pytest tests/test_lifecycle.py -q`
- `skills/plan/SKILL.md` declara que a aprovação do contrato é o único gate
  humano e dispara o ciclo até o push, entrega o PR pronto, e preserva a
  proibição de auto-preencher `approved_by`/`approved_at`, provado por
  `pytest tests/test_plan_skill_approval_flow.py -q`
- A documentação descreve a camada 3 avisada-mas-não-bloqueada, as quatro
  razões do descarte do bloqueio, e o gate único do ciclo, provado por
  `pytest tests/test_docs_enforcement_claims.py -q`

## Não-objetivos

- Bloquear, negar ou degradar tool call por causa do cache de plugin.
- Rodar `claude plugin update` automaticamente, ou reiniciar a sessão.
- Abrir, aprovar ou mergear Pull Request automaticamente — em nenhuma
  circunstância, por nenhum caminho.
- Commitar ou empurrar em branch protegida: segue barrado pelo runtime floor,
  e o `chore` de versão/CHANGELOG continua sendo do humano.
- Afrouxar o runtime floor do `git push` (sem `--force`, sem refspec
  explícito, só da branch do contrato para ela mesma).
- Remover, enfraquecer ou automatizar o gate de aprovação do contrato.
- Gerar o racional do PR automaticamente: `pr-draft` monta o fato, o agente
  escreve o porquê.
- Mudar as outras skills (`assess`, `init`, `preflight`, `team`, `audit`,
  `compile`): nenhuma tem gate de aprovação de contrato.

## Unknowns

- Nenhum. O `repo-profile.json` deste repositório não reportou unknowns.
