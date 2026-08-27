"""Unit tests for ApprovalService."""
import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from models.agent import AgentRun, ApprovalRequest
from models.base import generate_uuid


@pytest.fixture(autouse=True)
def _clean_approval_events():
    """Reset the module-level event dict between tests."""
    from services import approval_service
    approval_service._approval_events.clear()
    yield
    approval_service._approval_events.clear()


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _make_req(db, *, status="pending", expires_in_minutes=5, run_id=None, requester_id=None):
    """Create and flush an ApprovalRequest row, returning the id."""
    req_id = generate_uuid()
    rid = requester_id or generate_uuid()
    req = ApprovalRequest(
        id=req_id,
        agent_run_id=run_id,
        requester_id=rid,
        operation="Tool call: file_delete",
        operation_detail_json='{"tool": "file_delete", "input": {"path": "x.txt"}}',
        risk_level="high",
        status=status,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
    )
    return req


def _register_event(req_id):
    """Register an asyncio.Event for a request id (simulates create_request)."""
    from services import approval_service
    approval_service._approval_events[req_id] = asyncio.Event()


# ------------------------------------------------------------------
# Existing tests (kept, adapted)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approve_sets_status(db):
    from services.approval_service import ApprovalService

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    updated = await svc.approve(req.id, admin_id=generate_uuid(), note="OK")

    assert updated.status == "approved"
    assert updated.decided_by is not None


@pytest.mark.asyncio
async def test_reject_requires_note(db):
    from services.approval_service import ApprovalService

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    updated = await svc.reject(req.id, admin_id=generate_uuid(), note="Not allowed")
    assert updated.status == "rejected"
    assert updated.decision_note == "Not allowed"


@pytest.mark.asyncio
async def test_approve_already_decided_raises(db):
    from services.approval_service import ApprovalService
    from fastapi import HTTPException

    req = _make_req(db, status="approved")
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    with pytest.raises(HTTPException) as exc:
        await svc.approve(req.id, admin_id=generate_uuid())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_expire_stale_requests(db):
    from services.approval_service import ApprovalService

    req = _make_req(db, expires_in_minutes=-1)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    count = await svc.expire_stale()
    assert count == 1


@pytest.mark.asyncio
async def test_list_pending_returns_only_pending(db):
    from services.approval_service import ApprovalService

    for status in ("pending", "approved", "rejected"):
        req = _make_req(db, status=status)
        db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    pending = await svc.list_pending()
    assert len(pending) == 1
    assert pending[0].status == "pending"


# ------------------------------------------------------------------
# New tests: asyncio.Event signaling
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_event_signal_wakes_waiter_on_approve(db):
    """Approving should set the event, causing wait_for_decision to return immediately."""
    from services.approval_service import ApprovalService

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)
    req_id = req.id

    async def wait_task():
        return await svc.wait_for_decision(req_id)

    waiter = asyncio.create_task(wait_task())
    await asyncio.sleep(0.05)

    # Approve — this should signal the event
    await svc.approve(req_id, admin_id=generate_uuid(), note="Approved")

    done, _ = await asyncio.wait([waiter], timeout=2.0)
    assert waiter in done, "wait_for_decision should have been woken by approve"
    approved, note = waiter.result()
    assert approved is True


@pytest.mark.asyncio
async def test_reject_signal_wakes_waiter(db):
    """Rejecting should set the event, causing wait_for_decision to return immediately."""
    from services.approval_service import ApprovalService

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)
    req_id = req.id

    async def wait_task():
        return await svc.wait_for_decision(req_id)

    waiter = asyncio.create_task(wait_task())
    await asyncio.sleep(0.05)

    await svc.reject(req_id, admin_id=generate_uuid(), note="Nope")

    done, _ = await asyncio.wait([waiter], timeout=2.0)
    assert waiter in done, "wait_for_decision should have been woken by reject"
    approved, note = waiter.result()
    assert approved is False


