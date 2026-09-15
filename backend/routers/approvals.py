"""
Approval request management router.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.agent import ApprovalRequest
from models.user import User
from schemas.agent import ApprovalDecision, ApprovalReject, ApprovalResponse
from services.approval_service import ApprovalService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["approvals"])


def _svc(db: AsyncSession) -> ApprovalService:
    return ApprovalService(db)


def _operation_detail(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (TypeError, ValueError, json.JSONDecodeError):
        # A malformed detail field must never make the entire status/filter page 500.
        return {"raw": str(value)[:2000]}


def _response(r: ApprovalRequest) -> ApprovalResponse:
    return ApprovalResponse(
        id=r.id,
        agent_run_id=r.agent_run_id,
        requester_id=r.requester_id,
        operation=r.operation,
        operation_detail=_operation_detail(r.operation_detail_json),
        risk_level=r.risk_level,
        status=r.status,
        decided_by=r.decided_by,
        decided_at=r.decided_at,
        decision_note=r.decision_note,
        expires_at=r.expires_at,
        created_at=r.created_at,
    )


async def _list(db: AsyncSession, status: str | None, limit: int, offset: int):
    query = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    count_q = select(func.count()).select_from(ApprovalRequest)
    if status:
        query = query.where(ApprovalRequest.status == status)
        count_q = count_q.where(ApprovalRequest.status == status)
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(query.offset(offset).limit(limit))
    return {"items": [_response(r) for r in result.scalars().all()], "total": total}


@router.get("/")
async def list_approvals(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Admin approval list. Invalid/malformed detail data is isolated per row."""
    return await _list(db, status, limit, offset)


@router.get("/count")
async def pending_approval_count(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(func.count()).select_from(ApprovalRequest).where(ApprovalRequest.status == "pending"))
    return {"count": result.scalar_one()}


@router.get("/pending")
async def list_pending_approvals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    return await _list(db, "pending", limit, offset)


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(approval_id: str, admin: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    req = await _svc(db).get(approval_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    return _response(req)


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_request(approval_id: str, data: ApprovalDecision, admin: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    req = await _svc(db).approve(approval_id, admin.id, note=data.note)
    return _response(req)


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_request(approval_id: str, data: ApprovalReject, admin: User = Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    req = await _svc(db).reject(approval_id, admin.id, note=data.note)
    return _response(req)
