# Plans: `governance.extra_allowed_commands`

Backlog do contrato `extra-allowed-commands`. Formato parseável por
`src/harness/contract.py` (`## [T-XX]` + `files`/`verify`/`depends`).
Cadeia sequencial: schema → runtime hook (boundary_guard) → enumeração
nativa (session_permissions) → docs/versão → prova E2E. Cada camada depende
da anterior estar correta (o loader novo, escrito em T-02, é reusado por
T-03 via import).

Convenção de trabalho (vale para todas as tarefas): teste PRIMEIRO no
arquivo de teste correspondente, depois a implementação mínima que o faz
passar; mensagens/comentários em pt-BR, chaves JSON/YAML em inglês.

## [T-01] Schema: `GovernanceConfig.extra_allowed_commands`
- files: `src/harness/config.py`, `tests/test_config.py`
- verify: `python -m pytest tests/test_config.py -q`

Detalhe: `tests/test_config.py` é arquivo NOVO (não existe teste de
`config.py` hoje). Campo `extra_allowed_commands: list[str] = Field(default_factory=list)`
em `GovernanceConfig`. Testes: (a) `HarnessConfig.model_validate({})` produz
`governance.extra_allowed_commands == []`; (b)
`HarnessConfig.model_validate({"governance": {"extra_allowed_commands": ["python -m mar_committee"]}})`
preserva a lista na ordem declarada; (c) `yaml.safe_load` de um YAML real
(string multi-linha com a chave em lista) + `model_validate` end-to-end,
provando que o parsing YAML→Pydantic funciona (não só o dict Python direto).

## [T-02] `boundary_guard.py`: loader + parametrização do hook gerado + wiring em `_evaluate_bash`/`_evaluate_powershell`
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `python -m pytest tests/test_boundary_guard.py -q`
- depends: T-01

Detalhe:
1. `load_extra_allowed_commands(target_dir: Path) -> list[str]` (Python real,
   importável): lê `target_dir/.harness/harness.yaml` se existir; `yaml.safe_load`
   + `HarnessConfig.model_validate`; devolve `list(config.governance.extra_allowed_commands)`;
   devolve `[]` em QUALQUER falha (arquivo ausente, `yaml.YAMLError`,
   `pydantic.ValidationError`, ou raiz do YAML não sendo dict) — nunca lança.
   Precisa de `import yaml` e `from harness.config import HarnessConfig` no
   topo do módulo (sem ciclo: `config.py` não importa `boundary_guard`).
2. `render_boundary_guard(extra_allowed_commands: list[str] | None = None) -> str`:
   novo parâmetro; um bloco novo (f-string, interpolado — diferente do
   `middle` hoje, que é literal fixo) injeta
   `EXTRA_ALLOWED_COMMANDS = {list(extra_allowed_commands or [])!r}` logo
   após a definição de `FIXED_HARNESS_SEQUENCES` no script gerado. As DUAS
   linhas `allowed_sequences = (FIXED_GIT_SEQUENCES + FIXED_HARNESS_SEQUENCES + [...])`
   (uma em `_evaluate_bash`, outra em `_evaluate_powershell`) ganham
   `+ [_tokenize_command(c) for c in EXTRA_ALLOWED_COMMANDS]` no final —
   mesma variável, um único ponto de derivação para as duas tools.
3. `install_boundary_guard(target_dir)`: chama
   `load_extra_allowed_commands(target_dir)` e repassa a `render_boundary_guard`.
4. Testes novos em `test_boundary_guard.py` (reusar `_write_feature_list`/
   `_write_profile`/`_script` já existentes, mais um helper novo
   `_write_harness_yaml(target, extra_allowed_commands)`):
   - contrato ativo + `extra_allowed_commands=["python -m mar_committee"]`
     sem `verify_cmd` cobrindo → `Bash("python -m mar_committee --help")`
     allow, `Bash("python -m mar_committee config-show")` allow (AC-2).
   - `Bash("mar_committee --help")` (sem `python -m`) → deny (AC-3, prefixo
     exato).
   - `extra_allowed_commands=["git push"]` → `Bash("git push origin main")`
     continua deny com motivo do runtime floor (AC-4) — floor decide ANTES
     de `allowed_sequences` ser consultado, sem código novo, só o teste.
   - mesma checagem para `PowerShell` (comando equivalente via
     `_evaluate_powershell`, cobrindo o segundo consumidor de
     `EXTRA_ALLOWED_COMMANDS`).
   - sem `.harness/harness.yaml` no alvo → comportamento idêntico ao atual
     (AC-5); com `.harness/harness.yaml` malformado (YAML inválido) → idem,
     sem exceção.

