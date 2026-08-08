---
slug: auto-update-transparente
approved_by: Daniel Seto
approved_at: 2026-08-08T22:30:26Z
stop_conditions:
  - "3 falhas consecutivas da mesma suite de teste (pytest)"
  - "A recompilacao automatica alterar a branch git ativa do usuario em qualquer teste"
  - "Descobrir que a recompilacao automatica pode transformar um comando que funcionava em erro (violacao do fail-open)"
---

# Spec: atualização transparente do harness no projeto

## Resumo executivo

**Problema hoje:** quando sai uma versão nova do harness-creator, atualizar
não é um passo — são vários, repetidos em cada projeto. A pessoa instala a
versão nova na máquina e, em cada repositório que usa o harness, ainda
precisa lembrar de mandar recompilar os arquivos de governança. Se
esquecer, nada quebra e nada avisa: o projeto continua rodando as regras da
versão antiga, e a única forma de descobrir é rodar um comando de
diagnóstico de propósito.

**O que vamos entregar:** o projeto passa a se atualizar sozinho. Ao usar o
harness — seja por um comando no terminal, seja abrindo uma sessão do
Claude Code — o harness percebe que os arquivos do projeto foram gerados
por uma versão mais antiga do que a instalada na máquina e os regenera na
hora, avisando em uma linha o que fez. O desenvolvedor não precisa saber
que existe uma etapa de recompilação.

**Como saber que funcionou:** depois de pronto, atualizar o harness na
máquina passa a ser um passo só (instalar). Qualquer projeto governado
volta sozinho para a versão nova no próximo uso, sem comando extra e sem
efeito colateral — em particular, sem nunca trocar a branch em que a pessoa
está trabalhando.

## Escopo

O plugin chega ao usuário por 3 camadas independentes, cada uma com seu
ciclo de atualização (documentado em `src/harness/doctor.py:6-18`):

1. pacote Python instalado (pip) -> `harness.__version__`
2. `.harness/` compilado no projeto -> `plugin_version` em
   `.harness/compiled-state.json`
3. cache de plugin do Claude Code -> `~/.claude/plugins/installed_plugins.json`

Hoje `harness doctor` apenas DIAGNOSTICA a divergência e imprime o comando
a rodar. Esta demanda automatiza exclusivamente a sincronização da
**camada 2 a partir da camada 1**: quando os artefatos compilados do projeto
estão atrás do pacote pip instalado, o harness recompila sozinho.

As camadas 1 e 3 continuam manuais e continuam sendo reportadas pelo
`doctor` — nenhuma delas pode se auto-atualizar de dentro do processo
(exigem rede e, no caso do cache de plugin, reinício da sessão do Claude
Code).

Dois gatilhos, ambos chamando a mesma primitiva:

- **CLI**: `harness.cli.main()` roda a verificação antes de despachar o
  subcomando, exceto para `compile`, `compile-session` (evita recursão),
  `doctor` (precisa observar o estado real, sem corrigi-lo) e
  `status`/`enable`/`disable` (o kill-switch precisa funcionar em qualquer
  estado). Este gatilho cobre também as skills `/harness-creator:*`, que
  invocam a CLI.
- **Hook `SessionStart`**: o script gerado passa a disparar a mesma
  verificação, cobrindo o caso em que a pessoa abre o Claude Code sem
  nunca rodar `harness` na mão.

Restrições de desenho, cada uma derivada do código atual:

- **Comparação por tupla semver, nunca por igualdade.** O `doctor` compara
  com `!=` (`doctor.py:305`) porque só reporta. Uma ação automática precisa
  distinguir defasagem de adiantamento: se a versão compilada for MAIOR que
  a do pacote pip (máquina B com pip antigo abrindo um repo compilado na
  máquina A), a ação é apenas avisar — jamais regredir os artefatos.
- **Nunca mexer na branch git.** `compile-session` hoje posiciona o
  repositório em `contract/<slug>` quando `branch_per_contract` está ativo
  (`cli.py:461-476`). Uma recompilação automática que faça isso moveria o
  desenvolvedor de branch sem ele pedir. A recompilação automática precisa
  de um modo que pule essa etapa.
