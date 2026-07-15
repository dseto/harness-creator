"""Testes de Inc.5 + Fixes #1/#3/#4/#6 — TDDGuard robusto (chaveado por risk_class)."""

from __future__ import annotations

import hashlib
from pathlib import Path

from harness.governance.approval import ApprovalPolicy
from harness.orchestrator import AgentOrchestrator
from harness.routing.eet import EETEvaluator
from harness.telemetry.tracer import ExecutionTracer
from harness.tools.terminal import CommandResult
from harness.verification.tdd_guard import TDDGuard
from harness.verification.tdd_loop import TDDCycle, TDDPhase
from _helpers import FakeSandbox, make_test_config

TEST_COMMAND = "pytest -x --tb=short"


async def _make_green_cycle(
    workspace: Path, test_glob: str = "tests/**/*.py"
) -> tuple[TDDCycle, FakeSandbox, Path]:
    test_file = workspace / "tests" / "test_x.py"
    test_file.write_text("def test_x():\n    assert False\n", encoding="utf-8")
    sandbox = FakeSandbox(script={
        TEST_COMMAND: CommandResult(command=TEST_COMMAND, exit_code=1, stdout="", stderr="AssertionError", duration_s=0.0)
    })
    cycle = TDDCycle(sandbox=sandbox, workspace=workspace, test_command=TEST_COMMAND, test_glob=test_glob)
    await cycle.assert_red()
    assert cycle.phase == TDDPhase.GREEN
    return cycle, sandbox, test_file


async def test_write_edit_blocked_in_green_without_token(workspace: Path) -> None:
    cycle, _, _ = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND)

    blocked = guard.check_pre_dispatch("edit", {"path": "tests/test_x.py", "content": "x"})

    assert blocked is not None
    assert "tdd_request_test_edit" in blocked


async def test_execute_blocked_when_colliding_with_test_command(workspace: Path) -> None:
    cycle, _, _ = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND)

    blocked = guard.check_pre_dispatch("execute", {"command": TEST_COMMAND})

    assert blocked is not None
    assert "tdd_try_green" in blocked


async def test_execute_not_blocked_for_unrelated_command(workspace: Path) -> None:
    cycle, _, _ = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND)

    assert guard.check_pre_dispatch("execute", {"command": "ls"}) is None


async def test_shell_metachar_bypass_is_closed(workspace: Path) -> None:
    """Fix #3: 'pytest&&true' tokenizava por espaço e escapava. Agora o split
    trata metacaracteres de shell como separadores."""
    cycle, _, _ = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND)

    for command in ("pytest&&true", "(pytest)", "pytest;echo done", "pytest>log", "true|pytest"):
        assert guard.check_pre_dispatch("execute", {"command": command}) is not None, command


async def test_full_test_edit_flow_rehashes_post_write_content(workspace: Path) -> None:
    cycle, _, test_file = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND)

    guard.grant_test_edit_token()
    assert guard.check_pre_dispatch("edit", {"path": "tests/test_x.py", "content": "novo"}) is None

    new_content = "def test_x():\n    assert True\n"
    test_file.write_text(new_content, encoding="utf-8")

    guard.note_post_dispatch("edit", {"path": "tests/test_x.py", "content": new_content}, ok=True)

    expected_hash = hashlib.sha256(test_file.read_bytes()).hexdigest()
    key = str(Path("tests") / "test_x.py")
    assert cycle._test_hashes[key] == expected_hash
    assert guard._test_edit_token is False


async def test_non_test_write_does_not_consume_token(workspace: Path) -> None:
    """Fix #4: um write de arquivo de implementação (não-teste) NÃO deve
    consumir o token de edição de teste nem re-baselinar os hashes."""
    cycle, _, _ = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND)
    (workspace / "src").mkdir(exist_ok=True)

    guard.grant_test_edit_token()
    # Escreve arquivo de implementação com o token na mão.
    guard.note_post_dispatch("edit", {"path": "src/impl.py", "content": "x = 1"}, ok=True)

    # Token intacto — não foi consumido por um write não-teste.
    assert guard._test_edit_token is True


async def test_enforce_tdd_false_disables_guard(workspace: Path) -> None:
    cycle, _, _ = await _make_green_cycle(workspace)
    guard = TDDGuard(cycle=cycle, test_command=TEST_COMMAND, enabled=False)

    assert guard.check_pre_dispatch("edit", {"path": "tests/test_x.py", "content": "x"}) is None
    assert guard.check_pre_dispatch("execute", {"command": TEST_COMMAND}) is None


async def test_execute_tool_integration_blocks_and_never_dispatches(workspace: Path) -> None:
    """Integração: _execute_tool aciona o guard ANTES do dispatch real —
    o arquivo de teste no disco não é tocado quando bloqueado."""
    test_file = workspace / "tests" / "test_x.py"
    original_content = "def test_x():\n    assert False\n"
    test_file.write_text(original_content, encoding="utf-8")

    config = make_test_config()
    orchestrator = AgentOrchestrator(config, workspace)

    sandbox = FakeSandbox(script={
        TEST_COMMAND: CommandResult(command=TEST_COMMAND, exit_code=1, stdout="", stderr="AssertionError", duration_s=0.0)
    })
    orchestrator._register_core_tools(sandbox)
    await orchestrator._tdd_cycle.assert_red()
    assert orchestrator._tdd_cycle.phase == TDDPhase.GREEN

    tracer = ExecutionTracer(config.telemetry, workspace, task_id="guard-integration-test")
    eet = EETEvaluator(config.eet)

    result = await orchestrator._execute_tool(
        name="write_file",
        arguments={"path": "tests/test_x.py", "content": "def test_x():\n    assert True\n"},
        tracer=tracer,
        eet=eet,
    )

    assert "error" in result
    assert test_file.read_text(encoding="utf-8") == original_content  # dispatch nunca rodou


async def test_edit_test_risk_always_gated_regardless_of_policy() -> None:
    for mode in ("auto", "balanced", "paranoid"):
        assert ApprovalPolicy(mode).needs_approval("edit_test") is True
