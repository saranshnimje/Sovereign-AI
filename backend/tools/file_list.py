"""file_list tool — list files in the agent workspace."""
from __future__ import annotations
from pathlib import Path

from pydantic import BaseModel, field_validator


class FileListInput(BaseModel):
    subdirectory: str = "."

    @field_validator("subdirectory")
    @classmethod
    def safe_subdir(cls, v: str) -> str:
        p = Path(v)
        if p.is_absolute():
            raise ValueError("Subdirectory must be relative")
        if ".." in p.parts:
            raise ValueError("Path traversal not allowed")
        return str(p)


class FileListOutput(BaseModel):
    files: list[str]
    count: int


async def execute(inp: FileListInput, context: dict) -> dict:
    workspace = Path(context.get("workspace_path", ""))
    target = (workspace / inp.subdirectory).resolve()
    workspace_resolved = workspace.resolve()

    if not str(target).startswith(str(workspace_resolved)):
        raise PermissionError("Access denied: outside workspace")

    if not target.exists():
        return FileListOutput(files=[], count=0).model_dump()

    files = [
        str(p.relative_to(workspace_resolved))
        for p in target.rglob("*")
        if p.is_file()
    ]
    return FileListOutput(files=sorted(files), count=len(files)).model_dump()
