"""
python_exec tool — Python code execution schema and handler.

SECURITY: This tool's handler delegates ALL execution to SandboxService.
The LLM-supplied code NEVER runs outside the Docker container.
Container is: non-root, cap_drop=ALL, network=none, read-only FS,
memory-limited, CPU-limited, time-limited, auto-removed.
"""
from __future__ import annotations
from pydantic import BaseModel, field_validator


class PythonExecInput(BaseModel):
    code: str
    description: str = ""  # agent explains what the code does

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Code cannot be empty")
        if len(v) > 50_000:
            raise ValueError("Code too long (max 50 000 chars)")
        return v


class PythonExecOutput(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    timed_out: bool
    duration_ms: int
    container_id: str = ""


async def execute(inp: PythonExecInput, context: dict) -> dict:
    """Delegate to SandboxService — NEVER execute inline."""
    sandbox = context.get("sandbox_service")
    if sandbox is None:
        raise RuntimeError(
            "SandboxService is not available. "
            "Ensure Docker is running and the sandbox is configured."
        )
    if not sandbox.available:
        raise RuntimeError(
            "Docker sandbox is unavailable. "
            "Ensure Docker Engine is running on the host."
        )

    result = await sandbox.run_python(
        code=inp.code,
        workspace_path=context.get("workspace_path", ""),
    )
    return PythonExecOutput(**result).model_dump()
