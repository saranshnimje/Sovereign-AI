"""
Unit tests for the Tool Registry — the security gateway.
Verifies that permissions, risk levels, validation, and approval logic
are enforced correctly.
"""
import pytest
from pydantic import BaseModel
from tools.registry import (
    ToolDefinition, ToolRegistry,
    RISK_LOW, RISK_MEDIUM, RISK_HIGH, RISK_CRITICAL,
    ROLE_VIEWER, ROLE_ANALYST, ROLE_ADMIN,
)


# ---- Helpers ----

class SimpleInput(BaseModel):
    value: str


class SimpleOutput(BaseModel):
    result: str


async def _noop(inp, ctx):
    return {"result": "ok"}


def _make_tool(name="test_tool", risk=RISK_LOW, role=ROLE_ANALYST, enabled=True):
    return ToolDefinition(
        name=name,
        description="test",
        input_schema=SimpleInput,
        output_schema=SimpleOutput,
        risk_level=risk,
        required_role=role,
        requires_sandbox=False,
        enabled=enabled,
        handler=_noop,
    )


def _make_registry(*tools):
    reg = ToolRegistry()
    for t in tools:
        reg.register(t)
    return reg


# ---- Registration ----

def test_register_and_get():
    reg = _make_registry(_make_tool("my_tool"))
    assert reg.get("my_tool") is not None


def test_get_disabled_returns_none():
    reg = _make_registry(_make_tool("disabled", enabled=False))
    assert reg.get("disabled") is None


def test_get_nonexistent_returns_none():
    reg = _make_registry()
    assert reg.get("does_not_exist") is None


def test_duplicate_registration_raises():
    reg = _make_registry(_make_tool("dup"))
    with pytest.raises(ValueError, match="already registered"):
        reg.register(_make_tool("dup"))


# ---- Permission checks ----

def test_analyst_can_use_analyst_tool():
    reg = _make_registry(_make_tool("t", role=ROLE_ANALYST))
    tool = reg.get("t")
    reg.check_permission(tool, ROLE_ANALYST)  # no exception


def test_admin_can_use_analyst_tool():
    reg = _make_registry(_make_tool("t", role=ROLE_ANALYST))
    tool = reg.get("t")
    reg.check_permission(tool, ROLE_ADMIN)  # admin >= analyst


def test_viewer_cannot_use_analyst_tool():
    reg = _make_registry(_make_tool("t", role=ROLE_ANALYST))
    tool = reg.get("t")
    with pytest.raises(PermissionError):
        reg.check_permission(tool, ROLE_VIEWER)


def test_analyst_cannot_use_admin_tool():
    reg = _make_registry(_make_tool("t", role=ROLE_ADMIN))
    tool = reg.get("t")
    with pytest.raises(PermissionError):
        reg.check_permission(tool, ROLE_ANALYST)


# ---- Risk / approval logic ----

def test_low_risk_does_not_require_approval():
    reg = _make_registry(_make_tool("t", risk=RISK_LOW))
    assert reg.requires_approval(reg.get("t")) is False


def test_medium_risk_does_not_require_approval():
    reg = _make_registry(_make_tool("t", risk=RISK_MEDIUM))
    assert reg.requires_approval(reg.get("t")) is False


def test_high_risk_requires_approval():
    reg = _make_registry(_make_tool("t", risk=RISK_HIGH))
    assert reg.requires_approval(reg.get("t")) is True


def test_critical_risk_requires_approval():
    reg = _make_registry(_make_tool("t", risk=RISK_CRITICAL))
    assert reg.requires_approval(reg.get("t")) is True


def test_approval_threshold_can_be_changed():
    reg = _make_registry(_make_tool("t", risk=RISK_HIGH))
    # Raising threshold to critical means HIGH no longer requires approval
    assert reg.requires_approval(reg.get("t"), approval_threshold=RISK_CRITICAL) is False


# ---- Input validation ----

def test_valid_input_passes_schema():
    reg = _make_registry(_make_tool("t"))
    tool = reg.get("t")
    validated = reg.validate_input(tool, {"value": "hello"})
    assert validated.value == "hello"


def test_invalid_input_raises():
    reg = _make_registry(_make_tool("t"))
    tool = reg.get("t")
    with pytest.raises(Exception):
        reg.validate_input(tool, {"wrong_field": 123})


# ---- Execution ----

@pytest.mark.asyncio
async def test_execute_calls_handler():
    reg = _make_registry(_make_tool("t"))
    tool = reg.get("t")
    validated = reg.validate_input(tool, {"value": "x"})
    result = await reg.execute(tool, validated, {})
    assert result["result"] == "ok"


@pytest.mark.asyncio
async def test_execute_without_handler_raises():
    tool = ToolDefinition(
        name="no_handler", description="", input_schema=SimpleInput,
        output_schema=SimpleOutput, risk_level=RISK_LOW,
        required_role=ROLE_ANALYST, requires_sandbox=False,
        handler=None,  # no handler
    )
    reg = _make_registry(tool)
    validated = reg.validate_input(reg.get("no_handler"), {"value": "x"})
    with pytest.raises(RuntimeError, match="no handler"):
        await reg.execute(reg.get("no_handler"), validated, {})


# ---- Prompt list ----

def test_tool_list_for_prompt_contains_tool_names():
    reg = _make_registry(
        _make_tool("alpha", role=ROLE_ANALYST),
        _make_tool("beta", role=ROLE_ANALYST),
    )
    prompt = reg.get_tool_list_for_prompt(user_role=ROLE_ANALYST)
    assert "alpha" in prompt
    assert "beta" in prompt


def test_tool_list_excludes_tools_above_user_role():
    reg = _make_registry(
        _make_tool("admin_only", role=ROLE_ADMIN),
        _make_tool("analyst_ok", role=ROLE_ANALYST),
    )
    prompt = reg.get_tool_list_for_prompt(user_role=ROLE_ANALYST)
    assert "admin_only" not in prompt
    assert "analyst_ok" in prompt


# ---- Built-in tools smoke test ----

def test_builtin_tools_all_registered():
    from tools.registry import get_registry
    reg = get_registry()
    expected = ["file_read", "file_list", "file_write", "file_delete",
                "search_kb", "calculator", "python_exec"]
    for name in expected:
        assert reg.get(name) is not None, f"Built-in tool '{name}' not registered"


def test_python_exec_is_high_risk():
    from tools.registry import get_registry
    reg = get_registry()
    tool = reg.get("python_exec")
    assert tool.risk_level == RISK_HIGH
    assert tool.requires_sandbox is True


def test_file_delete_is_high_risk():
    from tools.registry import get_registry
    reg = get_registry()
    tool = reg.get("file_delete")
    assert tool.risk_level == RISK_HIGH


def test_file_read_is_low_risk():
    from tools.registry import get_registry
    reg = get_registry()
    tool = reg.get("file_read")
    assert tool.risk_level == RISK_LOW
    assert tool.requires_sandbox is False
