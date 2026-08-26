"""Unit tests for ApprovalService."""
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from models.agent import AgentRun, ApprovalRequest
from models.base import generate_uuid


@pytest.mark.asyncio
async def test_approve_sets_status(db):
    from services.approval_service import ApprovalService

    # Create a fake agent run
    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    # Create a pending approval request
    req_id = generate_uuid()
    req = ApprovalRequest(
        id=req_id,
        agent_run_id=run_id,
        requester_id=run.user_id,
        operation="Tool call: file_delete",
        operation_detail_json='{"tool": "file_delete", "input": {"path": "x.txt"}}',
        risk_level="high",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    updated = await svc.approve(req_id, admin_id=generate_uuid(), note="OK")

    assert updated.status == "approved"
    assert updated.decided_by is not None


@pytest.mark.asyncio
async def test_reject_requires_note(db):
    from services.approval_service import ApprovalService
    from fastapi import HTTPException

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req_id = generate_uuid()
    req = ApprovalRequest(
        id=req_id,
        agent_run_id=run_id,
        requester_id=run.user_id,
        operation="Tool call: file_delete",
        operation_detail_json='{}',
        risk_level="high",
        status="pending",
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    updated = await svc.reject(req_id, admin_id=generate_uuid(), note="Not allowed")
    assert updated.status == "rejected"
    assert updated.decision_note == "Not allowed"


@pytest.mark.asyncio
async def test_approve_already_decided_raises(db):
    from services.approval_service import ApprovalService
    from fastapi import HTTPException

    req_id = generate_uuid()
    req = ApprovalRequest(
        id=req_id,
        requester_id=generate_uuid(),
        operation="op",
        operation_detail_json="{}",
        risk_level="high",
        status="approved",  # already decided
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    with pytest.raises(HTTPException) as exc:
        await svc.approve(req_id, admin_id=generate_uuid())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_expire_stale_requests(db):
    from services.approval_service import ApprovalService

    req_id = generate_uuid()
    req = ApprovalRequest(
        id=req_id,
        requester_id=generate_uuid(),
        operation="op",
        operation_detail_json="{}",
        risk_level="high",
        status="pending",
        # Already expired
        expires_at=datetime.now(timezone.utc) - timedelta(minutes=1),
    )
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    count = await svc.expire_stale()
    assert count == 1


@pytest.mark.asyncio
async def test_list_pending_returns_only_pending(db):
    from services.approval_service import ApprovalService

    for status in ("pending", "approved", "rejected"):
        req = ApprovalRequest(
            id=generate_uuid(),
            requester_id=generate_uuid(),
            operation="op",
            operation_detail_json="{}",
            risk_level="high",
            status=status,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    pending = await svc.list_pending()
    assert len(pending) == 1
    assert pending[0].status == "pending"
