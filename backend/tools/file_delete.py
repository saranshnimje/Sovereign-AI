"""
file_delete tool — delete a file from the workspace (HIGH risk, requires approval).
This is irreversible. Human approval is required before execution.
"""
from __future__ import annotations
from pathlib import Path

from pydantic import BaseModel, field_validator


class FileDeleteInput(BaseModel):
    path: str
    reason: str = ""  # agent must explain why

    @field_validator("path")
    @classmethod
    def safe_path(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute():
            raise ValueError("Path must be relative")
        if ".." in p.parts:
            raise ValueError("Path traversal not allowed")
        return str(p)


class FileDeleteOutput(BaseModel):
    deleted: bool
    path: str
    message: str


async def execute(inp: FileDeleteInput, context: dict) -> dict:
    workspace = Path(context.get("workspace_path", ""))
    full = (workspace / inp.path).resolve()
    workspace_resolved = workspace.resolve()

    if not str(full).startswith(str(workspace_resolved)):
        raise PermissionError("Access denied: outside workspace")

    if not full.exists():
        return FileDeleteOutput(
            deleted=False, path=inp.path, message="File not found"
        ).model_dump()

    if not full.is_file():
        return FileDeleteOutput(
            deleted=False, path=inp.path, message="Not a regular file"
        ).model_dump()

    full.unlink()
    return FileDeleteOutput(
        deleted=True, path=inp.path, message="File deleted"
    ).model_dump()
