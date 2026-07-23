"""Kill-switch externo do harness — comando `harness disable|enable|status`.

Estado = arquivo-sentinela `.harness/harness.disabled` (machine-local,
gitignored). Presente = o usuário desativou o harness completamente: cada hook
gerado (`boundary_guard`, `session_start`, `stop_hook`, `guard_tests`,
`guard_test_runner`) faz no-op no topo do `main()`.

Invariante de segurança: o AGENTE dentro do Claude Code não pode se
auto-desativar — o `boundary_guard` tem uma regra de nível *floor* que nega,
enquanto o harness está ativo, criar o sentinel (Edit/Write/PowerShell/
Bash-redirect) e rodar `harness disable`. O USUÁRIO, no terminal próprio, não
passa por hook nenhum (o `boundary_guard` só dispara dentro de sessão do
Claude Code) — o comando funciona livremente.

Este módulo é stdlib-only e NÃO importa outros módulos do pacote (evita ciclo:
`boundary_guard`/`cli`/`compiler` importam daqui).

`DISABLED_CHECK_SRC` é a FONTE ÚNICA do snippet `_harness_disabled()`
embutido literalmente por cada render de hook (`render_boundary_guard`,
`render_session_start_hook`, `render_stop_hook`, `_render_guard_tests`,
`_render_guard_test_runner`). Ancorado por `__file__` — o hook mora sempre em
`<repo>/.harness/hooks/<nome>.py`, então `parent.parent` é `<repo>/.harness` e
o sentinel é `<repo>/.harness/harness.disabled`, independente do `cwd` do
payload (que pode derivar; mesmo racional de `boundary_guard`
`_resolve_repo_root_anchor`). Fail-safe: qualquer erro na checagem devolve
`False` (harness continua ativo) — nunca desativa por acidente.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SENTINEL_RELATIVE_PATH = ".harness/harness.disabled"


def _sentinel_path(target_dir: Path | str) -> Path:
    return Path(target_dir) / SENTINEL_RELATIVE_PATH


def is_disabled(target_dir: Path | str) -> bool:
    """True se o harness foi desativado (sentinel presente em `target_dir`)."""
    return _sentinel_path(target_dir).is_file()


def disable(target_dir: Path | str, note: str = "") -> Path:
    """Grava o sentinel como JSON `{"disabled_at": <ISO8601>, "note": <note>}`
    e devolve o `Path` escrito. Idempotente: sobrescreve se já existir."""
    path = _sentinel_path(target_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "disabled_at": datetime.now(timezone.utc).isoformat(),
        "note": note or "",
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def enable(target_dir: Path | str) -> bool:
    """Remove o sentinel se existir. Devolve `True` se removeu, `False` se já
    estava ativo (nada a fazer)."""
    path = _sentinel_path(target_dir)
    if not path.is_file():
        return False
    path.unlink()
    return True


def status(target_dir: Path | str) -> dict:
    """Estado atual: `{"disabled": bool, "sentinel": <str path>, "disabled_at":
    ..., "note": ...}`. Campos de metadados só presentes/relevantes quando
    desativado e o sentinel é JSON válido."""
    path = _sentinel_path(target_dir)
    result: dict = {"disabled": path.is_file(), "sentinel": str(path)}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        result["disabled_at"] = data.get("disabled_at")
        result["note"] = data.get("note", "")
    return result


# Snippet stdlib-only embutido por cada render de hook (T-03/T-04/T-05). Fonte
# única — os renders o inserem literalmente no script standalone gerado. Não
# importa `harness` (hooks rodam fora do pacote instalado). Ancorado por
# `__file__` (o hook mora em `<repo>/.harness/hooks/`), não pelo `cwd` do
# payload. Fail-safe: erro -> False (harness continua ativo).
DISABLED_CHECK_SRC = '''def _harness_disabled() -> bool:
    """True se o harness foi desativado pelo usuario (sentinel
    .harness/harness.disabled presente). Ancorado por __file__ (o hook mora em
    <repo>/.harness/hooks/), nao pelo cwd do payload. Fail-safe: erro -> False
    (harness continua ativo)."""
    try:
        from pathlib import Path as _P
        return (_P(__file__).resolve().parent.parent / "harness.disabled").is_file()
    except Exception:
        return False'''
