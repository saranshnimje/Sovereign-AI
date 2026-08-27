"""
Approval Service — human-in-the-loop gate for high/critical risk tool calls.

Security invariant:
  - Tool execution is BLOCKED until an admin explicitly approves.
  - Expired requests auto-reject (never auto-approve).
  - The decision is recorded with who decided, when, and a note.
  - Approved input is compared to proposed input — they must match exactly.
  - The agent run remains in 'awaiting_approval' status until resolved.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.agent import AgentRun, ApprovalRequest
from models.base import generate_uuid
from services.audit_service import AuditService
from services.settings_service import load_settings

logger = logging.getLogger(__name__)

# In-process signaling: approve/reject wakes up waiting task immediately
_approval_events: dict[str, asyncio.Event] = {}


class ApprovalService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Create request
    # ------------------------------------------------------------------
    async def create_request(
        self,
        agent_run_id: str,
        requester_id: str,
        tool_name: str,
        tool_input: dict,
        risk_level: str,
    ) -> ApprovalRequest:
        """
        Create an approval request and set the agent run to awaiting_approval.
        Returns immediately — caller must then poll/await the decision.
        """
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=load_settings().approval_timeout_minutes
        )
        req = ApprovalRequest(
            id=generate_uuid(),
            agent_run_id=agent_run_id,
            requester_id=requester_id,
            operation=f"Tool call: {tool_name}",
            operation_detail_json=json.dumps(
                {"tool": tool_name, "input": tool_input}
            ),
            risk_level=risk_level,
            status="pending",
            expires_at=expires_at,
        )
        self.db.add(req)

        # Register in-process event so wait_for_decision can be woken immediately
        evt = asyncio.Event()
        _approval_events[req.id] = evt

        # Mark agent run as awaiting_approval
        run_result = await self.db.execute(
            select(AgentRun).where(AgentRun.id == agent_run_id)
        )
        run = run_result.scalar_one_or_none()
        if run:
            run.status = "awaiting_approval"

        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "approval", "approval.request_created", "pending",
            user_id=requester_id,
            resource_type="approval_request",
            resource_id=req.id,
            metadata={"tool": tool_name, "risk": risk_level, "run_id": agent_run_id},
        )
        logger.info(
            "Approval request %s created for tool '%s' (risk=%s, run=%s)",
            req.id, tool_name, risk_level, agent_run_id,
        )
        return req

    # ------------------------------------------------------------------
    # Wait for decision
    # ------------------------------------------------------------------
    async def wait_for_decision(self, request_id: str) -> tuple[bool, str | None]:
        """
        Wait for a decision on the given approval request.
        Returns (approved: bool, decision_note: str|None).

        Uses asyncio.Event for immediate wakeup when approve/reject is called,
        with a hard timeout based on the request's expires_at as a safety net.
        """
        # Clean up any stale requests first
        await self.expire_stale()

        # Fetch the request
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if req is None:
            logger.warning("Approval request %s disappeared", request_id)
            return False, "Request not found"

        # Calculate hard timeout from expires_at
        now = datetime.now(timezone.utc)
        expires = req.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        remaining_seconds = max((expires - now).total_seconds(), 0)

        # Already expired
        if req.status == "pending" and remaining_seconds <= 0:
            req.status = "expired"
            await self.db.flush()
            _approval_events.pop(request_id, None)
            audit = AuditService(self.db)
            await audit.log(
                "approval", "approval.expired", "failure",
                resource_type="approval_request", resource_id=request_id,
            )
            logger.info("Approval request %s expired (already past deadline)", request_id)
            return False, "Approval timed out — request expired"

        # Wait on the in-process event with a hard timeout
        evt = _approval_events.get(request_id)
        if evt:
            try:
                await asyncio.wait_for(evt.wait(), timeout=remaining_seconds)
            except asyncio.TimeoutError:
                pass

        # Re-check DB status (Event may have been signaled or timed out)
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if req is None:
            logger.warning("Approval request %s disappeared", request_id)
            return False, "Request not found"

        now = datetime.now(timezone.utc)
        expires = req.expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)

        if req.status == "pending" and now >= expires:
            req.status = "expired"
            await self.db.flush()
            _approval_events.pop(request_id, None)
            audit = AuditService(self.db)
            await audit.log(
                "approval", "approval.expired", "failure",
                resource_type="approval_request", resource_id=request_id,
            )
            logger.info("Approval request %s expired", request_id)
            return False, "Approval timed out — request expired"

        if req.status == "approved":
            _approval_events.pop(request_id, None)
            return True, req.decision_note

        if req.status in ("rejected", "expired"):
            _approval_events.pop(request_id, None)
            return False, req.decision_note or f"Request {req.status}"

        # Still pending after timeout — should not happen, but treat as expired
        req.status = "expired"
        await self.db.flush()
        _approval_events.pop(request_id, None)
        audit = AuditService(self.db)
        await audit.log(
            "approval", "approval.expired", "failure",
            resource_type="approval_request", resource_id=request_id,
        )
        return False, "Approval timed out — request expired"

    # ------------------------------------------------------------------
    # Admin decisions
    # ------------------------------------------------------------------
    async def approve(
        self, request_id: str, admin_id: str, note: str | None = None
    ) -> ApprovalRequest:
        req = await self._get_pending(request_id)
        req.status = "approved"
        req.decided_by = admin_id
        req.decided_at = datetime.now(timezone.utc)
        req.decision_note = note
        await self.db.flush()

        # Resume agent run
        if req.agent_run_id:
            run_result = await self.db.execute(
                select(AgentRun).where(AgentRun.id == req.agent_run_id)
            )
            run = run_result.scalar_one_or_none()
            if run and run.status == "awaiting_approval":
                run.status = "running"

        await self.db.flush()

        # Wake up the waiting task immediately
        evt = _approval_events.pop(request_id, None)
        if evt:
            evt.set()

        audit = AuditService(self.db)
        await audit.log(
            "approval", "approval.granted", "success",
            user_id=admin_id,
            resource_type="approval_request", resource_id=request_id,
            metadata={"note": note},
        )
        return req

    async def reject(
        self, request_id: str, admin_id: str, note: str
    ) -> ApprovalRequest:
        req = await self._get_pending(request_id)
        req.status = "rejected"
        req.decided_by = admin_id
        req.decided_at = datetime.now(timezone.utc)
        req.decision_note = note
        await self.db.flush()

        # Wake up the waiting task immediately
        evt = _approval_events.pop(request_id, None)
        if evt:
            evt.set()

        audit = AuditService(self.db)
        await audit.log(
            "approval", "approval.rejected", "failure",
            user_id=admin_id,
            resource_type="approval_request", resource_id=request_id,
            metadata={"note": note},
        )
        return req

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------
    async def list_pending(self) -> list[ApprovalRequest]:
        result = await self.db.execute(
            select(ApprovalRequest)
            .where(ApprovalRequest.status == "pending")
            .order_by(ApprovalRequest.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(self, request_id: str) -> ApprovalRequest | None:
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id)
        )
        return result.scalar_one_or_none()

    # ------------------------------------------------------------------
    # Expire stale requests (can be called from a background task)
    # ------------------------------------------------------------------
    async def expire_stale(self) -> int:
        now = datetime.now(timezone.utc)
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.status == "pending")
        )
        expired_count = 0
        for req in result.scalars().all():
            expires = req.expires_at
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            if now >= expires:
                req.status = "expired"
                _approval_events.pop(req.id, None)
                expired_count += 1
        if expired_count:
            await self.db.flush()
        return expired_count

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------
    async def _get_pending(self, request_id: str) -> ApprovalRequest:
        from fastapi import HTTPException
        result = await self.db.execute(
            select(ApprovalRequest).where(ApprovalRequest.id == request_id)
        )
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(404, "Approval request not found")
        if req.status != "pending":
            raise HTTPException(400, f"Request is already '{req.status}'")
        return req
