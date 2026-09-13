"""
Plugin management router — list, toggle, and probe plugins.
"""
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.user import User
from services.tool_catalog import ToolCatalogService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["plugins"])


def _catalog(db: AsyncSession) -> ToolCatalogService:
    return ToolCatalogService(db)


# ------------------------------------------------------------------
# List plugins (requires auth)
# ------------------------------------------------------------------

@router.get("")
async def list_plugins(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    return await svc.list_plugins()


# ------------------------------------------------------------------
# Toggle plugin (admin only)
# ------------------------------------------------------------------

@router.post("/{plugin_id}/disable")
async def disable_plugin(
    plugin_id: str,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_plugin_enabled(plugin_id, False)
    except KeyError:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")


@router.post("/{plugin_id}/enable")
async def enable_plugin(
    plugin_id: str,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_plugin_enabled(plugin_id, True)
    except KeyError:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")


@router.patch("/{plugin_id}")
async def toggle_plugin(
    plugin_id: str,
    data: dict,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    enabled = data.get("enabled", True)
    try:
        return await svc.set_plugin_enabled(plugin_id, enabled)
    except KeyError:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")


# ------------------------------------------------------------------
# Plugin test probe (admin only)
# ------------------------------------------------------------------

@router.post("/{plugin_id}/test")
async def test_plugin(
    plugin_id: str,
    _admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    plugins = await svc.list_plugins()
    plugin = next((p for p in plugins if p["id"] == plugin_id), None)
    if plugin is None:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")
    if not plugin["enabled"]:
        return {"success": False, "note": f"Plugin '{plugin_id}' is disabled"}
    return {"success": True, "note": f"Plugin '{plugin_id}' is operational"}
