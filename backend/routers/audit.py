"""Audit log router — query, verify, export."""
import csv
import io
import json
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_role
from models.audit import AuditLog
from schemas.audit import AuditLogResponse, AuditVerifyResponse
from services.audit_service import AuditService

router = APIRouter(tags=["audit"])


def _parse_dt(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@router.get("/logs")
async def list_logs(
    event_type: str | None = None,
    user_id: str | None = None,
    outcome: str | None = None,
    ip_address: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog).order_by(AuditLog.sequence_num.desc())

    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if outcome:
        query = query.where(AuditLog.outcome == outcome)
    if ip_address:
        query = query.where(AuditLog.ip_address.contains(ip_address))
    if sd := _parse_dt(start_date):
        query = query.where(AuditLog.timestamp >= sd)
    if ed := _parse_dt(end_date):
        query = query.where(AuditLog.timestamp <= ed)

    from sqlalchemy import func
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    result = await db.execute(query.offset(offset).limit(limit))
    entries = list(result.scalars().all())

    items = []
    for e in entries:
        meta = None
        if e.metadata_json:
            try:
                meta = json.loads(e.metadata_json)
            except Exception:
                pass
        items.append(
            AuditLogResponse(
                id=e.id,
                sequence_num=e.sequence_num,
                timestamp=e.timestamp,
                user_id=e.user_id,
                event_type=e.event_type,
                action=e.action,
                resource_type=e.resource_type,
                resource_id=e.resource_id,
                outcome=e.outcome,
                ip_address=e.ip_address,
                metadata=meta,
            )
        )

    return {"items": items, "total": total}


@router.get("/logs/{log_id}", response_model=AuditLogResponse)
async def get_log(
    log_id: str,
    _admin=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    from fastapi import HTTPException
    result = await db.execute(select(AuditLog).where(AuditLog.id == log_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(404, "Log entry not found")
    meta = None
    if entry.metadata_json:
        try:
            meta = json.loads(entry.metadata_json)
        except Exception:
            pass
    return AuditLogResponse(
        id=entry.id,
        sequence_num=entry.sequence_num,
        timestamp=entry.timestamp,
        user_id=entry.user_id,
        event_type=entry.event_type,
        action=entry.action,
        resource_type=entry.resource_type,
        resource_id=entry.resource_id,
        outcome=entry.outcome,
        ip_address=entry.ip_address,
        metadata=meta,
    )


@router.get("/verify", response_model=AuditVerifyResponse)
async def verify_chain(
    _admin=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    service = AuditService(db)
    result = await service.verify_chain()
    msg = (
        f"✓ Audit log integrity verified. {result['entries_checked']} entries checked."
        if result["verified"]
        else f"✗ Hash chain broken at entry #{result['first_error_at_sequence']}. Possible tampering."
    )
    return AuditVerifyResponse(
        verified=result["verified"],
        entries_checked=result["entries_checked"],
        first_error_at_sequence=result.get("first_error_at_sequence"),
        message=msg,
    )


@router.get("/export")
async def export_logs(
    format: str = Query("json", pattern="^(json|csv)$"),
    event_type: str | None = None,
    user_id: str | None = None,
    outcome: str | None = None,
    _admin=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = select(AuditLog).order_by(AuditLog.sequence_num)
    if event_type:
        query = query.where(AuditLog.event_type == event_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if outcome:
        query = query.where(AuditLog.outcome == outcome)

    result = await db.execute(query)
    entries = list(result.scalars().all())

    if format == "json":
        data = json.dumps(
            [
                {
                    "seq": e.sequence_num,
                    "timestamp": e.timestamp.isoformat(),
                    "user_id": e.user_id,
                    "event_type": e.event_type,
                    "action": e.action,
                    "outcome": e.outcome,
                    "resource_type": e.resource_type,
                    "resource_id": e.resource_id,
                    "ip_address": e.ip_address,
                }
                for e in entries
            ],
            indent=2,
        )
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="audit_log.json"'},
        )

    # CSV
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        ["seq", "timestamp", "user_id", "event_type", "action", "outcome",
         "resource_type", "resource_id", "ip_address"]
    )
    for e in entries:
        writer.writerow(
            [e.sequence_num, e.timestamp.isoformat(), e.user_id or "",
             e.event_type, e.action, e.outcome,
             e.resource_type or "", e.resource_id or "", e.ip_address or ""]
        )
    return Response(
        content=buf.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="audit_log.csv"'},
    )
