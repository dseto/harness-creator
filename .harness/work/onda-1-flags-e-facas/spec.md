---
slug: onda-1-flags-e-facas
approved_by: Daniel Seto
approved_at: 2026-07-30T11:05:48Z
stop_conditions:
  - "3 falhas consecutivas do mesmo verify_cmd sem hipótese nova — parar e devolver ao humano"
  - "Qualquer verify_cmd desta demanda exigir mudar um allow em deny (ou vice-versa) fora do que os critérios de aceitação declaram — parar e perguntar antes de tocar no floor de permissão"
  - "A poda de T-07 encontrar uma entrada de allow que NÃO seja estritamente subsumida por uma regra nua (Bash/Edit/Write/Read/Grep/Glob) já presente na mesma lista — não remover essa entrada; parar e perguntar"
---

# Spec: cortar peso morto de latência e tokens sem mudar nenhuma trava de segurança

## Resumo executivo

Hoje, cada comando que o agente roda passa por duas checagens de segurança em
sequência (uma delas não decide nada, só carimba "liberado"), e alguns
arquivos que o harness gera carregam comentários enormes que ninguém lê, um
script morto sem consumidor, e regras de permissão repetidas que uma regra
mais ampla já cobre. Esta entrega corta esse peso sem soltar nenhuma trava:
comandos ficam mais rápidos, os arquivos gerados ficam menores e mais
confiáveis, e nada que hoje é bloqueado passa a ser permitido.

## Escopo

Origem: seção 1 (itens 1, 9, 10 parcial, 12, 13, 15, 16) e seção 4 ("Onda 1")
de
[docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md](../../../docs/project/AUDIT-quick-wins-simplificacao-2026-07-30.md).
Sete correções mecânicas, todas com verificação executável, nenhuma exigindo
julgamento de segurança novo:

