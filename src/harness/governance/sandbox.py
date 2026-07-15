"""Camada 4 — SandboxEnvironment: contêiner Docker efêmero e sem rede.

Mitiga exfiltração de dados e o problema do "deputado confuso": mesmo que o
modelo seja induzido (prompt injection) a executar algo hostil, o comando roda
num contêiner descartável, sem rede e com o workspace como único mundo visível.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import docker
from docker.models.containers import Container

from harness.config import SandboxConfig
from harness.tools.terminal import CommandResult


class SandboxEnvironment:
    """Ambiente de execução isolado, um por tarefa.

    Uso:
        async with SandboxEnvironment(cfg, workspace) as sb:
            result = await sb.exec("pytest -x")
    """

    def __init__(self, config: SandboxConfig, workspace: Path) -> None:
        self._cfg = config
        self._workspace = workspace.resolve()
        try:
            self._client = docker.from_env()
            self._client.ping()
        except docker.errors.DockerException as exc:
            raise RuntimeError(
                "Docker não está acessível. Verifique se o Docker Desktop/daemon "
                "está rodando antes de executar 'harness run'."
            ) from exc
        self._container: Container | None = None
        self._last_container_id: str | None = None

    async def __aenter__(self) -> "SandboxEnvironment":
        await asyncio.to_thread(self._start)
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        # `asyncio.shield` protege a destruição de ser interrompida no meio se
        # a Task externa for cancelada (ex.: kill switch de um cockpit) — sem
        # isto, o cancelamento pode abortar o `await` antes do `container.remove`
        # completar, deixando um contêiner órfão. `wait_for` limita quanto tempo
        # esperamos antes de tentar uma remoção forçada de segurança.
        try:
            await asyncio.wait_for(asyncio.shield(asyncio.to_thread(self._destroy)), timeout=15)
        except Exception:
            try:
                await asyncio.to_thread(self._force_remove)
            except Exception:
                pass  # rede de segurança final: varredura por label "harness=true" no boot do cockpit

    @property
    def container_id(self) -> str | None:
        return self._last_container_id

    def _start(self) -> None:
        self._container = self._client.containers.run(
            image=self._cfg.image,
            command="sleep infinity",          # mantém vivo; exec_run injeta comandos
            detach=True,
            network_mode=self._cfg.network_mode,   # "none" por padrão
            mem_limit=self._cfg.mem_limit,
            cpu_quota=self._cfg.cpu_quota,
            pids_limit=self._cfg.pids_limit,
            volumes={str(self._workspace): {"bind": self._cfg.workspace_mount, "mode": "rw"}},
            working_dir=self._cfg.workspace_mount,
            security_opt=["no-new-privileges"],
            cap_drop=["ALL"],
            labels={"harness": "true", "ephemeral": str(self._cfg.ephemeral).lower()},
        )
        self._last_container_id = self._container.id

    def _destroy(self) -> None:
        if self._container is None:
            return
        try:
            self._container.remove(force=True)   # efêmero: nenhum estado sobrevive
        finally:
            self._container = None

    def _force_remove(self) -> None:
        """Fallback quando a destruição normal (blindada por `shield`+timeout
        em `__aexit__`) não completa a tempo — tenta remover pelo id
        capturado em `_start`, mesmo que `self._container` já tenha sido
        zerado por uma tentativa concorrente."""
        if self._last_container_id is None:
            return
        try:
            self._client.containers.get(self._last_container_id).remove(force=True)
        except docker.errors.NotFound:
            pass

    async def exec(self, command: str, timeout_s: int = 120) -> CommandResult:
        """Executa comando no contêiner; nunca no host."""
        if self._container is None:
            raise RuntimeError("Sandbox não iniciado — use 'async with'.")

        start = time.monotonic()

        def _run() -> tuple[int, bytes, bytes]:
            exit_code, output = self._container.exec_run(  # type: ignore[union-attr]
                ["/bin/sh", "-lc", command], demux=True
            )
            stdout, stderr = output or (b"", b"")
            return exit_code, stdout or b"", stderr or b""

        try:
            exit_code, stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(_run), timeout=timeout_s
            )
        except asyncio.TimeoutError:
            return CommandResult(
                command=command,
                exit_code=124,
                stdout="",
                stderr=f"Timeout após {timeout_s}s. Comando possivelmente travado (aguardando input? loop infinito?).",
                duration_s=time.monotonic() - start,
            )

        return CommandResult(
            command=command,
            exit_code=exit_code,
            stdout=stdout.decode("utf-8", errors="replace"),
            stderr=stderr.decode("utf-8", errors="replace"),
            duration_s=time.monotonic() - start,
        )
