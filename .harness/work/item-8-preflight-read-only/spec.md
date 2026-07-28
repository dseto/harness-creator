---
slug: item-8-preflight-read-only
approved_by: Daniel Seto
approved_at: 2026-07-28T16:33:49Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd sem mudança de causa — parar e devolver ao humano"
  - "conflito de revert que exija reescrever lógica não introduzida por 6c6a383 — parar e perguntar"
  - "qualquer necessidade de tocar src/harness/verify.py ou normalize_command_head — parar (fora de escopo)"
---

# Spec: preflight volta a ser read-only e ensina onde o comando de teste/lint se corrige

## Resumo executivo
Hoje o preflight, quando encontra um repositório sem configuração do harness,
oferece criar um arquivo de configuração com valores padrão — e isso não
resolve o aviso que o motivou, ainda deixa o repositório "sujo" e contradiz a
promessa de que o preflight só olha, nunca mexe. Esta demanda desfaz essa
oferta e, no lugar dela, faz o laudo dizer ao usuário exatamente qual comando
rodar no terminal dele para corrigir o comando de teste ou de lint que não
resolve. Resultado: o preflight volta a não escrever nada, e o aviso que antes
não tinha saída passa a ter uma saída provada.

## Escopo
O commit `6c6a383` (PR #47) tentou fechar o item 8 do backlog do dogfood miojo
fazendo o CLI do preflight oferecer criar `.harness/harness.yaml` com defaults.
Auditoria independente provou, com execução real, que a implementação não
resolve o item e regride o laudo:

- Criar o yaml não pode limpar `test_command_resolvable` nem
  `lint_command_resolvable`: `run_preflight` alimenta os checks só com
  `analyze_project()` + `_with_manual_overrides` (`src/harness/preflight.py:853`),
  e o yaml é tocado apenas para o flag de existência (`preflight.py:862`).
  Medido no repositório de teste: message e fix idênticos antes e depois.
- O yaml gerado grava `test_command: 'pytest -x --tb=short'`
  (`src/harness/config.py:81`) — exatamente a forma desancorada que o aviso
  denuncia — e essa chave vira o hook `guard_test_runner` no compile
  (`src/harness/compiler.py:169`).
- O arquivo criado suja a árvore de trabalho: `git_worktree_clean` foi de PASS
  para WARNING no teste real. Saldo do "fix": um aviso a mais.
- A escrita (`src/harness/cli.py:297-321`) contradiz `docs/preflight.md:5-6` e
  `skills/preflight/SKILL.md:13` e `:75`, nenhuma atualizada pelo commit.
- No caminho documentado da skill a oferta nunca dispara: stdin não-interativo
  levanta `EOFError`, engolido em `cli.py:320-321`. O agente só vê uma pergunta
  irrespondível no stderr.
- Sob guard ativo o agente alcança a escrita: `echo` está em
  `READONLY_SHELL_UTILITIES` (`src/harness/boundary_guard.py:1038`) e a
  avaliação por segmento aprova `echo s | harness preflight`, dando rota de
  escrita em `.harness/harness.yaml`, que é o arquivo de governança.
- `lint_command_resolvable` é metade do gatilho da oferta (`cli.py:302`), mas o
  schema não tem chave de lint nenhuma (`src/harness/config.py:43-51`).
- O commit retro-editou uma evidência datada de dogfood
  (`tests/e2e/evidence/preflight-dogfood-2026-07-17.md`).

A rota que de fato funciona já existe e foi provada ponta-a-ponta: corrigir
`test_command` no `.harness/repo-profile.json` com `harness profile set`, que o
preflight relê via `_with_manual_overrides` + `MANUAL_EVIDENCE`
(`preflight.py:775`, `:807`) — o check vai de WARNING para PASS. O
pré-requisito é `harness analyze`, não `init`
(`src/harness/profile_edit.py:103`), o que derruba a premissa original do item
8. `harness profile set` é comando do USUÁRIO por design (não está em
`_HARNESS_SUBCOMMANDS`, `boundary_guard.py:2122`), então a skill instrui e não
executa.

Portanto: reverter `6c6a383` por inteiro e alterar apenas o Passo 3 da skill do
preflight para instruir essa rota.

## Critérios de aceitação
- A suíte do preflight passa com o contrato de saída estrito restaurado (sem
  `has_config`): `python -m pytest tests/test_preflight.py -q`
- O helper de geração de yaml deixou de existir:
  `python -c "import harness.config as c; assert not hasattr(c, 'generate_minimal_harness_config_yaml')"`
- O CLI do preflight não escreve nem pergunta nada:
  `python -c "import pathlib,sys; t=pathlib.Path('src/harness/cli.py').read_text(encoding='utf-8'); sys.exit(0 if ('generate_minimal_harness_config_yaml' not in t and 'has_config' not in t) else 1)"`
- A evidência de dogfood datada volta ao estado original:
  `python -c "import pathlib,sys; t=pathlib.Path('tests/e2e/evidence/preflight-dogfood-2026-07-17.md').read_text(encoding='utf-8'); sys.exit(0 if 'has_config' not in t else 1)"`
- A skill do preflight instrui a rota real de correção e mantém a promessa
  read-only, verificado por teste sobre o SKILL.md real:
  `python -m pytest tests/test_preflight.py -k skill -q`

## Não-objetivos
- Não tocar `src/harness/verify.py` nem `normalize_command_head` — o item 1 do
  mesmo backlog já foi entregue na v0.23.0 (`verify.py:319-351`).
- Não reintroduzir nenhuma forma de escrita no preflight (nem opt-in, nem flag,
  nem prompt interativo).
- Não rebaixar a severidade de `test_command_resolvable`/`lint_command_resolvable`
  para nota/info — o check nasceu de um falso-PASS que custou ~13 ciclos de
  disable/compile-session/enable.
- Não estender o loop de oferta de fix a TODOS os WARNINGs do laudo; esta
  entrega cobre apenas os dois checks de resolubilidade de comando.
- Não mexer no schema de `harness.yaml` (nenhuma chave de lint nova).

## Unknowns
- Nenhum. O `analyze` do Passo 1 retornou `unknowns: []`.
