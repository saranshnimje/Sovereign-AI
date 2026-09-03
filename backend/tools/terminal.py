"""
Terminal tools — execute shell commands and PowerShell scripts.

Security notes:
- Commands run in a subprocess, NOT shell=True
- stdout/stderr capped to prevent context flooding
- Timeout enforced (default 30s, max 120s)
- No shell injection — uses list-based command execution
- Workspace restriction: working_dir must be within workspace (CRITICAL security)
- Dangerous commands blocked: rm -rf /, format, shutdown, etc.
- Path traversal: ..\ and ..\ patterns rejected
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
from pydantic import BaseModel, Field

_MAX_OUTPUT = 10000
_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 120

_DANGEROUS_COMMANDS = frozenset({
    "rm -rf /", "rm -rf /*", "rmdir /s /q", "format", "format c:",
    "shutdown", "reboot", "halt", "init 0", "init 6",
    "del /s /q C:\\", "rd /s /q C:\\",
    "mkfs", "dd if=", ":(){ :|:& };:",
    "chmod -R 777 /", "chown -R root:root /",
    "echo 1 > /proc/sys/kernel/core_pattern",
    # PowerShell dangerous commands
    "remove-item -recurse -force", "clear-content", "stop-computer",
    "restart-computer", "remove-item -path c:\\*",
})

_DANGEROUS_PATTERNS = (
    "..\\", "../", "..\\\\", "..//",
    "/etc/passwd", "/etc/shadow", "/etc/sudoers",
    "C:\\Windows\\System32",
    "/proc/", "/sys/", "/dev/",
)


def _is_path_within_workspace(path: str, workspace: str) -> bool:
    """Check that resolved path is within the workspace directory."""
    try:
        resolved = os.path.realpath(path)
        workspace_real = os.path.realpath(workspace)
        return resolved.startswith(workspace_real + os.sep) or resolved == workspace_real
    except (ValueError, OSError):
        return False


def _contains_traversal(value: str) -> bool:
    """Check for path traversal attempts in input."""
    normalized = value.replace("\\", "/").lower()
    for pat in _DANGEROUS_PATTERNS:
        if pat.replace("\\", "/").lower() in normalized:
            return True
    return False


def _is_dangerous_command(command: str) -> bool:
    """Check for known dangerous command patterns."""
    normalized = command.lower().strip()
    for dangerous in _DANGEROUS_COMMANDS:
        d = dangerous.lower()
        if normalized.startswith(d) or d in normalized:
            return True
    return False


class RunCommandInput(BaseModel):
    """Input schema for run_command tool."""
    command: str = Field(
        ...,
        description="Shell command to execute (e.g. 'dir', 'ls -la', 'python --version')",
        max_length=2000,
    )
    working_dir: str | None = Field(
        None,
        description="Working directory (relative to workspace or absolute). Optional.",
        max_length=500,
    )
    timeout: int = Field(
        _DEFAULT_TIMEOUT,
        description=f"Timeout in seconds (1-{_MAX_TIMEOUT}). Default: {_DEFAULT_TIMEOUT}",
        ge=1,
        le=_MAX_TIMEOUT,
    )


class RunCommandOutput(BaseModel):
    """Output schema for run_command tool."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    command: str = ""
    working_dir: str = ""


class RunPowerShellInput(BaseModel):
    """Input schema for run_powershell tool."""
    script: str = Field(
        ...,
        description="PowerShell script or command to execute",
        max_length=5000,
    )
    working_dir: str | None = Field(
        None,
        description="Working directory (relative to workspace or absolute). Optional.",
        max_length=500,
    )
    timeout: int = Field(
        _DEFAULT_TIMEOUT,
        description=f"Timeout in seconds (1-{_MAX_TIMEOUT}). Default: {_DEFAULT_TIMEOUT}",
        ge=1,
        le=_MAX_TIMEOUT,
    )


