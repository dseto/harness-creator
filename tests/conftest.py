"""Fixtures compartilhadas: config mínima e sandbox falso (sem Docker real)."""

from __future__ import annotations

from pathlib import Path

import pytest

from _helpers import FakeSandbox


@pytest.fixture()
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    return tmp_path
