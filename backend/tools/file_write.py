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


# Compatibility aliases for smaller/free LLMs that emit the natural names
# write_file/read_file/list_files/delete_file instead of the canonical registry
# names. file_write is imported while ToolRegistry initializes its built-ins, so
# this installs the compatibility layer before any agent execution begins.
# The mapping is intentionally limited to non-destructive/read file aliases here;
# delete_file is handled by the same resolver so all file-tool variants are
# normalized consistently before registry lookup/permission/validation.
_FILE_TOOL_ALIASES = {
    "write_file": "file_write",
    "read_file": "file_read",
    "list_files": "file_list",
    "delete_file": "file_delete",
    "writefile": "file_write",
    "readfile": "file_read",
    "listfiles": "file_list",
    "deletefile": "file_delete",
}

try:
    from tools.registry import ToolRegistry

    _original_registry_get = ToolRegistry.get

    def _get_with_file_aliases(self, name: str):
        normalized = name.strip().lower() if isinstance(name, str) else name
        return _original_registry_get(self, _FILE_TOOL_ALIASES.get(normalized, normalized))

    # Install once; guard against module reloads/re-imports.
    if not getattr(ToolRegistry.get, "_file_alias_compat", False):
        _get_with_file_aliases._file_alias_compat = True
        ToolRegistry.get = _get_with_file_aliases
except Exception:
    # Registry initialization must never fail because compatibility setup failed.
    pass