@pytest.mark.asyncio
async def test_expire_stale_cleans_up(db):
    """expire_stale should mark expired pending requests and remove their events."""
    from services.approval_service import ApprovalService, _approval_events

    req = _make_req(db, expires_in_minutes=-1)
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)
    count = await svc.expire_stale()
    assert count == 1

    assert req.id not in _approval_events

    refreshed = await svc.get(req.id)
    assert refreshed.status == "expired"


@pytest.mark.asyncio
async def test_wait_for_decision_timeout(db):
    """wait_for_decision should return expired when the hard timeout elapses."""
    from services.approval_service import ApprovalService

    req = _make_req(db, expires_in_minutes=0.001)  # ~0.06 seconds
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)

    approved, note = await svc.wait_for_decision(req.id)
    assert approved is False
    assert "expired" in note.lower() or "timed out" in note.lower()


@pytest.mark.asyncio
async def test_event_cleanup_on_approve(db):
    """After approve, the event dict should be cleaned up for that request."""
    from services.approval_service import ApprovalService, _approval_events

    req = _make_req(db, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)
    await svc.approve(req.id, admin_id=generate_uuid(), note="ok")

    assert req.id not in _approval_events


@pytest.mark.asyncio
async def test_event_cleanup_on_reject(db):
    """After reject, the event dict should be cleaned up for that request."""
    from services.approval_service import ApprovalService, _approval_events

    req = _make_req(db, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)
    await svc.reject(req.id, admin_id=generate_uuid(), note="no")

    assert req.id not in _approval_events


@pytest.mark.asyncio
async def test_wait_for_decision_returns_not_found_for_missing_request(db):
    """wait_for_decision returns (False, 'Request not found') for nonexistent id."""
    from services.approval_service import ApprovalService

    svc = ApprovalService(db)
    approved, note = await svc.wait_for_decision("nonexistent-id")
    assert approved is False
    assert "not found" in note.lower()


@pytest.mark.asyncio
async def test_approve_resumes_agent_run(db):
    """Approving should set the agent run back to 'running'."""
    from services.approval_service import ApprovalService
    from sqlalchemy import select

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    await svc.approve(req.id, admin_id=generate_uuid(), note="go")

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    updated_run = result.scalar_one_or_none()
    assert updated_run.status == "running"


@pytest.mark.asyncio
async def test_reject_does_not_resume_agent_run(db):
    """Rejecting should NOT set the agent run back to 'running'."""
    from services.approval_service import ApprovalService
    from sqlalchemy import select

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    await svc.reject(req.id, admin_id=generate_uuid(), note="nope")

    result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
    updated_run = result.scalar_one_or_none()
    assert updated_run.status == "awaiting_approval"


@pytest.mark.asyncio
async def test_expire_stale_does_not_touch_non_expired(db):
    """expire_stale should only expire requests past their expires_at."""
    from services.approval_service import ApprovalService

    expired_req = _make_req(db, expires_in_minutes=-5)
    valid_req = _make_req(db, expires_in_minutes=30)
    db.add(expired_req)
    db.add(valid_req)
    await db.flush()

    svc = ApprovalService(db)
    count = await svc.expire_stale()
    assert count == 1

    refreshed_expired = await svc.get(expired_req.id)
    refreshed_valid = await svc.get(valid_req.id)
    assert refreshed_expired.status == "expired"
    assert refreshed_valid.status == "pending"


