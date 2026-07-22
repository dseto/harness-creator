"""Testes do schema `.harness/harness.yaml` (`harness.config`)."""

from __future__ import annotations

import yaml

from harness.config import HarnessConfig


def test_extra_allowed_commands_defaults_to_empty_list() -> None:
    config = HarnessConfig.model_validate({})
    assert config.governance.extra_allowed_commands == []


def test_extra_allowed_commands_preserves_declared_order() -> None:
    config = HarnessConfig.model_validate({
        "governance": {
            "extra_allowed_commands": ["python -m mar_committee", "ng test"],
        },
    })
    assert config.governance.extra_allowed_commands == [
        "python -m mar_committee",
        "ng test",
    ]


def test_extra_allowed_commands_parses_from_real_yaml() -> None:
    raw = yaml.safe_load(
        """
governance:
  extra_allowed_commands:
    - "python -m mar_committee"
verification:
  test_command: "pytest -x --tb=short"
"""
    )
    config = HarnessConfig.model_validate(raw)
    assert config.governance.extra_allowed_commands == ["python -m mar_committee"]
