"""Teste de Inc.12/B11 — checagem de Docker acessível no boot do sandbox."""

from __future__ import annotations

from pathlib import Path

import docker
import pytest

from harness.config import SandboxConfig
from harness.governance.sandbox import SandboxEnvironment


def test_docker_unavailable_raises_clear_runtime_error(tmp_path: Path, monkeypatch) -> None:
    def fake_from_env():
        raise docker.errors.DockerException("Error while fetching server API version")

    monkeypatch.setattr("docker.from_env", fake_from_env)

    with pytest.raises(RuntimeError, match="Docker não está acessível"):
        SandboxEnvironment(SandboxConfig(), tmp_path)


def test_docker_available_constructs_normally(tmp_path: Path, monkeypatch) -> None:
    class FakeClient:
        def ping(self) -> bool:
            return True

    monkeypatch.setattr("docker.from_env", lambda: FakeClient())

    sandbox = SandboxEnvironment(SandboxConfig(), tmp_path)
    assert sandbox.container_id is None  # ainda não iniciado
