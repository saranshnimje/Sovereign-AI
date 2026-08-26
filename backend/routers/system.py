"""System health and status endpoints."""
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user
from schemas.system import HealthResponse, SystemStatus
from services.system_service import get_system_status, _get_resource_metrics

router = APIRouter(tags=["system"])


@router.get("/time")
async def time_diagnostic():
    """
    Time synchronization diagnostic (public, safe — no secrets).
    Returns server UTC instant and configured display timezone info.
    """
    from datetime import datetime, timezone, timedelta
    now_utc = datetime.now(timezone.utc)
    ist = timezone(timedelta(hours=5, minutes=30))
    now_ist = now_utc.astimezone(ist)
    offset = f"+{now_ist.utcoffset().seconds // 3600:02d}:{(now_ist.utcoffset().seconds // 60) % 60:02d}"
    return {
        "utc_time": now_utc.isoformat(),
        "display_timezone": "Asia/Kolkata",
        "display_local": now_ist.strftime("%Y-%m-%d %H:%M:%S"),
        "offset": offset,
    }


@router.get("/health", response_model=HealthResponse)
async def health():
    """
    Public health check used by Docker Compose healthcheck.
    Returns 200 OK when the API is running.
    """
    return HealthResponse(status="ok")


@router.get("/status", response_model=SystemStatus)
async def status(_user=Depends(get_current_user)):
    """Full system status — services, resources, loaded models. Auth required."""
    return await get_system_status()


@router.get("/resources")
async def resources(_user=Depends(get_current_user)):
    """CPU, RAM, and disk metrics."""
    return _get_resource_metrics()


@router.get("/activity")
async def recent_activity(
    limit: int = Query(10, ge=1, le=50),
    _user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Recent audit events for the dashboard activity feed.
    Returns last N events — auth required, any role.
    Sensitive metadata fields (passwords, tokens) are never stored in audit logs.
    """
    from models.audit import AuditLog

    result = await db.execute(
        select(AuditLog).order_by(AuditLog.sequence_num.desc()).limit(limit)
    )
    entries = list(result.scalars().all())

    items = []
    for e in entries:
        meta = None
        if e.metadata_json:
            try:
                meta = json.loads(e.metadata_json)
            except Exception:
                pass
        items.append({
            "id": e.id,
            "sequence_num": e.sequence_num,
            "timestamp": e.timestamp.isoformat(),
            "event_type": e.event_type,
            "action": e.action,
            "outcome": e.outcome,
            "resource_type": e.resource_type,
            "resource_id": e.resource_id,
            # User ID only — never email/username directly in feed
            "user_id": e.user_id,
        })

    return {"items": items}
