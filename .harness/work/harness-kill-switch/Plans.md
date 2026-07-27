## [T-01] Módulo core do kill-switch (`killswitch.py`)
- files: `src/harness/killswitch.py`, `tests/test_killswitch.py`
- verify: `pytest tests/test_killswitch.py -q`

Novo módulo `src/harness/killswitch.py` (stdlib-only, sem importar outros
módulos do pacote para evitar ciclo). Expõe:
- `SENTINEL_RELATIVE_PATH = ".harness/harness.disabled"`.
- `is_disabled(target_dir) -> bool` — sentinel existe.
- `disable(target_dir, note="") -> Path` — grava o sentinel como JSON
  `{"disabled_at": <ISO8601>, "note": <note>}` (idempotente; sobrescreve).
- `enable(target_dir) -> bool` — remove o sentinel se existir; devolve se
  removeu.
- `status(target_dir) -> dict` — `{"disabled": bool, "sentinel": <path>,
  "disabled_at": ..., "note": ...}`.
- `DISABLED_CHECK_SRC: str` — constante de texto contendo a `def
  _harness_disabled():` stdlib-only, ancorada por `__file__`
  (`Path(__file__).resolve().parent.parent / "harness.disabled"`), para ser
  embutida literalmente por cada render de hook (T-03/T-04/T-05). Uma única
  fonte de verdade do snippet.

## [T-02] CLI `harness disable | enable | status`
- files: `src/harness/cli.py`, `tests/test_cli.py`
- verify: `pytest tests/test_cli.py -q`
- depends: T-01

Adiciona três subparsers em `main()` (`disable` com `--note`, `enable`,
`status`), cada um com `--dir` (default "."), delegando a
`harness.killswitch`. `disable`/`enable`/`status` imprimem JSON de resultado
e saem com 0. Import lazy de `harness.killswitch` dentro do branch (mesmo
padrão dos demais comandos).

## [T-03] boundary_guard: short-circuit + floor anti-auto-desativação + gitignore
- files: `src/harness/boundary_guard.py`, `tests/test_boundary_guard.py`
- verify: `pytest tests/test_boundary_guard.py -q`
- depends: T-01

Na versão IMPORTÁVEL (testável via pytest) e, espelhado, na string do
`render_boundary_guard()` (regra "muda dos dois lados" do módulo):
- Novos helpers floor: `is_floor_disable_sentinel_path(path)` (path normaliza
  para `.harness/harness.disabled`), `is_floor_disable_command(command)`
  (tokens contêm sequência `["harness","disable"]` ou
  `["python","-m","harness.cli","disable"]`), `is_floor_bash_disable_redirect(command)`
  (redirecionamento/`tee` cujo alvo casa o sentinel — espelha
  `is_floor_bash_secret_redirect`). Embutir no script gerado (adicionar à
  lista de `inspect.getsource(...)` em `render_boundary_guard`, OU embutir
  como texto — manter o padrão existente do arquivo).
- Short-circuit no topo do `main()` do script gerado: se
  `_harness_disabled()` (via `DISABLED_CHECK_SRC` de T-01), imprime `allow`
  com razão "harness desativado pelo usuário (.harness/harness.disabled)" e
  retorna — precede todo o resto.
- `_evaluate_file`: negar quando `is_floor_disable_sentinel_path(path)` (junto
  ao floor de segredo, no topo). `_evaluate_bash` e `_evaluate_powershell`:
  negar quando `is_floor_disable_command` / `is_floor_bash_disable_redirect`
  (junto aos floors existentes). Como o short-circuit já retornou allow
  quando o sentinel existe, esses denies só rodam com o harness ativo — sem
  contradição.
- `install_boundary_guard`: garantir (idempotente) que `.harness/.gitignore`
  contém `harness.disabled`, mesmo padrão do `.gitignore` de scratch já
  criado ali.

## [T-04] session_start + stop_hook respeitam o sentinel
- files: `src/harness/session_start.py`, `src/harness/stop_hook.py`, `tests/test_session_start.py`, `tests/test_stop_hook.py`
- verify: `pytest tests/test_session_start.py tests/test_stop_hook.py -q`
- depends: T-01

Em `render_session_start_hook()` e `render_stop_hook()`: embutir
`DISABLED_CHECK_SRC` (T-01) e, no topo do `main()` do script gerado, se
`_harness_disabled()`, retornar sem imprimir nada (SessionStart/Stop injetam
contexto — no-op = não injetar). Ancoragem por `__file__` (o hook mora em
`.harness/hooks/`), não pelo `cwd` do payload.

## [T-05] guard_tests + guard_test_runner respeitam o sentinel
- files: `src/harness/compiler.py`, `tests/test_compiler.py`
- verify: `pytest tests/test_compiler.py -q`
- depends: T-01

Em `_render_guard_tests()` e `_render_guard_test_runner()`: embutir
`DISABLED_CHECK_SRC` (T-01) e, no topo do `main()` de cada script gerado, se
`_harness_disabled()`, imprimir `allow` (são hooks `PreToolUse`) e retornar —
antes de qualquer matching de teste/runner. Ancoragem por `__file__`.

## [T-06] Regressão completa + CHANGELOG
- files: `docs/reference/CHANGELOG.md`
- verify: `pytest tests -q`
- depends: T-01, T-02, T-03, T-04, T-05

Entrada na seção "Não lançado" do CHANGELOG descrevendo o kill-switch
(comando externo, sentinel gitignored, floor anti-auto-desativação com o
residual do floor de segredo). Critério de aceitação top-level: suíte
completa verde (`pytest tests -q`) com todos os hooks e o floor novo.
