"""
Plugins management router.

Plugins are code-defined manifests bundling registered tools. Disabling a
plugin disables every tool it provides. No plugin code is ever executed.
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.user import User
from services.audit_service import AuditService
from services.tool_catalog import ToolCatalogService

router = APIRouter(tags=["plugins"])


def _svc(db: AsyncSession = Depends(get_db)) -> ToolCatalogService:
    return ToolCatalogService(db)


@router.get("")
async def list_plugins(
    _user: User = Depends(get_current_user),
    svc: ToolCatalogService = Depends(_svc),
):
    return await svc.list_plugins()


@router.post("/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: str,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ToolCatalogService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await svc.set_plugin_enabled(plugin_id, True)
    except KeyError:
        raise HTTPException(404, "Plugin not found")
    await AuditService(db).log("config", "plugin.enabled", "success",
                               user_id=admin.id,
                               resource_type="plugin", resource_id=plugin_id, request=request)
    return result


@router.post("/{plugin_id}/disable")
async def disable_plugin(
    plugin_id: str,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ToolCatalogService = Depends(_svc),
    db: AsyncSession = Depends(get_db),
):
    try:
        result = await svc.set_plugin_enabled(plugin_id, False)
    except KeyError:
        raise HTTPException(404, "Plugin not found")
    await AuditService(db).log("config", "plugin.disabled", "success",
                               user_id=admin.id,
                               resource_type="plugin", resource_id=plugin_id, request=request)
    return result


@router.post("/{plugin_id}/test")
async def test_plugin(
    plugin_id: str,
    _user: User = Depends(get_current_user),
    svc: ToolCatalogService = Depends(_svc),
):
    """Verify the manifest is intact and every provided tool is available."""
    plugins = await svc.list_plugins()
    p = next((x for x in plugins if x["id"] == plugin_id), None)
    if p is None:
        raise HTTPException(404, "Plugin not found")
    missing = [t["name"] for t in p["tools_detail"] if not t["enabled"]]
    return {
        "success": p["enabled"] and not missing,
        "enabled": p["enabled"],
        "tools_total": len(p["tools"]),
        "tools_unavailable": missing,
        "note": None if not missing else
                ("Plugin disabled" if not p["enabled"]
                 else f"Unavailable tools: {', '.join(missing)}"),
    }
