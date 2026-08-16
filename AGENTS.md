# AGENTS.md — Diretrizes de Governança para Agentes

> Este arquivo é injetado como contexto no início de toda sessão de agente
> Claude Code neste repositório. Edite-o para governar o comportamento dos
> agentes.

## Arquitetura

- Linguagem: Python 3.11+, tipagem estrita.
- Estrutura: `src/harness/` — módulos Python soltos por responsabilidade
  (`compiler.py`, `verify.py`, `boundary_guard.py`, `session_start.py`,
  etc.), mais os pacotes `governance/` e `teams/`.
- Configuração vive em `.harness/harness.yaml` — nunca hard-code política em código.

## Regras Inegociáveis

1. **TDD obrigatório**: nenhuma implementação antes de um teste falho (fase RED
   validada pelo harness). O gate humano é só na ESCRITA do arquivo de teste —
   editar um teste protegido sempre exige aprovação humana explícita, em
   qualquer modo de política. Rodar a suíte (RED ou GREEN, quantas vezes for
   preciso) não pede aprovação: é fricção sem sinal, o humano já aprovou o
   teste quando ele foi escrito.
2. **Floor de segurança**: o hook `boundary_guard.py` (`PreToolUse`) bloqueia
   incondicionalmente rede não planejada (`curl`, `wget`, `pip install`/
   `npm publish` de rede etc.), segredos (`.env`, `.pem`, `id_rsa`,
   `*credentials*`) e escrita em branch protegida — com ou sem contrato
   ativo. Não tente contornar.
3. **Escopo mínimo**: modifique apenas arquivos diretamente relacionados à
   tarefa. Refactors oportunistas exigem tarefa própria.
4. **Sem segredos**: nunca escreva credenciais, tokens ou chaves em código,
   logs ou commits.
5. **Commits atômicos** com mensagem convencional (`feat:`, `fix:`, `test:`...).

## Convenções

- Testes: `pytest`, arquivos em `tests/`, nomeados `test_*.py`.
- Lint: `ruff check .` deve passar antes de concluir qualquer tarefa.
- Erros de ferramenta são estruturados: leia `stderr` e `recovery_hints`
  antes de repetir um comando que falhou.

## O que entra no git

Fonte canônica: **Seção 3** de
`docs/project/AUDIT-footprint-raiz-e-versionamento-2026-07-26.md`. Não
reescreva a política aqui nem em outro documento com palavras próprias —
foi exatamente assim que ela passou a existir em duas versões contraditórias
(achado F4 daquele laudo). Precisou decidir sobre um artefato novo? Aplique o
critério de decisão da Seção 3 e acrescente a linha **lá**.

Em uma frase: *especificação, contrato e prova são versionados; saída de
compilação que carrega dado de máquina é machine-local e regenerada por
`compile`*.

Consequência operacional para você, agente: as regras de ignore são escritas
pelo próprio produto em `.harness/.gitignore` e `.claude/.gitignore` (via
`harness.settings_paths.ensure_machine_local_gitignores`). **Nunca edite o
`.gitignore` da raiz para acomodar artefato do harness**, e nunca duplique
nele uma linha que já vive num desses dois arquivos.

## Release: bump, CHANGELOG e tag são um passo só

Toda entrega que muda comportamento fecha com os **três** artefatos abaixo. Não
é opcional e não é "depois": um release pela metade é indistinguível de um
release completo olhando só o `git log`, e foi assim que as tags pararam na
`v0.22.2` enquanto quatro versões seguiram para a `main`.

1. **Versão nas três fontes manuais E nos marcadores de doc.** As fontes são
   `src/harness/__init__.py` (`__version__`), `.claude-plugin/plugin.json` e
   `.claude-plugin/marketplace.json`; o `pyproject.toml` deriva do
   `__init__.py` via hatch, não tem o que bumpar lá. Além delas, cinco
   marcadores de versão CORRENTE em documentação — o badge do `README.md`, o
   do `docs/plugin/ARCHITECTURE.md`, dois no
   `docs/plugin/arquitetura-visual.html` (pill do topo e rodapé) e o exemplo
   de `marketplace.json` no `docs/plugin/GUIDE.md`.

   **Não decore esta lista: rode `pytest tests/test_version_sync.py`.** Ele é a
   fonte de verdade (`_DOC_VERSION_MARKERS`), aponta qual arquivo ficou atrás e
   qual string procurar. Se um marcador novo nascer, ele entra lá — não aqui.

   Não confunda com **referência histórica**, que deve continuar apontando para
   a versão em que a coisa aconteceu: "Convenção da suíte (v0.26.0)",
   "padrão desde a v0.23.0", o CHANGELOG inteiro. O teste enumera marcadores em
   vez de fazer grep por número de versão exatamente para não transformar
   histórico correto em falha.

   Também não confunda com `.harness/compiled-state.json`: ele é machine-local
   e registra qual versão COMPILOU o repo. Fica atrás de propósito até o
   próximo `harness compile`, e não é fonte a bumpar.

   > Esta lista já esteve incompleta. Na v0.27.0 o bump tocou as três fontes,
   > o teste da época passou, e cinco marcadores de doc ficaram na versão
   > anterior — o README anunciava v0.26.0 com a suíte verde. A instrução foi
   > seguida à risca; o defeito era a instrução. Foi por isso que a cobertura
   > virou teste em vez de item de checklist.
2. **Entrada no `docs/reference/CHANGELOG.md`.** Uma seção `##` por versão, com
   título que descreve o que a versão FAZ (não "correções diversas"), e uma
   subseção `###` por frente de trabalho, cada uma citando sua issue e seu PR.
   A entrada explica o PORQUÊ e o modo de falha que motivou a mudança — é o
   documento que a próxima pessoa lê para não reintroduzir o problema. Se a
   versão junta frentes distintas, o título cobre as duas.
