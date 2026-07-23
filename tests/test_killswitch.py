"""Testes do módulo core do kill-switch (`harness.killswitch`).

Estado = arquivo-sentinela `.harness/harness.disabled` (machine-local,
gitignored). Presente = harness desativado pelo usuário. `DISABLED_CHECK_SRC`
é o snippet stdlib-only embutido por cada render de hook (T-03/T-04/T-05),
ancorado por `__file__` — testado aqui de forma funcional (subprocess).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from harness.killswitch import (
    DISABLED_CHECK_SRC,
    SENTINEL_RELATIVE_PATH,
    disable,
    enable,
    is_disabled,
    status,
)


# ---------------- SENTINEL_RELATIVE_PATH ----------------

def test_sentinel_relative_path_is_under_harness_dir() -> None:
    assert SENTINEL_RELATIVE_PATH == ".harness/harness.disabled"


# ---------------- is_disabled ----------------

def test_is_disabled_false_when_no_sentinel(tmp_path: Path) -> None:
    assert is_disabled(tmp_path) is False


def test_is_disabled_true_when_sentinel_present(tmp_path: Path) -> None:
    sentinel = tmp_path / SENTINEL_RELATIVE_PATH
    sentinel.parent.mkdir(parents=True, exist_ok=True)
    sentinel.write_text("{}", encoding="utf-8")
    assert is_disabled(tmp_path) is True


# ---------------- disable ----------------

def test_disable_creates_sentinel_with_valid_json(tmp_path: Path) -> None:
    path = disable(tmp_path, note="destravando deploy")
    assert path == tmp_path / SENTINEL_RELATIVE_PATH
    assert path.is_file()

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["note"] == "destravando deploy"
    # disabled_at é ISO8601 parseável
    datetime.fromisoformat(data["disabled_at"].replace("Z", "+00:00"))


def test_disable_is_idempotent_overwrites(tmp_path: Path) -> None:
    disable(tmp_path, note="primeira")
    disable(tmp_path, note="segunda")
    data = json.loads((tmp_path / SENTINEL_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert data["note"] == "segunda"
    assert is_disabled(tmp_path) is True


def test_disable_default_note_is_empty(tmp_path: Path) -> None:
    disable(tmp_path)
    data = json.loads((tmp_path / SENTINEL_RELATIVE_PATH).read_text(encoding="utf-8"))
    assert data["note"] == ""


# ---------------- enable ----------------

def test_enable_removes_sentinel_and_returns_true(tmp_path: Path) -> None:
    disable(tmp_path)
    assert enable(tmp_path) is True
    assert is_disabled(tmp_path) is False


def test_enable_returns_false_when_already_active(tmp_path: Path) -> None:
    assert enable(tmp_path) is False


# ---------------- status ----------------

def test_status_reports_active(tmp_path: Path) -> None:
    st = status(tmp_path)
    assert st["disabled"] is False
    assert st["sentinel"].endswith("harness.disabled")


def test_status_reports_disabled_with_metadata(tmp_path: Path) -> None:
    disable(tmp_path, note="janela de manutencao")
    st = status(tmp_path)
    assert st["disabled"] is True
    assert st["note"] == "janela de manutencao"
    assert st["disabled_at"]


# ---------------- DISABLED_CHECK_SRC (snippet embutido nos hooks) ----------------

def test_disabled_check_src_is_embeddable_source() -> None:
    assert isinstance(DISABLED_CHECK_SRC, str)
    assert "def _harness_disabled" in DISABLED_CHECK_SRC
    assert "harness.disabled" in DISABLED_CHECK_SRC


def _write_fake_hook(tmp_path: Path) -> Path:
    """Escreve um hook fake em .harness/hooks/ que embute DISABLED_CHECK_SRC e
    imprime o resultado de _harness_disabled() — prova a ancoragem por
    __file__ (independente do cwd do payload)."""
    hooks_dir = tmp_path / ".harness" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    script = hooks_dir / "fake_hook.py"
    script.write_text(
        DISABLED_CHECK_SRC
        + "\n\nimport json, sys\n"
        + "print(json.dumps({'disabled': _harness_disabled()}))\n",
        encoding="utf-8",
    )
    return script


def _run(script: Path, cwd: Path) -> dict:
    proc = subprocess.run(
        [sys.executable, str(script)],
        input="{}",
        capture_output=True,
        text=True,
        timeout=15,
        cwd=str(cwd),
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_snippet_detects_active_by_file_anchor(tmp_path: Path) -> None:
    script = _write_fake_hook(tmp_path)
    # cwd deliberadamente derivado para fora do repo — ancoragem é por __file__
    assert _run(script, tmp_path.parent)["disabled"] is False


def test_snippet_detects_disabled_by_file_anchor(tmp_path: Path) -> None:
    script = _write_fake_hook(tmp_path)
    disable(tmp_path)
    # mesmo com cwd derivado, o sentinel é achado via __file__ do hook
    assert _run(script, tmp_path.parent)["disabled"] is True
