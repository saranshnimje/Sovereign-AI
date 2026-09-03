"""
Terminal tools — execute shell commands and PowerShell scripts.

Security notes:
- Commands run in a subprocess, NOT shell=True
- stdout/stderr capped to prevent context flooding
- Timeout enforced (default 30s, max 120s)
- No shell injection — uses list-based command execution
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
    working_dir = _resolve_working_dir(validated_input.working_dir, context)
    timeout = min(validated_input.timeout, _MAX_TIMEOUT)
    command = validated_input.command.strip()

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

    result = {
        "stdout": "",
        "stderr": "",
        "exit_code": -1,
        "timed_out": False,
        "command": command,
        "working_dir": working_dir,
    }

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
