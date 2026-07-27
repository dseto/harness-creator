---
slug: hook-reasons-progress-sync
approved_by: Daniel Seto
approved_at: 2026-07-22T22:05:00Z
stop_conditions:
  - "3 falhas consecutivas da mesma suíte de teste (tests/test_compiler.py, tests/test_templates.py ou tests/test_verify.py) sem progresso — parar e devolver ao humano"
  - "Parser da tabela markdown do claude-progress.md ambíguo/frágil ao ponto de arriscar corromper conteúdo escrito pelo humano (seção 'Última atualização' ou texto livre) — parar e replaneja a abordagem de reescrita antes de prosseguir"
  - "verify_cmd batendo em padrão de arquivo/processo em uso (lock: MSB302x/EBUSY) — parar, é processo externo, não bug da tarefa"
---

# Spec: razão concreta nos hooks TDD + sincronização automática do claude-progress.md

## Escopo

Duas correções de qualidade achadas durante o dogfood do próprio harness-creator, ambas do tipo "o lifecycle promete algo que nada garante/mostra":

**US-1 — Razão concreta nos hooks TDD gerados.** Os hooks `guard_test_runner.py` e `guard_tests.py`, gerados por `_render_guard_test_runner`/`_render_guard_tests` em `src/harness/compiler.py`, emitem `permissionDecisionReason` com texto FIXO, igual em toda aprovação, sem citar o comando Bash executado nem o arquivo de teste editado. O humano aprova às cegas — não sabe, pelo prompt, o que está sendo testado/editado. Corrigir: `guard_test_runner.py` inclui o comando real na razão; `guard_tests.py` inclui o path do arquivo na razão.

**US-2 — claude-progress.md sincroniza com feature_list.json (opção b: eliminar o passo manual).** `claude-progress.md` é escrito uma única vez como esqueleto (`install_templates`, só grava se ausente) e depois só é atualizado manualmente pelo agente (passo 12 do lifecycle), sem enforcement. A fonte de verdade real é `.harness/feature_list.json` (`passes`) + `.harness/evidence/<id>.json`. Resultado observado: contrato `extra-allowed-commands` fechou (T-01..T-05 `passes:true`, evidência gravada, código em `ddc37f6`) mas `claude-progress.md` continuou com as 5 linhas em `pending`. Corrigir na CAUSA: quando `run_verify` tem sucesso (exit 0), reescrever a linha do `<id>` na tabela do `claude-progress.md` para `done` — automático, sem passo manual.

## Critérios de aceitação

- US-1: a razão do `guard_test_runner.py` gerado contém o comando Bash executado; a razão do `guard_tests.py` gerado contém o path do arquivo de teste — prova: `python -m pytest tests/test_compiler.py -q`
- US-2 (helper puro): `templates.update_progress_status` reescreve só a coluna de status da linha do `<id>` para `done`, é idempotente (2ª chamada não duplica/quebra) e é no-op silencioso quando o arquivo ou a linha do `<id>` não existem (nunca recria esqueleto, nunca toca a seção "Última atualização" nem outras linhas) — prova: `python -m pytest tests/test_templates.py -q`
- US-2 (wiring): após `run_verify` sair com exit 0 e gravar evidência, a linha do `<id>` no `claude-progress.md` fica `done`; se o arquivo não existir, `run_verify` não falha por causa disso — prova: `python -m pytest tests/test_verify.py -q`
- Regressão total verde e lint limpo — prova: `python -m pytest tests -q` e `ruff check .`

## Não-objetivos

- Opção (a) — detecção da divergência via nova invariante em `runtime_audit.py`. Descartada explicitamente: só apitaria, não cura.
- Extração de NOMES de função de teste tocados para a razão do `guard_tests.py` — mencionado como "idealmente" na demanda, fica FORA desta entrega (só o path). Possível trabalho futuro.
- Reescrever a seção "Última atualização" (texto livre) do `claude-progress.md` — só a coluna de status da tabela muda.
- Mexer nas razões do `boundary_guard.py` (mecanismo moderno) — já são concretas.
- Bump de versão / publicação — decisão à parte; esta entrega inclui só nota no CHANGELOG, sem release.

## Unknowns

- `package_manager` do repo-alvo: `analyze` não detectou lockfile e o usuário não confirmou um valor — permanece unknown. Irrelevante para estas tarefas (todas verificam com `pytest`, já detectado como test_command).
