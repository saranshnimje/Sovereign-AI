"""
Tool and plugin management router.
"""
import json
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


class ToolToggle(BaseModel):
    enabled: bool


class ToolConfigUpdate(BaseModel):
    config: dict


class PluginToggle(BaseModel):
    enabled: bool


def _catalog(db: AsyncSession) -> ToolCatalogService:
    return ToolCatalogService(db)


@router.get("/")
async def list_tools(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    return await svc.list_tools()


@router.patch("/{tool_name}")
async def toggle_tool(
    tool_name: str,
    data: ToolToggle,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_tool_enabled(tool_name, data.enabled)
    except KeyError:
        raise HTTPException(404, f"Tool '{tool_name}' not found")


@router.put("/{tool_name}/config")
async def update_tool_config(
    tool_name: str,
    data: ToolConfigUpdate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_tool_config(tool_name, data.config)
    except KeyError:
        raise HTTPException(404, f"Tool '{tool_name}' not found")


@router.get("/plugins")
async def list_plugins(
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    return await svc.list_plugins()


@router.patch("/plugins/{plugin_id}")
async def toggle_plugin(
    plugin_id: str,
    data: PluginToggle,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _catalog(db)
    try:
        return await svc.set_plugin_enabled(plugin_id, data.enabled)
    except KeyError:
        raise HTTPException(404, f"Plugin '{plugin_id}' not found")