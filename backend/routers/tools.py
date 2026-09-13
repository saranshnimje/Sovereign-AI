"""
Tool management router — list, toggle, configure, and probe tools.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.user import User
from services.tool_catalog import ToolCatalogService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["tools"])


class ToolConfigUpdate(BaseModel):
    config: dict


def _catalog(db: AsyncSession) -> ToolCatalogService:
    return ToolCatalogService(db)


# ------------------------------------------------------------------
# List tools (requires auth)
# ------------------------------------------------------------------

@router.get("")
async def list_tools(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    return await svc.list_tools()


# ------------------------------------------------------------------
# Toggle individual tool (admin only)
# ------------------------------------------------------------------

@router.post("/{tool_name}/disable")
async def disable_tool(
    tool_name: str,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_tool_enabled(tool_name, False)
    except KeyError:
        raise HTTPException(404, f"Tool '{tool_name}' not found")


@router.post("/{tool_name}/enable")
async def enable_tool(
    tool_name: str,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_tool_enabled(tool_name, True)
    except KeyError:
        raise HTTPException(404, f"Tool '{tool_name}' not found")


@router.patch("/{tool_name}")
async def toggle_tool(
    tool_name: str,
    data: dict,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    enabled = data.get("enabled", True)
    try:
        return await svc.set_tool_enabled(tool_name, enabled)
    except KeyError:
        raise HTTPException(404, f"Tool '{tool_name}' not found")


# ------------------------------------------------------------------
# Tool config (admin only)
# ------------------------------------------------------------------

@router.put("/{tool_name}/config")
async def update_tool_config(
    tool_name: str,
    data: ToolConfigUpdate,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_tool_config(tool_name, data.config)
    except KeyError:
        raise HTTPException(404, f"Tool '{tool_name}' not found")


# ------------------------------------------------------------------
# Tool test probe (admin only)
# ------------------------------------------------------------------

TOOL_PROBES = {
    "calculator": {"expression": "6 * 7"},
    "time_now": {},
    "tool_discovery": {},
    "web_search": {"query": "test query"},
    "web_fetch": {"url": "http://example.com"},
    "search_kb": {"query": "test"},
    "file_read": {"path": "test.txt"},
    "file_list": {"path": "."},
}


@router.post("/{tool_name}/test")
async def test_tool(
    tool_name: str,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from tools.registry import get_registry

    reg = get_registry()
    svc = _catalog(db)
    await svc.sync()

    tool_def = reg.get_definition_any_state(tool_name)
    if tool_def is None:
        raise HTTPException(404, f"Tool '{tool_name}' not found")
    if not tool_def.enabled:
        raise HTTPException(409, f"Tool '{tool_name}' is disabled")

    probe_input = TOOL_PROBES.get(tool_name, {})
    try:
        validated = reg.validate_input(tool_def, probe_input)
        result = await reg.execute(tool_def, validated, context={"db": db})
        return {"success": True, "result": result}
    except Exception as exc:
        return {"success": False, "error": str(exc)}