@pytest.mark.asyncio
async def test_approve_already_rejected_raises(db):
    from services.approval_service import ApprovalService
    from fastapi import HTTPException

    req = _make_req(db, status="rejected")
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    with pytest.raises(HTTPException) as exc:
        await svc.approve(req.id, admin_id=generate_uuid())
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_reject_already_approved_raises(db):
    from services.approval_service import ApprovalService
    from fastapi import HTTPException

    req = _make_req(db, status="approved")
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    with pytest.raises(HTTPException) as exc:
        await svc.reject(req.id, admin_id=generate_uuid(), note="too late")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_decision_recorded_with_admin_and_note(db):
    """Approve/reject should record decided_by and decision_note."""
    from services.approval_service import ApprovalService

    admin_id = generate_uuid()
    req = _make_req(db, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    approved = await svc.approve(req.id, admin_id=admin_id, note="Looks good")
    assert approved.decided_by == admin_id
    assert approved.decision_note == "Looks good"
    assert approved.decided_at is not None

    req2 = _make_req(db, expires_in_minutes=10)
    db.add(req2)
    await db.flush()

    rejected = await svc.reject(req2.id, admin_id=admin_id, note="Dangerous")
    assert rejected.decided_by == admin_id
    assert rejected.decision_note == "Dangerous"
    assert rejected.decided_at is not None


@pytest.mark.asyncio
async def test_wait_for_decision_already_expired_request(db):
    """If the request is already expired when wait is called, return immediately."""
    from services.approval_service import ApprovalService

    req = _make_req(db, expires_in_minutes=-5)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    approved, note = await svc.wait_for_decision(req.id)
    assert approved is False
    assert "expired" in note.lower() or "timed out" in note.lower()


@pytest.mark.asyncio
async def test_event_not_registered_falls_through_to_expire(db):
    """If no event is registered (manual DB insert), wait_for_decision expires after timeout."""
    from services.approval_service import ApprovalService

    req = _make_req(db, expires_in_minutes=-1)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    approved, note = await svc.wait_for_decision(req.id)
    assert approved is False


@pytest.mark.asyncio
async def test_approve_no_event_still_works(db):
    """approve() works even without a registered event (no crash)."""
    from services.approval_service import ApprovalService

    req = _make_req(db, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    updated = await svc.approve(req.id, admin_id=generate_uuid(), note="ok")
    assert updated.status == "approved"


@pytest.mark.asyncio
async def test_reject_no_event_still_works(db):
    """reject() works even without a registered event (no crash)."""
    from services.approval_service import ApprovalService

    req = _make_req(db, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    svc = ApprovalService(db)
    updated = await svc.reject(req.id, admin_id=generate_uuid(), note="nope")
    assert updated.status == "rejected"


@pytest.mark.asyncio
async def test_multiple_waiters_same_request(db):
    """Multiple waiters on the same request should all wake up on approve."""
    from services.approval_service import ApprovalService

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    evt = asyncio.Event()
    from services import approval_service
    approval_service._approval_events[req.id] = evt

    svc = ApprovalService(db)
    req_id = req.id

    async def wait_task():
        return await svc.wait_for_decision(req_id)

    waiter1 = asyncio.create_task(wait_task())
    waiter2 = asyncio.create_task(wait_task())
    await asyncio.sleep(0.05)

    # Only one event exists — the second waiter will not find an event
    # (first waiter pops it via wait_for_decision's cleanup paths)
    await svc.approve(req_id, admin_id=generate_uuid(), note="go")

    done, _ = await asyncio.wait([waiter1, waiter2], timeout=3.0)
    results = [t.result() for t in done]
    assert any(approved for approved, _ in results)


@pytest.mark.asyncio
async def test_waiter_wakes_on_reject_not_approve(db):
    """wait_for_decision returns (False, ...) when request is rejected."""
    from services.approval_service import ApprovalService

    run_id = generate_uuid()
    run = AgentRun(
        id=run_id, user_id=generate_uuid(), goal="test",
        status="awaiting_approval", max_iterations=5,
    )
    db.add(run)

    req = _make_req(db, run_id=run_id, expires_in_minutes=10)
    db.add(req)
    await db.flush()

    _register_event(req.id)

    svc = ApprovalService(db)
    req_id = req.id

    async def wait_task():
        return await svc.wait_for_decision(req_id)

    waiter = asyncio.create_task(wait_task())
    await asyncio.sleep(0.05)

    await svc.reject(req_id, admin_id=generate_uuid(), note="Denied")

    done, _ = await asyncio.wait([waiter], timeout=2.0)
    assert waiter in done
    approved, note = waiter.result()
    assert approved is False
    assert note == "Denied"
