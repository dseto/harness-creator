# AGENTS.md — Diretrizes de Governança para Agentes

> Este arquivo é lido pelo `ContextManager` do harness e injetado como
> contexto imutável em **toda** sessão de agente. Edite-o para governar o
> comportamento dos agentes neste repositório.

## Arquitetura

- Linguagem: Python 3.11+, tipagem estrita.
- Estrutura: `src/harness/` com uma camada operacional por pacote
  (`tools/`, `verification/`, `context/`, `governance/`, `telemetry/`, `routing/`).
- Configuração vive em `.harness/harness.yaml` — nunca hard-code política em código.

## Regras Inegociáveis

1. **TDD obrigatório**: nenhuma implementação antes de um teste falho (fase RED
   validada pelo harness). Não edite arquivos de teste durante GREEN/REFACTOR —
   o `TDDGuard` bloqueia essa edição e bloqueia rodar a suíte via
   `run_terminal` diretamente. Precisa editar um teste protegido? Chame
   `tdd_request_test_edit` primeiro (sempre exige aprovação humana explícita,
   em qualquer modo de política).
2. **Sandbox only**: todo comando roda no contêiner isolado, sem rede. Não
   tente contornar (`curl`, `pip install` de rede, etc. falharão por design).
3. **Escopo mínimo**: modifique apenas arquivos diretamente relacionados à
   tarefa. Refactors oportunistas exigem tarefa própria.
4. **Sem segredos**: nunca escreva credenciais, tokens ou chaves em código,
   logs ou commits.
5. **Commits atômicos** com mensagem convencional (`feat:`, `fix:`, `test:`...).
6. **Prefira `read_file`/`write_file` a `run_terminal`** para operações
   simples de arquivo — são ferramentas discretas com `risk_class` correto
   (leitura nunca gateada, escrita gateada conforme a política ativa) e
   bloqueiam escapes do workspace. Use `run_terminal` para o que exige shell
   de verdade (build, lint, git).

## Convenções

- Testes: `pytest`, arquivos em `tests/`, nomeados `test_*.py`.
- Lint: `ruff check .` deve passar antes de concluir qualquer tarefa.
- Erros de ferramenta são estruturados: leia `stderr` e `recovery_hints`
  antes de repetir um comando que falhou.

<!-- harness:begin -->
## Governança do Harness (gerado — edite .harness/harness.yaml e rode `harness compile`)

Política de aprovação: **auto**. Rede (WebFetch/WebSearch/curl)
sempre exige aprovação humana.

1. **TDD obrigatório**: escreva o teste falho antes da implementação. Suíte: `pytest -x --tb=short`. Arquivos de teste (`tests/**/*.py`) são protegidos — editá-los dispara aprovação humana (hook do harness).
2. **Escopo mínimo**: modifique apenas arquivos diretamente ligados à
   tarefa; refactors oportunistas exigem tarefa própria.
3. **Sem segredos** em código, logs ou commits.
4. **Orçamento (orientação)**: alvo de ~500,000 tokens
   por tarefa e 120 tool calls. O Claude Code não
   expõe contagem de tokens a hooks — este teto é disciplina, não enforcement;
   se a tarefa estourar muito, pare e replaneje com o humano.
5. **Artefatos temporários de verificação** (screenshots, dumps de rede,
   HTML de debug, JSON de resposta de API): salve SEMPRE em
   `.harness/scratch/` — única área liberada para arquivos que não pertencem
   a nenhuma tarefa do contrato. A pasta é auto-ignorada pelo git e apagável
   a qualquer momento; nunca referencie nada dela em código e nunca salve
   esses artefatos na raiz do repositório.
<!-- harness:end -->

<!-- harness:lifecycle:begin -->
## Agent Session Lifecycle (gerado — 17 passos, docs/project/ROADMAP.md Fase 2)

1. Ler `AGENTS.md`.
2. Rodar `init.sh`/`init.ps1` (deps + health check do profile).
3. Ler `claude-progress.md`.
4. Ler `feature_list.json`.
5. Checar `git log`.
6. Escolher exatamente UMA feature pendente.
7. Planejar a implementação da feature escolhida.
8. Implementar a mudança dentro do raio de impacto declarado.
9. Rodar `verify_cmd` da tarefa.
10. Se falhar: autocorrigir e re-rodar `verify_cmd` até passar.
11. Registrar a prova (evidência da verificação bem-sucedida).
12. Atualizar `claude-progress.md` com o estado atual.
13. Marcar a feature concluída em `feature_list.json`.
14. Documentar o que ficou quebrado, se houver.
15. Parar e pedir aprovação humana explícita antes do commit, com mensagem clara do que foi feito.
16. Só após aprovação: commit em estado retomável.
17. Deixar a working tree limpa.

Detalhe de cada passo: ver `.harness/LIFECYCLE.md`.
<!-- harness:lifecycle:end -->
