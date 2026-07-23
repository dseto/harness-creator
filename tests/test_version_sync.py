"""Guard test contra drift de versão (issue #11): marketplace.json e
plugin.json são fontes manuais que não podem divergir de
harness.__version__ — commit ddc37f6 atualizou só 2 de 4 fontes."""

from __future__ import annotations

import json
from pathlib import Path

import harness

REPO_ROOT = Path(__file__).resolve().parent.parent


def _read_json_version(relative_path: str) -> str:
    path = REPO_ROOT / relative_path
    data = json.loads(path.read_text(encoding="utf-8"))
    if relative_path.endswith("marketplace.json"):
        return data["plugins"][0]["version"]
    return data["version"]


def test_marketplace_json_matches_harness_version() -> None:
    assert _read_json_version(".claude-plugin/marketplace.json") == harness.__version__


def test_plugin_json_matches_harness_version() -> None:
    assert _read_json_version(".claude-plugin/plugin.json") == harness.__version__