- **Fail-open.** Se a recompilação falhar por qualquer motivo, o harness
  emite aviso e segue com os artefatos antigos. Auto-update jamais pode
  transformar um comando que funcionava em erro.
- **Respeita o kill-switch.** Com `.harness/harness.disabled` presente, a
  verificação não roda.
- **Opt-out.** A variável de ambiente `HARNESS_AUTO_UPDATE=0` desliga o
  comportamento. É machine-local por natureza (assim como o próprio output
  compilado), então não entra em `.harness/harness.yaml`.
- **Sem custo quando já está em dia.** O caminho feliz é uma leitura de
  JSON e uma comparação de tuplas; nenhum subprocess é disparado.

Limitação conhecida e aceita: o hook `SessionStart` da sessão atual é o da
versão antiga (foi ele quem disparou a recompilação). A sessão corrente
segue com os hooks e o `settings.local.json` antigos já carregados; a
sessão seguinte nasce na versão nova. É consistência eventual de uma
sessão. Do mesmo modo, o gatilho de hook só existe em projetos já
compilados por uma versão que o contenha — até lá, o gatilho de CLI é quem
faz o bootstrap.

## Critérios de aceitação

- A comparação de versões usa ordem semver e classifica os quatro casos
  (em dia / defasado / adiantado / ilegível), provado por
  `pytest tests/test_autoupdate.py -q`
- `harness compile-session --no-branch` compila todos os artefatos sem
  criar nem trocar a branch de contrato, mesmo com `branch_per_contract`
  ativo, provado por `pytest tests/test_cli.py -q`
- A recompilação automática falha aberta (erro no subprocess -> aviso, sem
  exceção propagada), não roda com kill-switch ativo, não roda com
  `HARNESS_AUTO_UPDATE=0` e não regride versão adiantada, provado por
  `pytest tests/test_autoupdate.py -q`
- `harness.cli.main()` dispara a verificação nos subcomandos cobertos e a
  pula em `compile`, `compile-session`, `doctor`, `status`, `enable` e
  `disable`, provado por `pytest tests/test_cli.py -q`
- O hook `SessionStart` gerado dispara a verificação com um interpretador
  que enxerga `site-packages` (sem as flags `-S`/`-E` usadas no lançamento
  do próprio hook) e nunca deixa de injetar contexto por causa dela,
  provado por `pytest tests/test_session_start.py -q`
- Fluxo ponta a ponta num repositório temporário: estado compilado com
  versão antiga volta sozinho para a versão do pacote instalado ao rodar um
  comando qualquer, sem trocar de branch, provado por
  `pytest tests/e2e/test_autoupdate_flow.py -q`
- A documentação de instalação/atualização descreve o passo único e o
  opt-out, provado por `pytest tests/test_docs_enforcement_claims.py -q`

## Não-objetivos

- Atualizar o pacote pip (camada 1) ou o cache de plugin do Claude Code
  (camada 3) automaticamente — seguem manuais e reportados pelo `doctor`.
- Compilar pela PRIMEIRA vez um clone novo que tem `harness.yaml` mas nunca
  rodou `harness compile` nesta máquina. É um caso adjacente ("clone novo
  não nasce governado", `doctor.py:20-29`), já reportado como issue pelo
  `doctor` com o comando exato; ampliar o escopo para ele faria a demanda
  deixar de ser sobre ATUALIZAÇÃO.
- Chave de opt-out em `.harness/harness.yaml` (exigiria mudar o schema de
  `HarnessConfig`; a variável de ambiente cobre o caso).
- Trava de concorrência entre duas sessões recompilando o mesmo projeto ao
  mesmo tempo — `compile` já é idempotente e o `feature_list.json` já
  carece de lock por decisão anterior documentada.
- Mudar o comportamento do `harness doctor`: ele continua exibindo a
  divergência das 3 camadas como hoje (é o único comando deliberadamente
  isento do auto-update, justamente para poder mostrar o estado real).

## Unknowns

- Nenhum. O `repo-profile.json` deste repositório não reportou unknowns.
