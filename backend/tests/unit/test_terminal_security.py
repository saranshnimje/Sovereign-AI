"""
Terminal security tests — workspace restriction, dangerous command blocking,
path traversal protection, and audit logging.

CRITICAL: Terminal tools execute arbitrary commands on the host OS.
These tests verify the security controls are properly enforced.
"""
import asyncio
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from tools.terminal import (
    execute_command,
    execute_powershell,
    RunCommandInput,
    RunPowerShellInput,
    _is_path_within_workspace,
    _contains_traversal,
    _is_dangerous_command,
)


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
@pytest.fixture
def workspace(tmp_path):
    """Create a temporary workspace directory."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return str(ws)


@pytest.fixture
def context(workspace):
    """Create a context dict with workspace_path."""
    return {"workspace_path": workspace}


# ------------------------------------------------------------------
# 1. Workspace restriction tests
# ------------------------------------------------------------------
class TestWorkspaceRestriction:
    """Tests that working_dir must be within workspace."""

    @pytest.mark.asyncio
    async def test_working_dir_within_workspace(self, context, workspace):
        """Working directory within workspace should succeed."""
        subdir = os.path.join(workspace, "subdir")
        os.makedirs(subdir)
        result = await execute_command(
            RunCommandInput(command="echo hello", working_dir="subdir"),
            context,
        )
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]

    @pytest.mark.asyncio
    async def test_working_dir_outside_workspace_blocked(self, workspace, tmp_path):
        """Working directory outside workspace should be blocked."""
        outside = tmp_path / "outside"
        outside.mkdir()
        context = {"workspace_path": workspace}
        result = await execute_command(
            RunCommandInput(command="echo hello", working_dir=str(outside)),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]
        assert "within workspace" in result["stderr"]

    @pytest.mark.asyncio
    async def test_working_dir_is_parent_of_workspace(self, workspace):
        """Working directory that is parent of workspace should be blocked."""
        parent = os.path.dirname(workspace)
        context = {"workspace_path": workspace}
        result = await execute_command(
            RunCommandInput(command="echo hello", working_dir=parent),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_working_dir_same_as_workspace(self, context):
        """Working directory equal to workspace should be allowed."""
        result = await execute_command(
            RunCommandInput(command="echo hello"),
            context,
        )
        assert result["exit_code"] == 0

    @pytest.mark.asyncio
    async def test_working_dir_path_traversal_blocked(self, context):
        """Path traversal in working_dir should be blocked."""
        result = await execute_command(
            RunCommandInput(command="echo hello", working_dir="../../etc"),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_working_dir_absolute_traversal_blocked(self, workspace):
        """Absolute path outside workspace should be blocked."""
        context = {"workspace_path": workspace}
        result = await execute_command(
            RunCommandInput(command="echo hello", working_dir="/etc/passwd"),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]


# ------------------------------------------------------------------
# 2. Dangerous command blocking tests
# ------------------------------------------------------------------
class TestDangerousCommandBlocking:
    """Tests that dangerous commands are blocked."""

    @pytest.mark.asyncio
    async def test_rm_rf_root_blocked(self, context):
        """rm -rf / should be blocked."""
        result = await execute_command(
            RunCommandInput(command="rm -rf /"),
            context,
        )
        assert result["exit_code"] == -1
        assert "dangerous operation" in result["stderr"]

    @pytest.mark.asyncio
    async def test_format_c_blocked(self, context):
        """format c: should be blocked."""
        result = await execute_command(
            RunCommandInput(command="format c:"),
            context,
        )
        assert result["exit_code"] == -1
        assert "dangerous operation" in result["stderr"]

    @pytest.mark.asyncio
    async def test_shutdown_blocked(self, context):
        """shutdown should be blocked."""
        result = await execute_command(
            RunCommandInput(command="shutdown -h now"),
            context,
        )
        assert result["exit_code"] == -1
        assert "dangerous operation" in result["stderr"]

    @pytest.mark.asyncio
    async def test_del_system_blocked(self, context):
        """Windows del /s /q C:\\ should be blocked."""
        result = await execute_command(
            RunCommandInput(command="del /s /q C:\\"),
            context,
        )
        assert result["exit_code"] == -1
        assert "dangerous operation" in result["stderr"]

    @pytest.mark.asyncio
    async def test_powershell_rm_rf_blocked(self, context):
        """PowerShell dangerous commands should be blocked (via pre-execution check)."""
        from tools.terminal import _is_dangerous_command
        assert _is_dangerous_command("Remove-Item -Recurse -Force C:\\*") is True

    @pytest.mark.asyncio
    async def test_safe_command_allowed(self, context):
        """Safe commands should be allowed."""
        result = await execute_command(
            RunCommandInput(command="echo hello world"),
            context,
        )
        assert result["exit_code"] == 0
        assert "hello" in result["stdout"]


# ------------------------------------------------------------------
# 3. Path traversal in working_dir tests
# ------------------------------------------------------------------
class TestPathTraversal:
    """Tests that path traversal attempts in working_dir are blocked."""

    @pytest.mark.asyncio
    async def test_dot_dot_slash_blocked(self, context):
        """../ should be blocked."""
        result = await execute_command(
            RunCommandInput(command="echo test", working_dir="../outside"),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_dot_dot_backslash_blocked(self, context):
        """..\\ should be blocked."""
        result = await execute_command(
            RunCommandInput(command="echo test", working_dir="..\\outside"),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]

    @pytest.mark.asyncio
    async def test_powershell_traversal_blocked(self, context):
        """PowerShell path traversal should be blocked."""
        result = await execute_powershell(
            RunPowerShellInput(script="Write-Output test", working_dir="../outside"),
            context,
        )
        assert result["exit_code"] == -1
        assert "Security error" in result["stderr"]


# ------------------------------------------------------------------
# 4. Helper function unit tests
# ------------------------------------------------------------------
class TestHelperFunctions:
    """Unit tests for security helper functions."""

    def test_is_path_within_workspace_true(self, tmp_path):
        """Path within workspace should return True."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        inside = ws / "subdir"
        inside.mkdir()
        assert _is_path_within_workspace(str(inside), str(ws)) is True

    def test_is_path_within_workspace_false(self, tmp_path):
        """Path outside workspace should return False."""
        ws = tmp_path / "workspace"
        ws.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        assert _is_path_within_workspace(str(outside), str(ws)) is False

    def test_contains_traversal_true(self):
        """Path traversal patterns should be detected."""
        assert _contains_traversal("../etc/passwd") is True
        assert _contains_traversal("..\\windows\\system32") is True
        assert _contains_traversal("/etc/passwd") is True
        assert _contains_traversal("C:\\Windows\\System32") is True

    def test_contains_traversal_false(self):
        """Normal paths should not be flagged."""
        assert _contains_traversal("subdir") is False
        assert _contains_traversal("src/main.py") is False
        assert _contains_traversal("project/src") is False

    def test_is_dangerous_command_true(self):
        """Dangerous commands should be detected."""
        assert _is_dangerous_command("rm -rf /") is True
        assert _is_dangerous_command("format c:") is True
        assert _is_dangerous_command("shutdown -h now") is True

    def test_is_dangerous_command_false(self):
        """Safe commands should not be flagged."""
        assert _is_dangerous_command("echo hello") is False
        assert _is_dangerous_command("ls -la") is False
        assert _is_dangerous_command("python script.py") is False
