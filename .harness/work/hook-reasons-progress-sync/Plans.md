# Plans: hook-reasons-progress-sync

## [T-01] US-1 — razão concreta nos hooks TDD gerados (guard_test_runner + guard_tests)
- files: `src/harness/compiler.py`, `tests/test_compiler.py`
- verify: `python -m pytest tests/test_compiler.py -q`

Em `_render_guard_test_runner`, montar a `permissionDecisionReason` incluindo o `command` que casou (já disponível na `main()` do hook gerado). Em `_render_guard_tests`, incluir o `path` do arquivo de teste (já resolvido na `main()`). Novos asserts em `tests/test_compiler.py` checando que a razão contém, respectivamente, o comando e o path — sem alterar os asserts existentes de `permissionDecision`.

## [T-02] US-2 — templates.update_progress_status: reescreve a coluna de status de uma linha
- files: `src/harness/templates.py`, `tests/test_templates.py`
- verify: `python -m pytest tests/test_templates.py -q`

Nova função pública `update_progress_status(target_dir, feature_id, status)` em `templates.py`: lê `claude-progress.md`, localiza a linha da tabela cujo 1º campo é `feature_id`, reescreve só a coluna de status para `status`, grava de volta. Idempotente (2ª chamada = mesmo resultado). No-op silencioso se o arquivo não existir OU se nenhuma linha casar o `feature_id` (nunca cria o arquivo, nunca toca a seção "Última atualização" nem outras linhas). Testes cobrindo: reescrita pending->done, idempotência, arquivo ausente, id inexistente, preservação do resto do conteúdo.

## [T-03] US-2 — wiring: run_verify sincroniza o claude-progress.md ao provar a feature
- files: `src/harness/verify.py`, `tests/test_verify.py`
- verify: `python -m pytest tests/test_verify.py -q`
- depends: T-02

Após gravar a evidência com sucesso (exit 0) em `run_verify`, chamar `update_progress_status(target_dir, feature_id, "done")`. Atualizar a docstring do módulo/função para refletir o efeito aditivo. A ausência do `claude-progress.md` nunca faz `run_verify` falhar (o no-op de T-02 garante). Teste em `tests/test_verify.py`: verify bem-sucedido com um `claude-progress.md` presente deixa a linha da feature `done`; verify bem-sucedido sem o arquivo continua gravando evidência e não levanta.

## [T-04] Regressão total + nota no CHANGELOG
- files: `docs/reference/CHANGELOG.md`
- verify: `python -m pytest tests -q`
- depends: T-01, T-03

Suíte inteira verde após as três tarefas. Registrar as duas correções no CHANGELOG (razão concreta nos hooks TDD; sincronização automática do claude-progress.md via run_verify). Sem bump de versão / release nesta entrega.
