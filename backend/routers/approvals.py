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


@router.get("/")
async def list_approvals(
    status: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    # Admin sees all; filter by status if provided
    query = select(ApprovalRequest).order_by(ApprovalRequest.created_at.desc())
    if status:
        query = query.where(ApprovalRequest.status == status)
    # Count total
    count_q = select(func.count()).select_from(ApprovalRequest)
    if status:
        count_q = count_q.where(ApprovalRequest.status == status)
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(query.offset(offset).limit(limit))
    requests_list = list(result.scalars().all())
    items = [
        ApprovalResponse(
            id=r.id,
            agent_run_id=r.agent_run_id,
            requester_id=r.requester_id,
            operation=r.operation,
            operation_detail=json.loads(r.operation_detail_json),
            risk_level=r.risk_level,
            status=r.status,
            decided_by=r.decided_by,
            decided_at=r.decided_at,
            decision_note=r.decision_note,
            expires_at=r.expires_at,
            created_at=r.created_at,
        )
        for r in requests_list
    ]
    return {"items": items, "total": total}


@router.get("/count")
async def pending_approval_count(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(func.count()).select_from(ApprovalRequest).where(
            ApprovalRequest.status == "pending"
        )
    )
    count = result.scalar_one()
    return {"count": count}


# ------------------------------------------------------------------
# List pending approvals (convenience alias)
# ------------------------------------------------------------------

@router.get("/pending")
async def list_pending_approvals(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    query = (
        select(ApprovalRequest)
        .where(ApprovalRequest.status == "pending")
        .order_by(ApprovalRequest.created_at.desc())
    )
    count_q = select(func.count()).select_from(ApprovalRequest).where(
        ApprovalRequest.status == "pending"
    )
    total = (await db.execute(count_q)).scalar() or 0
    result = await db.execute(query.offset(offset).limit(limit))
    requests_list = list(result.scalars().all())
    items = [
        ApprovalResponse(
            id=r.id,
            agent_run_id=r.agent_run_id,
            requester_id=r.requester_id,
            operation=r.operation,
            operation_detail=json.loads(r.operation_detail_json),
            risk_level=r.risk_level,
            status=r.status,
            decided_by=r.decided_by,
            decided_at=r.decided_at,
            decision_note=r.decision_note,
            expires_at=r.expires_at,
            created_at=r.created_at,
        )
        for r in requests_list
    ]
    return {"items": items, "total": total}


@router.get("/{approval_id}", response_model=ApprovalResponse)
async def get_approval(
    approval_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    req = await svc.get(approval_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    return ApprovalResponse(
        id=req.id,
        agent_run_id=req.agent_run_id,
        requester_id=req.requester_id,
        operation=req.operation,
        operation_detail=json.loads(req.operation_detail_json),
        risk_level=req.risk_level,
        status=req.status,
        decided_by=req.decided_by,
        decided_at=req.decided_at,
        decision_note=req.decision_note,
        expires_at=req.expires_at,
        created_at=req.created_at,
    )


@router.post("/{approval_id}/approve", response_model=ApprovalResponse)
async def approve_request(
    approval_id: str,
    data: ApprovalDecision,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    try:
        req = await svc.approve(approval_id, admin.id, note=data.note)
    except HTTPException as exc:
        raise exc
    return ApprovalResponse(
        id=req.id,
        agent_run_id=req.agent_run_id,
        requester_id=req.requester_id,
        operation=req.operation,
        operation_detail=json.loads(req.operation_detail_json),
        risk_level=req.risk_level,
        status=req.status,
        decided_by=req.decided_by,
        decided_at=req.decided_at,
        decision_note=req.decision_note,
        expires_at=req.expires_at,
        created_at=req.created_at,
    )


@router.post("/{approval_id}/reject", response_model=ApprovalResponse)
async def reject_request(
    approval_id: str,
    data: ApprovalReject,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    svc = _svc(db)
    try:
        req = await svc.reject(approval_id, admin.id, note=data.note)
    except HTTPException as exc:
        raise exc
    return ApprovalResponse(
        id=req.id,
        agent_run_id=req.agent_run_id,
        requester_id=req.requester_id,
        operation=req.operation,
        operation_detail=json.loads(req.operation_detail_json),
        risk_level=req.risk_level,
        status=req.status,
        decided_by=req.decided_by,
        decided_at=req.decided_at,
        decision_note=req.decision_note,
        expires_at=req.expires_at,
        created_at=req.created_at,
    )