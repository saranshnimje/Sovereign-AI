"""file_write tool — write text to a file in the agent workspace (MEDIUM risk)."""
from __future__ import annotations
from pathlib import Path

from pydantic import BaseModel, field_validator


class FileWriteInput(BaseModel):
    path: str
    content: str

    @field_validator("path")
    @classmethod
    def safe_path(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute():
            raise ValueError("Path must be relative")
        if ".." in p.parts:
            raise ValueError("Path traversal not allowed")
        return str(p)

    @field_validator("content")
    @classmethod
    def content_limit(cls, v: str) -> str:
        if len(v) > 1_000_000:
            raise ValueError("Content too large (max 1 MB)")
        return v


class FileWriteOutput(BaseModel):
    path: str
    bytes_written: int


async def execute(inp: FileWriteInput, context: dict) -> dict:
    workspace = Path(context.get("workspace_path", ""))
    full = (workspace / inp.path).resolve()
    workspace_resolved = workspace.resolve()

    if not str(full).startswith(str(workspace_resolved)):
        raise PermissionError("Access denied: outside workspace")

    full.parent.mkdir(parents=True, exist_ok=True)
    data = inp.content.encode("utf-8")
    full.write_bytes(data)
    return FileWriteOutput(path=inp.path, bytes_written=len(data)).model_dump()
