# Auditoria — harness-creator (plugin) — 2026-07-19

Gerada via skill `skill-audit` (auditor + verificador independentes, isenta, sem contexto de
sessões anteriores). Consolidada com os 2 itens pendentes de
`ROADMAP-dogfood-elegant-heisenberg.correction.backlog.md` que a auditoria automática não cobre
(o item 1 daquele backlog — UnicodeDecodeError — já saiu confirmado pela própria auditoria,
itens 1 e 2 abaixo; não duplicado).

## Plano

- `src/harness/verify.py:136` — Adicionar `encoding="utf-8", errors="replace"` ao `subprocess.run` que executa `verify_cmd` — C4 — outcome: `harness verify` deixa de derrubar com `UnicodeDecodeError` quando o `verify_cmd` produz saída não-ASCII num console cp1252 do Windows.
- `src/harness/contract.py:316` — Mesmo fix (`encoding="utf-8", errors="replace"`) no `subprocess.run` de `_dry_check_verify_cmd` — C4 — outcome: `compile-contract --dry-run-verify` deixa de poluir stderr com traceback de thread leitora em `verify_cmd` com saída não-ASCII.
- `src/harness/boundary_guard.py:439-1088` — Extrair a string retornada por `render_boundary_guard()` (cópia integral, stdlib-only, da lógica de runtime floor/feature-lock já implementada de forma importável nas linhas 100-434) para um template único gerado a partir da versão importável — C1/C5 — outcome: mudança de política do runtime floor passa a ser feita em um único lugar, eliminando risco das duas cópias divergirem silenciosamente.
- `config/harness.yaml:17-87` — Remover as seções `sandbox`/`routing`/`eet`/`telemetry`/`mcp` (era congelada, já removida do código-fonte) ou movê-las para `docs/roadmap-autonomous.md` como referência de roadmap — C1/C5 — outcome: o `harness.yaml` do próprio plugin deixa de descrever sandbox Docker e roteamento de modelo sem nenhuma linha de código por trás.
- `skills/plan/SKILL.md:61-138` — Mover os templates literais de `spec.md`/`Plans.md` para `references/`, deixando no `SKILL.md` só os passos procedurais — C6 — outcome: `SKILL.md` cai de 229 linhas para abaixo do limiar de ~150; template só entra no contexto do modelo quando a etapa de escrever contrato é de fato alcançada.
- `src/harness/verify.py` (novo comando) — Adicionar flag opt-in `harness verify <id> --mark-passed` que grava `passes: true` no `feature_list.json` quando `exit_code == 0` — C1/C6 — outcome: sessão orquestradora sequencial deixa de precisar editar `feature_list.json` manualmente por tarefa; default sem a flag preserva comportamento atual (sem corrida entre agentes paralelos).
- `skills/plan/SKILL.md` (Passo 6/7) — Adicionar nota curta sobre `verify_cmd` de build/test compilado falhar por lock de arquivo (`MSB3027`, `EBUSY`) quando um processo do próprio projeto-alvo está rodando — C6 — outcome: agente que bate nesse erro reconhece a causa (processo do usuário, não bug de código) e pergunta antes de encerrar o processo, em vez de tratar como falha de build.

## Backlog

| # | Item | Arquivo | Esforço (S/M/L) | Risco (baixo/médio/alto) | Outcome |
|---|------|---------|------------------|---------------------------|---------|
| 1 | UnicodeDecodeError em `run_verify` | src/harness/verify.py:136 | S | baixo | `harness verify` não crasha mais em saída não-ASCII no Windows sem `PYTHONUTF8=1`. |
| 2 | UnicodeDecodeError em `_dry_check_verify_cmd` | src/harness/contract.py:316 | S | baixo | `--dry-run-verify` não produz mais traceback de thread leitora em saída não-ASCII. |
| 3 | Lógica de fronteira duplicada em string + módulo | src/harness/boundary_guard.py:439-1088 | L | médio | Política de runtime floor/feature-lock passa a existir numa fonte única, não duas cópias hand-synced. |
| 4 | Config do próprio plugin referencia modo de execução removido | config/harness.yaml:17-87 | S | baixo | `harness.yaml` do plugin para de descrever sandbox Docker/routing/EET/telemetria sem código correspondente. |
| 5 | Dockerfile órfão do sandbox removido | sandbox/Dockerfile | S | baixo | Repo deixa de carregar um Dockerfile sem consumidor, referenciado só por um comentário em config morta. |
| 6 | SKILL.md acima do limiar de progressive disclosure | skills/plan/SKILL.md:61-138 | M | baixo | Template de contrato só entra no contexto do modelo ao escrever o contrato, não a cada trigger da skill. |
| 7 | Nenhum comando marca `passes:true` automaticamente | src/harness/verify.py | M | baixo | Flag `--mark-passed` elimina edição manual repetida do `feature_list.json` em sessão sequencial única. |
| 8 | `dotnet build`/`test` falha se API do projeto-alvo estiver rodando | skills/plan/SKILL.md | S | baixo | Agente reconhece lock de DLL como processo do usuário, não bug, antes de agir. |

Verificação: 6 confirmados, 0 ajustados, 0 refutados (removidos) — itens 7 e 8 vêm do backlog de
dogfood (`ROADMAP-dogfood-elegant-heisenberg.correction.backlog.md`), não passaram pelo
verificador da skill-audit (achados já eram evidência de reprodução real, não achados de leitura
estática).
