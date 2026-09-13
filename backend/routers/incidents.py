"""
Incident management router.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from models.incident import Incident
from models.sensor import SensorAnalysis
from models.user import User
from services.audit_service import AuditService
from services.incident_service import IncidentService, assess_risk

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


def _serialize_incident(inc: Incident, risk_level: str | None = None) -> dict:
    """Serialize an Incident to a response dict."""
    result = {
        "id": inc.id,
        "owner_id": inc.owner_id,
        "title": inc.title,
        "machine": inc.machine,
        "asset_tag": inc.asset_tag,
        "description": inc.description,
        "kb_id": inc.kb_id,
        "sensor_analysis_id": inc.sensor_analysis_id,
        "status": inc.status,
        "error_message": inc.error_message,
        "evidence": json.loads(inc.evidence_json) if inc.evidence_json else None,
        "risk": json.loads(inc.risk_json) if inc.risk_json else None,
        "ai_model": inc.ai_model,
        "ai_analysis": inc.ai_analysis,
        "ai_error": inc.ai_error,
        "recommendation_action": inc.recommendation_action,
        "recommendation_risk_level": inc.recommendation_risk_level,
        "requires_approval": inc.requires_approval,
        "approval_request_id": inc.approval_request_id,
        "created_at": inc.created_at.isoformat() if inc.created_at else None,
        "updated_at": inc.updated_at.isoformat() if inc.updated_at else None,
    }
    if risk_level is not None:
        result["risk_level"] = risk_level
    return result


async def _validate_artifact_ownership(
    db: AsyncSession,
    user: User,
    kb_id: str | None = None,
    sensor_analysis_id: str | None = None,
):
    """Validate that attached artifacts exist and belong to the user (or user is admin)."""
    if kb_id:
        from models.knowledge_base import KnowledgeBase
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
        )
        kb = result.scalar_one_or_none()
        if not kb:
            raise HTTPException(404, "Knowledge base not found")
        if user.role != "admin" and kb.owner_id != user.id:
            raise HTTPException(404, "Knowledge base not found")

    if sensor_analysis_id:
        result = await db.execute(
            select(SensorAnalysis).where(SensorAnalysis.id == sensor_analysis_id)
        )
        sa = result.scalar_one_or_none()
        if not sa:
            raise HTTPException(404, "Sensor analysis not found")
        if user.role != "admin" and sa.owner_id != user.id:
            raise HTTPException(404, "Sensor analysis not found")


async def _compute_risk_level(db: AsyncSession, sensor_analysis_id: str | None) -> str | None:
    """Compute deterministic risk level from attached sensor analysis."""
    if not sensor_analysis_id:
        return None
    result = await db.execute(
        select(SensorAnalysis).where(SensorAnalysis.id == sensor_analysis_id)
    )
    sa = result.scalar_one_or_none()
    if not sa or not sa.result_json:
        return None
    try:
        payload = json.loads(sa.result_json)
        risk = assess_risk(payload)
        return risk.get("level")
    except Exception:
        return None


@router.get("")
async def list_incidents(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    incidents = await svc.list_incidents(_user.id, status=status, limit=limit, offset=offset)
    if _user.role != "admin":
        incidents = [i for i in incidents if i.owner_id == _user.id]
    items = [_serialize_incident(i) for i in incidents]
    return {"items": items, "total": len(items)}


@router.post("", status_code=201)
async def create_incident(
    data: IncidentCreate,
    _user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if _user.role == "viewer":
        raise HTTPException(403, "Viewers cannot create incidents")

    # Validate artifact ownership before creating
    await _validate_artifact_ownership(db, _user, data.kb_id, data.sensor_analysis_id)

    svc = _svc(db)
    inc = await svc.create(
        owner_id=_user.id,
        title=data.title,
        machine=data.machine,
        asset_tag=data.asset_tag,
        description=data.description,
        kb_id=data.kb_id,
        sensor_analysis_id=data.sensor_analysis_id,
    )

    # Compute deterministic risk level from attached sensor analysis
    risk_level = await _compute_risk_level(db, data.sensor_analysis_id)

    return _serialize_incident(inc, risk_level=risk_level)


@router.get("/{inc_id}")
async def get_incident(
    inc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    inc = await svc.get(inc_id)
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(404, "Incident not found")

    # Audit viewed
    audit = AuditService(db)
    await audit.log(
        "incident", "incident.viewed", "success",
        user_id=_user.id,
        resource_type="incident",
        resource_id=inc.id,
    )

    risk_level = await _compute_risk_level(db, inc.sensor_analysis_id)
    return _serialize_incident(inc, risk_level=risk_level)


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
        raise HTTPException(404, "Incident not found")

    # Validate new artifacts if being changed
    new_kb = data.kb_id if data.kb_id is not None else inc.kb_id
    new_sa = data.sensor_analysis_id if data.sensor_analysis_id is not None else inc.sensor_analysis_id
    await _validate_artifact_ownership(db, _user, new_kb, new_sa)

    updated = await svc.update(
        incident_id=inc_id,
        title=data.title,
        machine=data.machine,
        asset_tag=data.asset_tag,
        description=data.description,
        kb_id=data.kb_id,
        sensor_analysis_id=data.sensor_analysis_id,
    )

    risk_level = await _compute_risk_level(db, updated.sensor_analysis_id)
    return _serialize_incident(updated, risk_level=risk_level)


@router.delete("/{inc_id}", status_code=204)
async def delete_incident(
    inc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    inc = await svc.get(inc_id)
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(404, "Incident not found")

    audit = AuditService(db)
    await audit.log(
        "incident", "incident.deleted", "success",
        user_id=_user.id,
        resource_type="incident",
        resource_id=inc.id,
    )

    await db.delete(inc)
    await db.flush()


@router.post("/{inc_id}/investigate")
async def investigate_incident(
    inc_id: str,
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    inc = await svc.get(inc_id)
    if _user.role != "admin" and inc.owner_id != _user.id:
        raise HTTPException(404, "Incident not found")
    return await svc.investigate(inc_id)
