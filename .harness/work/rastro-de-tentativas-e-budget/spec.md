---
slug: rastro-de-tentativas-e-budget
approved_by: Daniel Seto
approved_at: 2026-08-09T04:18:41Z
stop_conditions:
  - "3 falhas consecutivas da mesma suíte de teste"
  - "verify_cmd referenciado não existe no repo-profile"
  - "mudança exigiria alterar o runtime floor do boundary_guard"
---

# Spec: Rastro de tentativas falhas + disjuntor mecânico (`harness budget`)

## Resumo executivo
Hoje, quando uma verificação falha, nada fica registrado — o harness só grava
sucesso. Com esta demanda, cada falha deixa um rastro estruturado em disco, e
um novo comando (`harness budget`) lê esse rastro e responde de forma objetiva
se o agente deve continuar tentando ou parar e chamar o humano. O limite de
tentativas, que hoje é só texto de orientação, passa a ser contado por máquina.

## Escopo
Incremento 1 do design de loop engineering
(`docs/reference/loop-engineering-design.md`, §5.1 histórico de tentativas,
§4.2 budget mecânico, §8.2 regra do padrão repetido). Antecipa o item 3 da
Fase 6 do `docs/roadmap-autonomous.md` ("verify passa a gravar tentativas
FALHAS"). Quatro peças:

1. **Rastro de tentativas** — novo módulo `src/harness/attempts.py`:
   - Caminho: `.harness/attempts/<contract>/<feature_id>.jsonl` (escopo por
     contrato, espelhando `evidence_path` — evidência de um contrato nunca
     conta para outro).
   - Registro de falha (append, uma linha JSON):
     `{"result": "fail", "contract", "feature_id", "recorded_at",
     "verify_cmd", "exit_code", "failure_line", "failure_signature",
     "files_hash"}`. `failure_line` = primeira linha não-vazia de stderr
     (fallback: stdout), truncada em 300 chars. `failure_signature` = sha256
     (12 hex) da `failure_line` normalizada (strip + espaços colapsados).
   - Registro de sucesso (append): `{"result": "pass", "recorded_at",
     "files_hash"}` — encerra a sequência de falhas consecutivas. O arquivo
     nunca é apagado no verde: o histórico é o produto.
   - Leitura: contadores derivados do tail do jsonl — total de falhas,
     falhas consecutivas (desde o último `pass`), sequência da mesma
     `failure_signature`.

2. **Gravação em `run_verify`** (`src/harness/verify.py`):
   - `VerifyFailedError` (exit ≠ 0) passa a gravar o registro de falha ANTES
     de levantar a exceção. A invariante atual "NADA é gravado no vermelho"
     muda deliberadamente — docstring atualizada.
   - Sucesso grava o registro `pass` junto com a evidência, com o MESMO
     `recorded_at` da evidência (regra existente: nunca dois relógios para o
     mesmo evento).
   - Timeout (`VerifyError`) NÃO grava tentativa — falha transiente/infra é
     taxonomia do Incremento 5, fora deste escopo.
   - Falha ao gravar o rastro nunca faz a verificação mudar de resultado
     (mesma regra do sync do progress.md: rastro é subproduto, não gate).

3. **Stop conditions tipadas** (`src/harness/contract.py`):
   - O frontmatter `stop_conditions:` passa a aceitar itens dict além de
     string: `{type: consecutive_verify_failures, n: 3}` e
     `{type: same_failure_signature, n: 3}`. Strings continuam aceitas como
     advisory (comportamento atual intacto).
   - Dict com `type` fora dos dois suportados, ou `n` não-inteiro/≤0 →
     `ContractError` na compilação (fail-closed: typo não vira advisory
     silencioso).
   - `compile_contract` grava no `feature_list.json` a chave top-level
     `"stop_conditions": {"typed": [...], "advisory": [...]}` — chave nova,
     aditiva, nenhum consumidor atual quebra.
   - `get_stop_conditions` (acessor existente) segue devolvendo SÓ as
     strings advisory — compatibilidade com quem já chama.

4. **Verbo `harness budget`** (novo `src/harness/budget.py` + subparser em
   `cli.py`):
   - `harness budget --dir <alvo> --feature <id>` — SÓ LEITURA (padrão
     `supervisor.py`: nunca escreve, nunca roda subprocess).
   - Lê o jsonl + `stop_conditions.typed` do `feature_list.json` +
     `governance.budget.max_green_iterations` do `harness.yaml`.
   - Tetos efetivos: `same_failure_signature` tipada (default 3 se ausente);
     `consecutive_verify_failures` tipada (default `max_green_iterations`).
     A tipada, quando presente, VENCE o default — é o contrato falando.
   - Saída JSON: `{"feature_id", "contract", "attempts_total",
     "consecutive_failures", "same_signature_streak", "limits": {...},
     "verdict", "reason"}`. Vereditos: `continue` | `stop_same_failure` |
     `stop_iterations`. Sem rastro → `continue` com contadores zerados.
     `reason` é frase para humano, não código.
   - `max_green_iterations` deixa de ser campo sem consumidor: é o teto de
     iterações do veredito.

5. **Bloco Tentativas no `progress.md`** (`src/harness/templates.py`):
   - Nova seção gerenciada `### Tentativas — <feature_id>`, regenerada a
     partir do jsonl a cada falha gravada (uma linha por tentativa:
     `N. exit <code> — <failure_line> (sig <12hex>)`).
   - No `pass`, o bloco da feature é removido (fatia saiu de "em
     andamento"; o histórico permanente é o jsonl).
   - Mesmas regras dos irmãos `update_progress_status`/`append_progress_note`:
     no-op silencioso se o arquivo não existe, nunca faz o verify falhar.

6. **Lifecycle passo 10** (`src/harness/lifecycle.py`): o texto do passo 10
   passa a mandar consultar `harness budget --feature <id>` a cada falha do
   loop de autocorreção e obedecer o veredito — em vez da prosa atual
   "respeitando as stop conditions". Strings advisory continuam citadas como
   condição adicional interpretada pelo agente.

Testes novos seguem o padrão da suíte: um teste = uma REGRA com tabela de
casos (`Case`/`_expect`), não um def por caso.

## Critérios de aceitação
- Módulo attempts grava/lê o rastro e deriva os 3 contadores:
  `pytest tests/test_attempts.py -q` sai 0.
- `run_verify` grava falha no vermelho e `pass` no verde sem mudar
  resultado nem evidência: `pytest tests/test_verify_attempts.py -q` sai 0.
- Parse + compilação das stop conditions tipadas (incluindo fail-closed de
  tipo desconhecido): `pytest tests/test_contract_stop_conditions.py -q`
  sai 0.
- `harness budget` devolve os 3 vereditos nos cenários de tabela:
  `pytest tests/test_budget.py -q` sai 0.
- Bloco Tentativas renderiza do jsonl e some no pass:
  `pytest tests/test_progress_attempts.py -q` sai 0.
- Lifecycle regenerado cita `harness budget` no passo 10:
  `pytest tests/test_lifecycle.py -q` sai 0.
- Regressão do escopo tocado: `pytest tests/test_verify.py
  tests/test_contract.py tests/test_cli.py tests/test_templates.py -q`
  sai 0.

## Não-objetivos
- Enforcement do veredito por hook (Stop bloqueante / PreToolUse) — Fase 6
  item 4; aqui o disjuntor é consultável, obedecê-lo é papel do lifecycle.
- Driver multi-sessão (`harness work`), ledger de custo, EET.
- Taxonomia transiente/infra (timeout segue não gravando tentativa).
- Métrica de convergência (§4.3), `harness reconcile`, `decisions.md`/
  `lessons.md`, `harness escalate` — Incrementos 2, 4, 5 e 6.
- `.harness/stop-conditions.json` como arquivo separado (roadmap Fase 6):
  a forma compilada vive dentro do `feature_list.json`.
- Campo `approach` no registro de falha (quem descreve abordagem é o
  agente no progress.md; o jsonl guarda o que a máquina observou).

## Unknowns
- (nenhum — profile sem unknowns; comandos de teste confirmados pelo
  pyproject.toml)