3. **Tag anotada, no commit de bump.** `git tag -a v<X.Y.Z> -m "<mesmo título
   da seção do CHANGELOG>"` seguido de `git push origin v<X.Y.Z>`. A tag é o
   que o marketplace do plugin resolve; sem ela, o bump só existe no arquivo.

Os três vão no **mesmo commit de chore**, direto na `main`, no terminal do
humano — `main` é branch protegida e o guard barra o agente ali por decisão de
projeto. Ao agente cabe deixar tudo pronto e entregar o comando; o commit e o
push da tag são do humano.

Só depois disso a demanda está encerrada. `harness finish` limpa o estado do
contrato, não o release.

<!-- harness:begin -->
## Governança do Harness (gerado — edite .harness/harness.yaml e rode `harness compile`)

Política de aprovação: **auto**. Rede (WebFetch/WebSearch/curl)
sempre exige aprovação humana.

1. **TDD obrigatório**: escreva o teste falho antes da implementação. Suíte: `pytest -x --tb=short`. Arquivos de teste (`tests/**/*.py`) são protegidos — editá-los dispara aprovação humana (hook do harness).
2. **Orçamento (orientação)**: alvo de ~500,000 tokens
   por tarefa e 120 tool calls. O Claude Code não
   expõe contagem de tokens a hooks — este teto é disciplina, não enforcement;
   se a tarefa estourar muito, pare e replaneje com o humano.
3. **Artefatos temporários de verificação** (screenshots, dumps de rede,
   HTML de debug, JSON de resposta de API): salve SEMPRE em
   `.harness/scratch/` — única área liberada para arquivos que não pertencem
   a nenhuma tarefa do contrato. A pasta é auto-ignorada pelo git e apagável
   a qualquer momento; nunca referencie nada dela em código e nunca salve
   esses artefatos na raiz do repositório.
<!-- harness:end -->

<!-- harness:lifecycle:begin -->
## Agent Session Lifecycle (gerado — 17 passos, docs/project/ROADMAP.md Fase 2)

1. Ler `AGENTS.md`.
2. Rodar `harness health` e parar se o ambiente não responder — é falha de
   infraestrutura (§8.3), não teste vermelho: não melhora tentando de novo.
   Dependência faltando se instala com `.harness/init.sh`/`.harness/init.ps1`.
3. Ler `.harness/progress.md`.
4. Ler `feature_list.json`.
5. Rodar `harness reconcile` e resolver toda divergência antes de seguir —
   estado declarado que não bate com o repositório envenena a sessão inteira.
6. Escolher exatamente UMA feature pendente — e colar `harness status --brief`
   no chat ao trocar de fatia, na abertura de cada iteração e em qualquer
   parada. A saída é montada por código: cole, nunca redija.
7. Planejar a implementação da feature escolhida — alternativa descartada por
   razão não óbvia vira `harness decide`.
8. Implementar a mudança dentro do raio de impacto declarado.
9. Rodar `verify_cmd` da tarefa — o `harness verify` ainda re-prova sozinho as
   tarefas concluídas que compartilham arquivo com esta; exit 2 = regressão a
   consertar antes de seguir. Tarefa com `metric` opcional (§4.3) também mede
   a trajetória logo depois, passe ou falhe — a métrica GUIA, quem decide
   `passes` continua sendo só o `verify_cmd`.
10. Se falhar (falha transiente já tenta de novo sozinha, 3× — não conta;
    tarefa com métrica também pode parar por piora/platô da trajetória):
    consultar `harness budget --feature <id>` e obedecer o veredito —
    autocorrigir e re-rodar só enquanto ele disser `continue`; em qualquer
    parada, usar o campo `escalation` da saída pronto, sem escrever à mão.
    **Se o que trava é uma AÇÃO HUMANA** (editar o plano de controle,
    instalar ferramenta, fornecer credencial), nada disso se aplica: a
    parede é a mesma na tentativa 1 e na 21. NÃO repita a tentativa —
    declare `harness block <id> --needs "a ação concreta que cabe à
    pessoa"` (com `--watch <path>` se houver arquivo esperado), siga para
    outra fatia, e deixe `harness unblock` para quem fez a ação.
11. Registrar a prova (evidência da verificação bem-sucedida).
12. Atualizar `.harness/progress.md` com o estado atual.
13. Marcar a feature concluída em `feature_list.json`.
14. Documentar o que ficou quebrado, e anotar a fricção da sessão com
    `harness lesson` — o agente anota, quem compila é o humano.
15. Mostrar o trabalho a quem não o escreveu: `harness blind package` →
    despachar o pacote para um verificador com contexto limpo →
    `harness blind verdict`. E apresentar o que será commitado — por feature,
    descrição funcional em linguagem natural do que mudou, e link `file:line`
    do teste que prova.
16. Antes do commit, PERGUNTAR ao desenvolvedor se quer incluir a
    atualização de docs/CHANGELOG/versão que `harness finish` reportou
    (campo `docs_version` — informativo, nunca bloqueia); nunca fazer
    sozinho, nunca pular a pergunta, "não" segue direto pro commit. Depois,
    commit e push na branch do contrato, condicionados a `harness finish`
    com `blockers: []`. O PR é do humano: entregue o `harness pr-draft`.
17. Deixar a working tree limpa.

Detalhe de cada passo: ver `.harness/LIFECYCLE.md`.
<!-- harness:lifecycle:end -->
