"""
Unit tests for individual tool implementations.
Tests path traversal prevention, safe evaluation, and workspace isolation.
"""
import os
import tempfile
import pytest


# ---- file_read ----

@pytest.mark.asyncio
async def test_file_read_valid():
    from tools.file_read import FileReadInput, execute
    with tempfile.TemporaryDirectory() as ws:
        path = os.path.join(ws, "test.txt")
        with open(path, "w") as f:
            f.write("hello world")
        inp = FileReadInput(path="test.txt")
        result = await execute(inp, {"workspace_path": ws})
        assert result["content"] == "hello world"
        assert result["size_bytes"] == 11


@pytest.mark.asyncio
async def test_file_read_not_found():
    from tools.file_read import FileReadInput, execute
    with tempfile.TemporaryDirectory() as ws:
        inp = FileReadInput(path="missing.txt")
        with pytest.raises(FileNotFoundError):
            await execute(inp, {"workspace_path": ws})


def test_file_read_path_traversal_blocked():
    from tools.file_read import FileReadInput
    with pytest.raises(Exception):
        FileReadInput(path="../../etc/passwd")


def test_file_read_absolute_path_blocked():
    from tools.file_read import FileReadInput
    with pytest.raises(Exception):
        FileReadInput(path="/etc/passwd")


# ---- file_write ----

@pytest.mark.asyncio
async def test_file_write_creates_file():
    from tools.file_write import FileWriteInput, execute
    with tempfile.TemporaryDirectory() as ws:
        inp = FileWriteInput(path="output.txt", content="result data")
        result = await execute(inp, {"workspace_path": ws})
        assert result["bytes_written"] > 0
        assert os.path.exists(os.path.join(ws, "output.txt"))


def test_file_write_path_traversal_blocked():
    from tools.file_write import FileWriteInput
    with pytest.raises(Exception):
        FileWriteInput(path="../outside.txt", content="bad")


# ---- file_list ----

@pytest.mark.asyncio
async def test_file_list_returns_files():
    from tools.file_list import FileListInput, execute
    with tempfile.TemporaryDirectory() as ws:
        open(os.path.join(ws, "a.txt"), "w").close()
        open(os.path.join(ws, "b.csv"), "w").close()
        inp = FileListInput(subdirectory=".")
        result = await execute(inp, {"workspace_path": ws})
        assert result["count"] == 2
        assert any("a.txt" in f for f in result["files"])


@pytest.mark.asyncio
async def test_file_list_empty_workspace():
    from tools.file_list import FileListInput, execute
    with tempfile.TemporaryDirectory() as ws:
        inp = FileListInput()
        result = await execute(inp, {"workspace_path": ws})
        assert result["count"] == 0


# ---- file_delete ----

@pytest.mark.asyncio
async def test_file_delete_removes_file():
    from tools.file_delete import FileDeleteInput, execute
    with tempfile.TemporaryDirectory() as ws:
        path = os.path.join(ws, "todel.txt")
        open(path, "w").close()
        inp = FileDeleteInput(path="todel.txt", reason="cleanup")
        result = await execute(inp, {"workspace_path": ws})
        assert result["deleted"] is True
        assert not os.path.exists(path)


@pytest.mark.asyncio
async def test_file_delete_missing_returns_not_deleted():
    from tools.file_delete import FileDeleteInput, execute
    with tempfile.TemporaryDirectory() as ws:
        inp = FileDeleteInput(path="ghost.txt")
        result = await execute(inp, {"workspace_path": ws})
        assert result["deleted"] is False


def test_file_delete_traversal_blocked():
    from tools.file_delete import FileDeleteInput
    with pytest.raises(Exception):
        FileDeleteInput(path="../../etc/hosts")


# ---- calculator ----

@pytest.mark.asyncio
async def test_calculator_basic_arithmetic():
    from tools.calculator import CalculatorInput, execute
    for expr, expected in [
        ("2 + 2", 4.0),
        ("10 * 5", 50.0),
        ("100 / 4", 25.0),
        ("2 ** 8", 256.0),
    ]:
        inp = CalculatorInput(expression=expr)
        result = await execute(inp, {})
        assert result["result"] == expected, f"{expr} failed"


@pytest.mark.asyncio
async def test_calculator_math_functions():
    from tools.calculator import CalculatorInput, execute
    import math
    inp = CalculatorInput(expression="sqrt(16)")
    result = await execute(inp, {})
    assert result["result"] == 4.0


@pytest.mark.asyncio
async def test_calculator_division_by_zero():
    from tools.calculator import CalculatorInput, execute
    inp = CalculatorInput(expression="1 / 0")
    with pytest.raises(ValueError, match="Calculation error"):
        await execute(inp, {})


def test_calculator_import_blocked():
    from tools.calculator import CalculatorInput
    with pytest.raises(Exception):
        CalculatorInput(expression="import os")


def test_calculator_eval_blocked():
    from tools.calculator import CalculatorInput
    with pytest.raises(Exception):
        CalculatorInput(expression="eval('1')")


def test_calculator_underscore_blocked():
    from tools.calculator import CalculatorInput
    with pytest.raises(Exception):
        CalculatorInput(expression="__import__('os')")


# ---- Agent action parser ----

def test_parse_action_tool_call():
    from services.agent_service import AgentService
    action = AgentService._parse_action(
        '{"type": "tool_call", "tool": "file_read", "input": {"path": "a.txt"}, "reasoning": "need it"}'
    )
    assert action["type"] == "tool_call"
    assert action["tool"] == "file_read"


def test_parse_action_complete():
    from services.agent_service import AgentService
    action = AgentService._parse_action(
        '{"type": "complete", "result": "Done!"}'
    )
    assert action["type"] == "complete"


def test_parse_action_strips_markdown_fence():
    from services.agent_service import AgentService
    action = AgentService._parse_action(
        '```json\n{"type": "complete", "result": "ok"}\n```'
    )
    assert action["type"] == "complete"


def test_parse_action_invalid_json_returns_error():
    from services.agent_service import AgentService
    action = AgentService._parse_action("This is not JSON at all")
    assert action["type"] == "error"
