"""
file_read tool — reads a file from the agent workspace.
Path traversal is blocked at the Pydantic validation layer.
"""
from __future__ import annotations
import os
from pathlib import Path

from pydantic import BaseModel, field_validator


class FileReadInput(BaseModel):
    path: str

    @field_validator("path")
    @classmethod
    def safe_path(cls, v: str) -> str:
        p = Path(v)
        # Reject absolute paths: Unix (/foo), Windows (C:\foo), UNC (\\server)
        # Use string check in addition to Path.is_absolute() for cross-platform safety
        stripped = v.strip()
        if (stripped.startswith("/") or stripped.startswith("\\") or
                p.is_absolute() or (len(stripped) >= 2 and stripped[1] == ":")):
            raise ValueError("Path must be relative (no leading / or drive letter)")
        if ".." in p.parts:
            raise ValueError("Path traversal ('..') is not allowed")
        return str(p)


class FileReadOutput(BaseModel):
    content: str
    size_bytes: int
    path: str
    truncated: bool = False


MAX_READ_BYTES = 512 * 1024  # 512 KB — prevent huge file reads


async def execute(inp: FileReadInput, context: dict) -> dict:
    workspace = context.get("workspace_path", "")
    full = (Path(workspace) / inp.path).resolve()
    workspace_resolved = Path(workspace).resolve()

    # Double-check resolved path is still inside workspace
    if not str(full).startswith(str(workspace_resolved)):
        raise PermissionError(f"Access denied: '{inp.path}' is outside the workspace")

    if not full.exists():
        raise FileNotFoundError(f"File not found: {inp.path}")
    if not full.is_file():
        raise ValueError(f"Not a regular file: {inp.path}")

    size = full.stat().st_size
    truncated = size > MAX_READ_BYTES
    raw = full.read_bytes()[:MAX_READ_BYTES]

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        content = raw.decode("latin-1", errors="replace")

    return FileReadOutput(
        content=content,
        size_bytes=size,
        path=inp.path,
        truncated=truncated,
    ).model_dump()
