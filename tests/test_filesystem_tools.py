"""Testes de Inc.1 — read_file/write_file e bloqueio de path traversal."""

from pathlib import Path

import pytest

from harness.tools.filesystem import FileReadTool, FileWriteTool
from harness.tools.registry import ToolExecutionError


@pytest.fixture()
def workspace(tmp_path: Path) -> Path:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    return tmp_path


async def test_read_file_inside_workspace(workspace: Path) -> None:
    tool = FileReadTool(workspace)
    result = await tool(path="src/hello.py")
    assert result["content"] == "print('hi')\n"


async def test_write_file_inside_workspace(workspace: Path) -> None:
    tool = FileWriteTool(workspace)
    result = await tool(path="src/new_file.py", content="x = 1\n")
    assert (workspace / "src" / "new_file.py").read_text(encoding="utf-8") == "x = 1\n"
    assert result["bytes_written"] == len(b"x = 1\n")


async def test_read_file_missing(workspace: Path) -> None:
    tool = FileReadTool(workspace)
    with pytest.raises(ToolExecutionError):
        await tool(path="src/does_not_exist.py")


async def test_read_file_blocks_traversal(workspace: Path) -> None:
    tool = FileReadTool(workspace)
    with pytest.raises(ToolExecutionError):
        await tool(path="../outside.txt")


async def test_write_file_blocks_traversal(workspace: Path) -> None:
    tool = FileWriteTool(workspace)
    with pytest.raises(ToolExecutionError):
        await tool(path="../../x", content="y")


def test_risk_classes() -> None:
    assert FileReadTool.risk_class == "read"
    assert FileWriteTool.risk_class == "edit"
