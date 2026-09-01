"""
Incident management router.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.incident import Incident
from models.user import User
from services.incident_service import IncidentService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["incidents"])


class IncidentCreate(BaseModel):
    title: str
    machine: str = ""
    asset_tag: str | None = None
    description: str = ""
    kb_id: str | None = None
    sensor_analysis_id: str | None = None


class IncidentUpdate(BaseModel):
    title: str | None = None
    machine: str | None = None
    asset_tag: str | None = None
    description: str | None = None
    kb_id: str | None = None
    sensor_analysis_id: str | None = None


def _svc(db: AsyncSession) -> IncidentService:
    return IncidentService(db)


@router.get("/")
async def list_incidents(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    incidents = await svc.list_incidents(_user.id, status=status, limit=limit, offset=offset)
    # Non-admin users see only their own
    if _user.role != "admin":
        incidents = [i for i in incidents if i.owner_id == _user.id]
    total = len(incidents)
    return {"items": incidents, "total": total}


@router.post("/")
async def create_incident(
    data: IncidentCreate,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    return await svc.create(
        owner_id=_user.id,
        title=data.title,
        machine=data.machine,
        asset_tag=data.asset_tag,
        description=data.description,
        kb_id=data.kb_id,
        sensor_analysis_id=data.sensor_analysis_id,
    )


@router.get("/{inc_id}")
async def get_incident(
    inc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    inc = await svc.get(inc_id)
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(403, "Access denied")
    return inc


@router.patch("/{inc_id}")
async def update_incident(
    inc_id: str,
    data: IncidentUpdate,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    inc = await svc.get(inc_id)
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(403, "Access denied")
    return await svc.update(
        incident_id=inc_id,
        title=data.title,
        machine=data.machine,
        asset_tag=data.asset_tag,
        description=data.description,
        kb_id=data.kb_id,
        sensor_analysis_id=data.sensor_analysis_id,
    )


@router.post("/{inc_id}/investigate")
async def investigate_incident(
    inc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    inc = await svc.get(inc_id)
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(403, "Access denied")
    return await svc.investigate(inc_id)