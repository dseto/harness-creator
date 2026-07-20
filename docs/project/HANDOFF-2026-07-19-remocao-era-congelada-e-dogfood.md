# Handoff — 2026-07-19 — Remoção da era congelada + dogfood real (Story 2.6)

Resumo da sessão para continuar o trabalho no **harness-creator**. Estado atual:
versão `0.16.0`, testada ponta a ponta contra um projeto consumidor real
(`elegant-heisenberg`), com 3 achados de fricção pendentes de correção.

## 1. O que foi feito, em ordem

### 1.1 Skill de auditoria criada (fora deste repo)
Antes de mexer no harness-creator, foi criada a skill `skill-audit`
(`C:\Users\danie\.claude\skills\skill-audit\`) — audita qualquer skill/plugin/MCP
de Claude Code (arquitetura, clareza, segurança, erros, manutenção, simplicidade)
com um subagent auditor + um subagent verificador independente (baliza os
achados do auditor contra o código real antes de reportar). Ver
`C:\Projetos\unlucky-morpheus\SPEC-skill-audit.md` para a spec completa. **Não
é parte do harness-creator**, mas foi a ferramenta usada para auditar este
repo (seção 1.2).

### 1.2 Auditoria do harness-creator (2 rodadas independentes)
Duas auditorias isentas (auditor + verificador, sem contexto uma da outra)
convergiram no mesmo núcleo de achados. Verificação dupla: **16/16 achados
confirmados, 0 refutados**. Achado de maior prioridade: `pyproject.toml`
tinha `anthropic`/`mcp`/`docker` como dependências **obrigatórias**, usadas
só pelo modo de execução autônoma ("era congelada" — `orchestrator.py` +
sandbox Docker + TDD-loop chamando a API Anthropic diretamente), que o
projeto já tinha pivotado a abandonar (documentado em `PLAN.md`,
`ARCHITECTURE.md`, `README.md`, `CHANGELOG.md` como "congelado").

### 1.3 Remoção da era congelada — 3 commits, cada um com gate objetivo
Gate usado em toda fase: `import harness.compiler` **sem** docker/anthropic/mcp
instalados tem que funcionar (`IMPORT_CLEAN`) + suíte de testes verde.
Padrão: Sonnet (implementa) → Opus (valida, roda o gate real, não confia no
relato do implementador).

- **`938df48`** — Fase 0: desacopla o compilador do código congelado. Achado
  chave: o compilador só usava a função pura `_glob_to_regex` de
  `verification/tdd_loop.py`, mas esse arquivo tinha imports top-level que
  arrastavam `docker` pro load-path do compilador. Move `_glob_to_regex` →
  novo `src/harness/patterns.py` (só stdlib). Sem deleção.
- **`95d9cde`** — Fase 1 (fundida com a fase de wiring, ver nota abaixo):
  deleta 31 arquivos (`orchestrator.py`, `context/`, `routing/`,
  `telemetry/`, `tools/`, `verification/{tdd_guard,tdd_loop}`,
  `governance/{sandbox,budget}` + 11 testes que dependiam deles) e remove o
  wiring (`harness run` do `cli.py`, `AgentOrchestrator` de `__init__.py`).
  **Nota de processo:** a primeira tentativa (deletar só o código, sem tocar
  wiring) foi corretamente bloqueada pelo implementador (Regra de Ouro:
  `cli.py`/`__init__.py` ainda importavam `orchestrator`) — Opus então
  provou que esses imports eram *lazy* (dentro do branch `run`), então a
  fase foi refeita fundindo deleção + wiring numa passada atômica. Lição:
  **não separe "deletar código" de "remover as últimas referências a ele"
  em fases distintas** quando as referências são lazy — cria um estado
  incoerente que trava a Regra de Ouro por engano.
- **`3cde0d3`** — Fase final: remove `anthropic`/`mcp`/`docker` do
  `pyproject.toml`, 8 classes órfãs de `config.py` (`SandboxConfig`,
  `RoutingConfig`, `EETConfig`, `ContextConfig`, `GenerationConfig`,
  `TelemetryConfig`, `MCPConfig`, `MCPServerConfig`), seções congeladas de
  `README.md`/`ARCHITECTURE.md`. **`PLAN.md` e `docs/roadmap-autonomous.md`
  mantidos intactos por decisão do usuário** — são o roadmap de reintrodução
  futura do modo autônomo, não código morto.

Resultado líquido: 459→414 testes (44 eram só do modo congelado), zero
regressão no modo compilador.

### 1.4 Correções de qualidade — `cf49a04`
4 achados restantes da auditoria (confirmados por verificação dupla),
corrigidos com prova de execução real do hook gerado (não só leitura):
1. `boundary_guard.py` `_split_shell_segments`: passa a tratar `\n`/`\r`
   como operador de controle (antes, `git status\n<comando arbitrário>`
   escapava do matching de prefixo).
2. `boundary_guard.py` `main()`: try/except ao redor do corpo, emitindo
   `deny` explícito em erro interno (antes: exceção não tratada = fail-open,
   Claude Code deixava a tool call passar).
3. `verify.py`: `subprocess.TimeoutExpired` agora vira `VerifyError` com
   comando+timeout na mensagem (antes: traceback cru no CLI).
4. `compiler.py`/`lifecycle.py`/`teams.py` (×2): `re.sub(block, ...)` →
   `re.sub(lambda _: block, ...)` — `\` no conteúdo do usuário (paths
   Windows) não é mais interpretado como escape de replacement regex.

### 1.5 Bump de versão — `a779ff2` — `0.16.0`
Sincronizado nos 4 arquivos que precisam bater (`pyproject.toml`,
`src/harness/__init__.py`, `.claude-plugin/plugin.json`,
`.claude-plugin/marketplace.json` — há um comentário no `__init__.py`
avisando exatamente disso, "já aconteceu uma vez" dessincronizar).
CHANGELOG.md fechado com a entrada completa (remoção + correções).

**Refresh do plugin instalado** (não é passo do repo, é da sessão do Claude
Code local): `claude plugin marketplace update harness-creator-local` +
`claude plugin update harness-creator@harness-creator-local` → cache em
`C:\Users\danie\.claude\plugins\cache\harness-creator-local\harness-creator\0.16.0\`
confirmado sem os módulos frozen. **Precisa restart da sessão do Claude
Code pra valer** (aviso do próprio comando) — mas na prática, comandos
`python -m harness.cli ...` que setam `PYTHONPATH` manualmente para o path
de `0.16.0` já pegam o código novo sem restart (é só a skill/hook injetada
automaticamente via `$CLAUDE_PLUGIN_ROOT` que pode ainda apontar pro path
antigo até reiniciar).

### 1.6 Dogfood real — Story 2.6 em `elegant-heisenberg`
Primeiro teste ponta a ponta do 0.16.0 contra um projeto consumidor real
(não é o `test_e2e_dogfood` interno do harness-creator — é uso de verdade).
Fluxo completo exercitado: `/harness-creator:plan` → entrevista → aprovação
humana → `compile-contract --dry-run-verify` → `compile-session` → loop
`supervise`/`verify` nas 7 tarefas do contrato → regressão final.

Resultado: 7/7 tarefas verificadas (evidência em
`elegant-heisenberg/.harness/evidence/T-0X.json`), commit
`4900f7f` empurrado pra `origin/master`. Regressão: 137/137 testes frontend,
116/116 testes de integração backend, zero quebra em código pré-existente.

## 2. Achados de fricção do dogfood — PENDENTES, não implementados ainda

Registrados em `ROADMAP-dogfood-elegant-heisenberg.correction.backlog.md`
(raiz deste repo). Resumo — **2 são bugs reais do harness-creator, 1 é gap
de documentação**:

1. **`UnicodeDecodeError` (cp1252) em subprocess de verify_cmd no Windows**
   — bug real, 2 locais: `verify.py:136-141` e `contract.py:316-323`, ambos
   `subprocess.run(..., text=True, ...)` sem `encoding=` explícito. Fix:
   `encoding="utf-8", errors="replace"`. Reproduzido e confirmado nesta
   sessão (some com `PYTHONUTF8=1` setado externamente — contorno já
   documentado no projeto consumidor, nunca corrigido na fonte).
2. **Nenhum comando marca `passes:true` automaticamente** — `harness verify`
   grava evidência mas não escreve no `feature_list.json`; é intencional
   (evita corrida entre agentes paralelos), mas obriga a sessão
   orquestradora a editar o JSON manualmente a cada tarefa mesmo em fluxo
   sequencial single-agent. Proposta: flag opt-in `harness verify
   <id> --mark-passed`.
3. **`dotnet build`/`dotnet test` falha se a API do projeto-alvo estiver
   rodando** (lock de DLL, `MSB3027`) — não é bug de código, é gap de
   orientação. Proposta: nota em `skills/plan/SKILL.md`/`AGENTS.md` gerado,
   sem lógica nova.

## 3. Próximos passos sugeridos

1. Implementar os 3 itens do backlog (mesmo padrão desta sessão: Sonnet
   implementa, Opus valida com gate real, não só leitura de código).
2. Bump de versão de novo (0.16.0 → 0.16.1 provavelmente — são fixes, não
   breaking) nos 4 arquivos sincronizados + `claude plugin update`.
3. Re-rodar `--dry-run-verify` num `verify_cmd` com saída UTF-8 não-ASCII
   sem `PYTHONUTF8` setado, pra confirmar o item 1 resolvido de verdade
   (é o teste que reproduziu o bug nesta sessão).
4. Considerar dogfood De novo depois do fix — próxima story natural do
   `elegant-heisenberg` é a 2.7 (`.harness/work/fase2-complemento/
   USER_STORIES_FASE2_COMPLEMENTO.md`), mas não é obrigatório usá-la
   especificamente; qualquer contrato novo serve pra confirmar os fixes.

## 4. Estado dos repos ao final desta sessão

- `C:\Projetos\Harness-creator` — branch local, 4 commits à frente do que
  existia no início da sessão (`938df48`, `95d9cde`, `3cde0d3`, `cf49a04`,
  `a779ff2` — 5 na verdade). **Não verificado se há remote/push pendente
  neste repo** — checar `git status -sb` antes de continuar.
- `C:\Projetos\elegant-heisenberg` — `master` sincronizado com
  `origin/master` (`4900f7f` empurrado).
- Plugin instalado: `harness-creator@harness-creator-local` em `0.16.0`,
  cache em
  `C:\Users\danie\.claude\plugins\cache\harness-creator-local\harness-creator\0.16.0\`.
  Diretórios órfãos `0.15.7`/`0.15.8` no cache — `claude plugin prune`
  limparia, não urgente.
