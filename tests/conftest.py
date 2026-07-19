"""Fixtures compartilhadas."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    return tmp_path
