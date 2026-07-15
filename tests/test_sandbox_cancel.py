"""Teste de Inc.8 — cancelamento robusto do sandbox + container_id exposto.

Usa um cliente Docker falso (sem Docker real) para simular `task.cancel()`
no meio de um `exec` e confirmar que a destruição do contêiner ainda é
tentada (via `asyncio.shield`) e que o id fica acessível para correlação
com a varredura de órfãos."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from pathlib import Path

import docker
import pytest

from harness.config import SandboxConfig
from harness.governance.sandbox import SandboxEnvironment


@dataclass
class FakeContainer:
    id: str
    removed_with: list[bool] = field(default_factory=list)

    def exec_run(self, cmd, demux=True):
        time.sleep(0.3)  # simula comando "lento" — dá tempo do cancel acontecer
        return (0, (b"out", b""))

    def remove(self, force=True):
        self.removed_with.append(force)


class FakeContainersAPI:
    def __init__(self) -> None:
        self.container: FakeContainer | None = None

    def run(self, **kwargs) -> FakeContainer:
        self.container = FakeContainer(id="cid-123")
        return self.container

    def get(self, container_id: str) -> FakeContainer:
        if self.container is not None and self.container.id == container_id:
            return self.container
        raise docker.errors.NotFound("no such container")


class FakeDockerClient:
    def __init__(self) -> None:
        self.containers = FakeContainersAPI()

    def ping(self) -> bool:
        return True


async def _enter_and_exec_slow(config: SandboxConfig, workspace: Path, ready: asyncio.Event) -> None:
    async with SandboxEnvironment(config, workspace) as sandbox:
        ready.set()
        await sandbox.exec("comando-lento")


async def test_cancel_mid_exec_still_destroys_container(tmp_path: Path, monkeypatch) -> None:
    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    ready = asyncio.Event()
    task = asyncio.create_task(_enter_and_exec_slow(SandboxConfig(), tmp_path, ready))
    await ready.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake_client.containers.container is not None
    assert fake_client.containers.container.removed_with == [True]


async def test_container_id_exposed_after_start(tmp_path: Path, monkeypatch) -> None:
    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    async with SandboxEnvironment(SandboxConfig(), tmp_path) as sandbox:
        assert sandbox.container_id == "cid-123"


async def test_force_remove_fallback_removes_by_id_and_swallows_not_found(
    tmp_path: Path, monkeypatch
) -> None:
    fake_client = FakeDockerClient()
    monkeypatch.setattr("docker.from_env", lambda: fake_client)

    env = SandboxEnvironment(SandboxConfig(), tmp_path)
    await asyncio.to_thread(env._start)
    container_id = env.container_id

    # _force_remove funciona mesmo que self._container já tenha sido zerado
    # por uma tentativa concorrente de _destroy.
    env._container = None
    env._force_remove()
    assert fake_client.containers.container.removed_with == [True]

    # Segunda chamada: container já não existe mais (simulado) -> NotFound
    # engolido, sem levantar.
    fake_client.containers.container = None
    env._force_remove()  # não deve levantar
