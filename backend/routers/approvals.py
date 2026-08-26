"""
Approvals router — admin-only CRUD for human approval gates.
"""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import require_role
from models.user import User
from schemas.agent import ApprovalDecision, ApprovalReject, ApprovalResponse
from services.approval_service import ApprovalService

logger = logging.getLogger(__name__)
router = APIRouter(tags=["approvals"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> ApprovalService:
    return ApprovalService(db)


def _map(req) -> ApprovalResponse:
    try:
        detail = json.loads(req.operation_detail_json) if req.operation_detail_json else {}
    except Exception:
        detail = {}
    return ApprovalResponse(
        id=req.id,
        agent_run_id=req.agent_run_id,
        requester_id=req.requester_id,
        operation=req.operation,
        operation_detail=detail,
        risk_level=req.risk_level,
        status=req.status,
        decided_by=req.decided_by,
        decided_at=req.decided_at,
        decision_note=req.decision_note,
        expires_at=req.expires_at,
        created_at=req.created_at,
    )


@router.get("/count")
async def pending_count(
    _user=Depends(require_role("admin")),
    svc: ApprovalService = Depends(_get_svc),
):
    """Return count of pending approvals — used by the sidebar badge."""
    reqs = await svc.list_pending()
    return {"count": len(reqs)}


@router.get("/pending", response_model=list[ApprovalResponse])
async def list_pending(
    _admin=Depends(require_role("admin")),
    svc: ApprovalService = Depends(_get_svc),
):
    reqs = await svc.list_pending()
    return [_map(r) for r in reqs]


@router.get("/{request_id}", response_model=ApprovalResponse)
async def get_approval(
    request_id: str,
    _admin=Depends(require_role("admin")),
    svc: ApprovalService = Depends(_get_svc),
):
    req = await svc.get(request_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    return _map(req)


@router.post("/{request_id}/approve", response_model=ApprovalResponse)
async def approve(
    request_id: str,
    data: ApprovalDecision,
    admin: User = Depends(require_role("admin")),
    svc: ApprovalService = Depends(_get_svc),
):
    req = await svc.approve(request_id, admin_id=admin.id, note=data.note)
    return _map(req)


@router.post("/{request_id}/reject", response_model=ApprovalResponse)
async def reject(
    request_id: str,
    data: ApprovalReject,
    admin: User = Depends(require_role("admin")),
    svc: ApprovalService = Depends(_get_svc),
):
    req = await svc.reject(request_id, admin_id=admin.id, note=data.note)
    return _map(req)
