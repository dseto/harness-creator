"""Teste de Inc.6 — prompt_fn assíncrono não bloqueia o event loop.

Antes da correção, `_default_prompt` chamava `input()` de forma síncrona
dentro de um `gate()` async; com múltiplas tarefas concorrentes (cenário do
cockpit), uma aprovação pendente congelaria todas as outras."""

from __future__ import annotations

import asyncio

from harness.governance.approval import ApprovalPolicy


async def test_prompt_fn_does_not_block_concurrent_coroutines() -> None:
    order: list[str] = []

    async def slow_prompt(_message: str) -> bool:
        await asyncio.sleep(0.2)
        order.append("prompt_resolved")
        return True

    async def dummy_work() -> None:
        await asyncio.sleep(0)
        order.append("dummy_done")

    policy = ApprovalPolicy("balanced", prompt_fn=slow_prompt)

    gate_task = asyncio.create_task(policy.gate("run_terminal", "execute", {"command": "ls"}))
    dummy_task = asyncio.create_task(dummy_work())

    await dummy_task
    # A corrotina dummy, mais rápida, termina ANTES do prompt lento resolver —
    # prova de que o gate não bloqueia o event loop.
    assert order == ["dummy_done"]

    decision = await gate_task
    assert decision.approved is True
    assert order == ["dummy_done", "prompt_resolved"]
