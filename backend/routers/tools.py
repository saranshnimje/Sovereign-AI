"""
Tools management router.

RBAC: any authenticated user may VIEW tools; enable/disable/config are
admin-only. Test executes the tool's own safe probe (or a canned input).
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.user import User
from services.audit_service import AuditService
from services.tool_catalog import ToolCatalogService

router = APIRouter(tags=["tools"])


def _svc(db: AsyncSession = Depends(get_db)) -> ToolCatalogService:
    return ToolCatalogService(db)


class EnabledUpdate(BaseModel):
    enabled: bool


class ConfigUpdate(BaseModel):
    config: dict


@router.get("")
async def list_tools(
    _user: User = Depends(get_current_user),
    svc: ToolCatalogService = Depends(_svc),
):
    return await svc.list_tools()


@router.get("/{name}")
async def get_tool(
    name: str,
    _user: User = Depends(get_current_user),
    svc: ToolCatalogService = Depends(_svc),
):
    tools = await svc.list_tools()
    for t in tools:
        if t["name"] == name:
            return t
    raise HTTPException(404, f"Tool '{name}' not found")


@router.post("/{name}/enable")
async def enable_tool(
    name: str,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ToolCatalogService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await svc.set_tool_enabled(name, True)
    except KeyError:
        raise HTTPException(404, f"Tool '{name}' not found")
    await AuditService(db).log("config", "tool.enabled", "success",
                               user_id=admin.id,
                               resource_type="tool", resource_id=name, request=request)
    return result


@router.post("/{name}/disable")
async def disable_tool(
    name: str,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ToolCatalogService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await svc.set_tool_enabled(name, False)
    except KeyError:
        raise HTTPException(404, f"Tool '{name}' not found")
    await AuditService(db).log("config", "tool.disabled", "success",
                               user_id=admin.id,
                               resource_type="tool", resource_id=name, request=request)
    return result


@router.put("/{name}/config")
async def configure_tool(
    name: str,
    data: ConfigUpdate,
    admin: User = Depends(require_role("admin")),
    svc: ToolCatalogService = Depends(_svc),
):
    """Store tool configuration. Secret-looking values are returned MASKED and
    never appear in logs."""
    try:
        return await svc.set_tool_config(name, data.config)
    except KeyError:
        raise HTTPException(404, f"Tool '{name}' not found")


# Safe canned probes per category — never destructive.
_PROBES = {
    "calculator": {"expression": "6*7"},
    "time_now": {},
    "web_search": {"query": "Sovereign AI Workbench test"},
    "web_fetch": {"url": "https://example.com", "max_chars": 500},
    "tool_discovery": {},
    "model_select": {},
}


@router.post("/{name}/test")
async def test_tool(
    name: str,
    _user: User = Depends(get_current_user),
    svc: ToolCatalogService = Depends(_svc),
):
    from tools.registry import get_registry
    import time as _time

    await svc.sync()
    reg = get_registry()
    tool = reg.get(name)
    if tool is None:
        d = reg.get_definition_any_state(name)
        msg = "Tool is disabled" if d else "Tool not found"
        raise HTTPException(409 if d else 404, msg)

    probe = _PROBES.get(name)
    if probe is None:
        return {"success": True, "note": "No automated probe; tool registered and enabled"}

    try:
        validated = reg.validate_input(tool, probe)
        t0 = _time.monotonic()
        result = await reg.execute(tool, validated, {"user_role": "admin"})
        ms = int((_time.monotonic() - t0) * 1000)
        err = result.get("error")
        return {"success": err is None, "latency_ms": ms,
                "probe": probe, "result": result}
    except Exception as exc:  # noqa: BLE001 — user-safe message only
        return {"success": False, "error": type(exc).__name__,
                "note": "Probe failed — see server log for details"}