## [T-03] `session_permissions.py`: wiring de `extra_allowed_commands` na enumeração de `.claude/settings.json`
- files: `src/harness/session_permissions.py`, `tests/test_session_permissions.py`
- verify: `python -m pytest tests/test_session_permissions.py -q`
- depends: T-02

Detalhe: importar `load_extra_allowed_commands` de `harness.boundary_guard`
(mesmo import que já traz `is_floor_bash_command`/`is_floor_secret_path`).
`render_session_permissions(feature_list, profile, extra_allowed_commands=None)`
ganha parâmetro novo; cada entrada vira `f"Bash({cmd}*)"` (mesmo estilo sem
espaço de `_HARNESS_CLI_ALLOW`), adicionado à lista `allow` ANTES do filtro
final `_passes_runtime_floor_filter` — uma entrada de floor declarada em
`extra_allowed_commands` é removida pelo MESMO filtro que já protege
`verify_cmd`/`files[]`/instalação, sem código de exceção novo (AC-6, metade
"floor filtrado"). `compile_session_permissions(target_dir)` chama
`load_extra_allowed_commands(target_dir)` e repassa. Testes novos: (a)
`render_session_permissions` com `extra_allowed_commands=["python -m mar_committee"]`
produz `"Bash(python -m mar_committee*)"` em `allow`; (b) com
`extra_allowed_commands=["git push"]`, a entrada NÃO aparece em `allow` (
floor filtrado); (c) `compile_session_permissions` fim-a-fim com um
`.harness/harness.yaml` real no `tmp_path` confirma o mesmo resultado lendo
do disco.

## [T-04] Docs e versão 0.17.6 — gate de regressão total
- files: `docs/reference/CHANGELOG.md`, `README.md`, `pyproject.toml`, `.claude-plugin/plugin.json`
- verify: `python -m pytest tests -q`
- depends: T-03

Detalhe: bump `0.17.5 → 0.17.6` em `pyproject.toml` e
`.claude-plugin/plugin.json` (feature aditiva, mesma faixa de versionamento
das entradas 0.17.3/0.17.4/0.17.5 já no changelog). Entrada nova no topo de
`docs/reference/CHANGELOG.md` no padrão das anteriores (`### Adicionado`),
citando o motivador real (dogfood `entebate`/`elegant-heisenberg`, CLI
bloqueado mesmo com contrato `passes:true`). Atualizar a linha de versão no
topo do `README.md` (`**v0.17.1** · [CHANGELOG](...)` → versão nova). AC-7
(ruff) roda junto desta tarefa. O verify é a suíte INTEIRA — zero regressão
(AC-8).

## [T-05] E2E real (gate final da demanda): dogfood do cenário `entebate`, evidência commitada
- files: `tests/e2e/test_extra_allowed_commands_e2e.py`, `tests/e2e/evidence/extra-allowed-commands-dogfood-2026-07-22.md`
- verify: `python -m pytest tests/e2e/test_extra_allowed_commands_e2e.py -q`
- depends: T-04

Detalhe (regra permanente do ROADMAP — fase fecha com prova real, não
sintética, mesmo padrão do `T-08` do contrato `preflight-skill`): monta em
disco um mock do cenário motivador real — repo Python mínimo, contrato
compilado (`.harness/feature_list.json` com 1 feature `passes:true` e
`verify_cmd` que NÃO cobre o CLI do produto), `.harness/repo-profile.json`
mínimo, e `.harness/harness.yaml` com
`governance.extra_allowed_commands: ["python -m mar_committee"]`. Roda
`install_boundary_guard` de verdade (função real do pacote, não mock),
depois invoca o script instalado via `subprocess.run` DE VERDADE com payload
`tool_name=Bash` duas vezes: (a) `command="python -m mar_committee config-show"`
→ espera `permissionDecision=allow`; (b) `command="algum-comando-nao-declarado --flag"`
→ espera `permissionDecision=deny`. Grava
`tests/e2e/evidence/extra-allowed-commands-dogfood-2026-07-22.md` com os
dois JSONs de decisão reais colados, o comando `subprocess` executado, e a
data — evidência legível por humano sem reler código de teste, commitada no
repo. Não usa `HARNESS_E2E_DOGFOOD` (não invoca claude/dotnet — barato, roda
no gate padrão).