**1. Hook mais rápido.** O interpretador que roda os hooks de proteção é
lançado sem `-S`/`-E`: em toda tool call, o Python varre `site-packages` e
`.pth` de instalações de **outros projetos** na máquina antes de rodar um
script que só usa biblioteca padrão. Medido: 90→68 ms por chamada
([hook_launcher.py:109](../../../src/harness/hook_launcher.py#L109)).

**2. Docstring de módulo mais curto.** `boundary_guard.py` abre com 284
linhas de histórico de decisões (issues, achados, validações) que o hook
efetivamente instalado **nunca carrega** — `render_boundary_guard` substitui
por um cabeçalho de 33 linhas. O texto tem valor de arquivo, não de runtime
([boundary_guard.py:1-284](../../../src/harness/boundary_guard.py#L1)).

**3. Render determinístico.** Seis pontos de `render_boundary_guard` iteram
`set(...)!r` — a ordem de saída varia a cada processo Python (confirmado:
3 execuções, 3 hashes diferentes para o mesmo conteúdo). Sem determinismo,
nenhum check de drift por hash é possível no maior hook do produto
([boundary_guard.py:2183-2240](../../../src/harness/boundary_guard.py#L2183)).

**4. Remover a geração de `guard_tests.py`.** O compilador gera este script
mas o próprio produto remove seu registro em toda instalação (decisão do
issue #61: o `boundary_guard` cobre a mesma proteção por tarefa). A decisão
de NÃO registrar está certa; gerar o arquivo não tem consumidor.
Correção a uma estimativa anterior: isto é um "Outcome" testado da Fase 2 —
6 testes unitários (`tests/test_compiler.py`) e 2 e2e
(`test_boundary_flow.py`, `test_fase2_outcomes.py`) hoje afirmam
explicitamente "gerado, mas não registrado". Remover a geração exige
atualizar essas provas para "não gerado", não só apagar a função de render
([compiler.py:166-186](../../../src/harness/compiler.py#L166)).

**5. `findings.py` compartilhado.** `audit.py`, `runtime_audit.py` e
`team_audit.py` definem `Finding`/`Report`/`_PENALTY`/`_finish` de forma
triplicada, byte a byte. Um módulo novo concentra a definição; os três
módulos passam a importar de lá (re-exportando o mesmo nome, então nenhum
teste existente que faz `from harness.audit import Finding` quebra)
([audit.py:31-55](../../../src/harness/audit.py#L31)).

**6. Truncar saída de `verify` que falha.** Hoje `harness verify` sem
`--mark-passed` bem-sucedido despeja stdout **e** stderr completos do runner
de teste no stderr do processo — uma suíte pytest verbosa entra inteira no
contexto do agente no caminho mais frequente do ciclo TDD (o vermelho)
([cli.py:542](../../../src/harness/cli.py#L542)).

**7. Podar allowlist sombreada.** Duas rotinas de merge independentes
(`compile_project`, que rastreia `managed_permissions` em
`compiled-state.json`, e `compile_session_permissions`, que rastreia
`managed_session_permissions` em `compiled-state-session.json`) escrevem no
mesmo `.claude/settings.local.json` sem se enxergarem — nenhuma reconhece
uma entrada da outra como "gerenciada", então uma regra específica
(`Bash(git status)`) nunca é reconhecida como redundante quando uma regra
mais ampla do mesmo tipo (`Bash` nu) já está na lista. A poda entra no sink
único que os dois caminhos já compartilham
([settings_paths.py:182](../../../src/harness/settings_paths.py#L182)),
e remove **só** entradas estritamente subsumidas por uma regra nua de
`Bash`/`Edit`/`Write`/`Read`/`Grep`/`Glob` já presente na mesma lista —
nunca uma regra manual sem essa regra nua correspondente.

## Critérios de aceitação

- [T-01] Hooks compilados usam interpretador com `-S -E`, sem mudar
  `FAIL_CLOSED_SUFFIX` nem o caminho absoluto do interpretador — prova:
  `python -m pytest tests/test_hook_launcher.py -k flags -q`
- [T-02] O docstring de módulo de `boundary_guard.py` cai para 40 linhas ou
  menos, sem remover nenhuma função nem mudar comportamento do hook — prova:
  `python -m pytest tests/test_boundary_guard.py -k docstring -q`
- [T-03] `render_boundary_guard` produz o MESMO texto em chamadas
  sucessivas, em processos Python diferentes — prova:
  `python -m pytest tests/test_boundary_guard.py -k deterministic -q`
- [T-04] `harness compile` deixa de escrever `.harness/hooks/guard_tests.py`
  em disco; `guard_tests.py` continua ausente de `hooks.PreToolUse` (sem
  regressão do Outcome 5 da Fase 2) — prova:
  `python -m pytest tests/test_compiler.py tests/e2e/test_boundary_flow.py tests/e2e/test_fase2_outcomes.py -q`
- [T-05] `audit.py`, `runtime_audit.py` e `team_audit.py` importam
  `Finding`/`Report`/`_PENALTY`/`_finish` de `harness.findings`; as três
  suítes de auditoria continuam verdes sem alterar nenhum teste existente —
  prova:
  `python -m pytest tests/test_findings.py tests/test_audit.py tests/test_runtime_audit.py tests/test_team_audit.py -q`
- [T-06] Em falha de `verify`, só as últimas linhas de stdout/stderr do
  runner aparecem no stderr do comando, com um aviso de quantas linhas
  foram omitidas — prova:
  `python -m pytest tests/test_cli.py -k truncat -q`
- [T-07] Uma entrada `Bash(<comando específico>)` some do
  `settings.local.json` gerado quando `Bash` nu já está na mesma lista de
  `allow`; uma entrada manual sem regra nua correspondente sobrevive intacta
  — prova:
  `python -m pytest tests/test_settings_paths.py -q`
- Nenhuma das sete mudanças altera o resultado de uma decisão de
  permissão (`allow`/`ask`/`deny`) hoje em vigor, exceto a poda cosmética
  declarada em T-07 (que não muda o resultado, só remove redundância) —
  sem regressão em `python -m pytest tests/test_boundary_guard.py -q`.

## Não-objetivos

- Não funde `guard_test_runner.py` em `boundary_guard.py` — muda o floor de
  decisão (2 processos → 1 ponto de decisão), fora do escopo de "flags e
  facas"; é a Onda 3 do laudo de origem.
- Não reescreve `AGENTS.md` nem mexe em `session_start.py`/`progress.md` —
  é a Onda 2, e compartilha arquivo com a US-1 do P0
  (`docs/project/USER-STORY-p0-friccao-ciclo-2026-07-30.md`).
- Não unifica `_evaluate_bash`/`_evaluate_powershell` nem embute
  `review.py` via `getsource` no `boundary_guard.py` — Onda 3.
- Não mexe nas `skills/*` nem em `docs/plugin/GUIDE.md`/`TUTORIAL.md`/
  `ARCHITECTURE.md` além das 3 menções a `guard_tests.py` que ficam
  obsoletas por T-04 — o resto da consolidação de docs é Onda 4.
- Não afrouxa nenhuma regra de floor (rede, segredos, branch protegida,
  push fora do contrato). Nenhum `deny` existente vira `allow`.
- Não muda o algoritmo de merge "não-destrutivo" documentado em
  `session_permissions.py` além da poda estritamente definida em T-07 —
  regras manuais genuínas (sem regra nua correspondente) continuam
  preservadas exatamente como hoje.
- Não expõe `harness audit --all` nem consolida a SAÍDA dos quatro
  auditores — T-05 compartilha só a definição de `Finding`/`Report`, a
  interface de comando não muda.

## Unknowns

- Nenhum. Alvo é o próprio repositório do harness-creator; `repo-profile.json`
  já existe e não traz `unknowns` pendentes.
