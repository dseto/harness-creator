"""Onda 3 do plano v2 — instrumentação de contagem de ciclos de fricção.

O gate da onda 5 (decidir entre as posturas B e C do Item 9) depende de UM
número que ninguém tem: quantos ciclos `disable` -> editar -> `compile-session`
-> `enable` uma sessão real ainda gasta depois das ondas 2 e 3. Os ~13 da sessão
do `Savant.Backend.APP-15167` foram contados à mão, relendo transcrição.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from harness.cli import main
from harness.metrics import (
    COUNTED_EVENTS,
    friction_summary,
    metrics_path,
    read_metrics,
    record_event,
)


def _run_cli(monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["harness", *argv])
    with pytest.raises(SystemExit) as exc_info:
        main()
    return exc_info.value.code


def test_read_metrics_without_file_is_zeroed(tmp_path: Path) -> None:
    state = read_metrics(tmp_path)
    assert state["counters"] == {event: 0 for event in COUNTED_EVENTS}
    assert state["first_recorded_at"] is None


def test_record_event_increments_and_stamps(tmp_path: Path) -> None:
    record_event(tmp_path, "disable")
    record_event(tmp_path, "disable")
    record_event(tmp_path, "enable")

    state = read_metrics(tmp_path)
    assert state["counters"]["disable"] == 2
    assert state["counters"]["enable"] == 1
    assert state["first_recorded_at"] is not None
    assert state["last_recorded_at"] is not None


def test_record_event_ignores_unknown_events(tmp_path: Path) -> None:
    """Contador fechado de propósito: um que aceita nome livre vira lixo
    acumulado e ninguém confia no número depois."""
    record_event(tmp_path, "evento-inventado")

    assert "evento-inventado" not in read_metrics(tmp_path)["counters"]
    assert not metrics_path(tmp_path).exists()


def test_corrupt_metrics_file_never_breaks_the_command(tmp_path: Path) -> None:
    """Invariante: instrumentação não pode derrubar o comando instrumentado —
    e menos ainda o `disable`, que é a válvula de escape do usuário."""
    path = metrics_path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ isto nao e json", encoding="utf-8")

    record_event(tmp_path, "disable")

    assert read_metrics(tmp_path)["counters"]["disable"] == 1


def test_friction_summary_counts_closed_cycles_only(tmp_path: Path) -> None:
    """Leitura conservadora: um `disable` sem `enable` correspondente ainda
    está aberto e não fechou ciclo. Subestimar é preferível a inflar o número
    que decide se a postura B se justifica."""
    for _ in range(3):
        record_event(tmp_path, "disable")
        record_event(tmp_path, "enable")
    record_event(tmp_path, "disable")

    summary = friction_summary(tmp_path)
    assert summary["counters"]["disable"] == 4
    assert summary["counters"]["enable"] == 3
    assert summary["disable_enable_cycles"] == 3


def test_cli_disable_enable_status_wire_the_counters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A contagem vive na CLI, não em hook: os ciclos ocorrem com o harness
    DESLIGADO, então um contador em hook mediria zero exatamente durante o
    fenômeno de interesse."""
    for _ in range(2):
        _run_cli(monkeypatch, "disable", "--dir", str(tmp_path))
        capsys.readouterr()
        _run_cli(monkeypatch, "enable", "--dir", str(tmp_path))
        capsys.readouterr()

    code = _run_cli(monkeypatch, "status", "--dir", str(tmp_path))
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["friction"]["counters"]["disable"] == 2
    assert result["friction"]["counters"]["enable"] == 2
    assert result["friction"]["disable_enable_cycles"] == 2


def test_status_without_metrics_reports_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code = _run_cli(monkeypatch, "status", "--dir", str(tmp_path))
    result = json.loads(capsys.readouterr().out)

    assert code == 0
    assert result["friction"]["disable_enable_cycles"] == 0


def test_metrics_file_is_machine_local(tmp_path: Path) -> None:
    """Conta operações desta máquina, não fato do repositório — então precisa
    estar no `.gitignore` tool-owned do `.harness/`."""
    from harness.settings_paths import HARNESS_GITIGNORE_LINES, ensure_machine_local_gitignores

    assert "metrics.json" in HARNESS_GITIGNORE_LINES

    ensure_machine_local_gitignores(tmp_path)
    content = (tmp_path / ".harness" / ".gitignore").read_text(encoding="utf-8")
    assert "metrics.json" in content.split()