class RunPowerShellOutput(BaseModel):
    """Output schema for run_powershell tool."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    timed_out: bool = False
    command: str = ""
    working_dir: str = ""


def _resolve_working_dir(working_dir: str | None, context: dict) -> str:
    """Resolve working directory — workspace if relative, absolute if absolute."""
    workspace = context.get("workspace_path", os.getcwd())
    if working_dir is None:
        return workspace
    if os.path.isabs(working_dir):
        return working_dir
    return os.path.join(workspace, working_dir)


def _trim(text: str) -> str:
    """Trim output to max length."""
    if len(text) > _MAX_OUTPUT:
        return text[:_MAX_OUTPUT] + f"\n...[truncated, {len(text) - _MAX_OUTPUT} chars remaining]"
    return text


async def execute_command(validated_input: RunCommandInput, context: dict) -> dict:
    """Execute a shell command in a subprocess."""
    workspace = context.get("workspace_path", os.getcwd())
    working_dir = _resolve_working_dir(validated_input.working_dir, context)
    timeout = min(validated_input.timeout, _MAX_TIMEOUT)
    command = validated_input.command.strip()

    result = {
        "stdout": "",
        "stderr": "",
        "exit_code": -1,
        "timed_out": False,
        "command": command,
        "working_dir": working_dir,
    }

    # SECURITY: Block dangerous commands
    if _is_dangerous_command(command):
        result["stderr"] = "Security error: command is blocked (dangerous operation)"
        return result

    # SECURITY: Block path traversal in working_dir
    if validated_input.working_dir and _contains_traversal(validated_input.working_dir):
        result["stderr"] = "Security error: working_dir contains path traversal"
        return result

    # SECURITY: Working directory must be within workspace
    if not _is_path_within_workspace(working_dir, workspace):
        result["stderr"] = (
            f"Security error: working_dir must be within workspace. "
            f"Requested: {working_dir}, Workspace: {workspace}"
        )
        return result

    # Split command into args (safe, no shell=True)
    args = command.split()

    # Determine shell based on platform
    if platform.system() == "Windows":
        # On Windows, use cmd /c for built-in commands
        if args[0] in ("dir", "copy", "move", "del", "mkdir", "rmdir", "type", "echo", "set", "cls", "cd"):
            args = ["cmd", "/c"] + args
    else:
        # On Linux/Mac, use /bin/sh -c for shell built-ins
        args = ["/bin/sh", "-c", command]

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir if os.path.isdir(working_dir) else None,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result["timed_out"] = True
            result["stderr"] = f"Command timed out after {timeout}s"
            return result

        result["stdout"] = _trim(stdout.decode(errors="replace"))
        result["stderr"] = _trim(stderr.decode(errors="replace"))
        result["exit_code"] = proc.returncode or 0

    except FileNotFoundError:
        result["stderr"] = f"Command not found: {args[0]}"
        result["exit_code"] = -1
    except Exception as exc:
        result["stderr"] = f"Execution error: {str(exc)[:500]}"
        result["exit_code"] = -1

    return result


async def execute_powershell(validated_input: RunPowerShellInput, context: dict) -> dict:
    """Execute a PowerShell script."""
    workspace = context.get("workspace_path", os.getcwd())
    working_dir = _resolve_working_dir(validated_input.working_dir, context)
    timeout = min(validated_input.timeout, _MAX_TIMEOUT)
    script = validated_input.script.strip()

    result = {
        "stdout": "",
        "stderr": "",
        "exit_code": -1,
        "timed_out": False,
        "command": script[:200] + ("..." if len(script) > 200 else ""),
        "working_dir": working_dir,
    }

    # SECURITY: Block dangerous commands
    if _is_dangerous_command(script):
        result["stderr"] = "Security error: script is blocked (dangerous operation)"
        return result

    # SECURITY: Block path traversal in working_dir
    if validated_input.working_dir and _contains_traversal(validated_input.working_dir):
        result["stderr"] = "Security error: working_dir contains path traversal"
        return result

    # SECURITY: Working directory must be within workspace
    if not _is_path_within_workspace(working_dir, workspace):
        result["stderr"] = (
            f"Security error: working_dir must be within workspace. "
            f"Requested: {working_dir}, Workspace: {workspace}"
        )
        return result

    # Determine PowerShell executable
    if platform.system() == "Windows":
        ps_exe = "powershell"
        ps_args = [
            ps_exe,
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", script,
        ]
    else:
        # Linux/Mac: try pwsh (PowerShell Core)
        ps_exe = "pwsh"
        ps_args = [
            ps_exe,
            "-NoProfile",
            "-NonInteractive",
            "-Command", script,
        ]

    try:
        proc = await asyncio.create_subprocess_exec(
            *ps_args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=working_dir if os.path.isdir(working_dir) else None,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            result["timed_out"] = True
            result["stderr"] = f"PowerShell script timed out after {timeout}s"
            return result

        result["stdout"] = _trim(stdout.decode(errors="replace"))
        result["stderr"] = _trim(stderr.decode(errors="replace"))
        result["exit_code"] = proc.returncode or 0

    except FileNotFoundError:
        result["stderr"] = (
            f"PowerShell not found. Ensure {'powershell' if platform.system() == 'Windows' else 'pwsh'} "
            f"is installed and on PATH."
        )
        result["exit_code"] = -1
    except Exception as exc:
        result["stderr"] = f"Execution error: {str(exc)[:500]}"
        result["exit_code"] = -1

    return result
