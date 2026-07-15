# AGENTS.md — Diretrizes de Governança para Agentes

> Este arquivo é lido pelo `ContextManager` do harness e injetado como
> contexto imutável em **toda** sessão de agente. Edite-o para governar o
> comportamento dos agentes neste repositório.

## Arquitetura

- Linguagem: Python 3.11+, tipagem estrita.
- Estrutura: `src/harness/` com uma camada operacional por pacote
  (`tools/`, `verification/`, `context/`, `governance/`, `telemetry/`, `routing/`).
- Configuração vive em `config/harness.yaml` — nunca hard-code política em código.

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
