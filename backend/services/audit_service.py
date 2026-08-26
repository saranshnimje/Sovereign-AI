"""
Audit service — append-only, hash-chained event log.
Every write goes through this service. No UPDATE or DELETE ever touches audit_logs.
"""
import hashlib
import json
import logging
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.audit import AuditLog
from models.base import generate_uuid

logger = logging.getLogger(__name__)

GENESIS_HASH = "GENESIS"


def _extract_client_ip(request: Request) -> str | None:
    """
    Extract the real client IP from the request.

    Priority:
      1. X-Real-IP header  — set ONLY by our trusted nginx reverse proxy
                             (external clients cannot inject this through nginx,
                              because nginx overwrites it with $remote_addr).
      2. request.client.host — actual TCP source address (direct connections).

    X-Forwarded-For is deliberately NOT used because external clients can
    spoof it. Even behind our nginx, XFF may contain client-supplied values.

    Returns None if no client information is available.
    """
    # Trusted proxy: nginx sets X-Real-IP to $remote_addr (the ACTUAL peer IP)
    real_ip = request.headers.get("X-Real-IP")
    if real_ip and real_ip.strip():
        return real_ip.strip()

    # Direct connection — use the TCP-level source address
    return getattr(request.client, "host", None)


def compute_hash(
    sequence_num: int,
    timestamp: str,
    user_id: str | None,
    action: str,
    outcome: str,
    prev_hash: str,
) -> str:
    """SHA-256 hash of the canonical string for one audit entry."""
    content = f"{sequence_num}:{timestamp}:{user_id or ''}:{action}:{outcome}:{prev_hash}"
    return hashlib.sha256(content.encode()).hexdigest()


class AuditService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def log(
        self,
        event_type: str,
        action: str,
        outcome: str,
        user_id: str | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        metadata: dict | None = None,
        request: Request | None = None,
        ip_address: str | None = None,
    ) -> AuditLog | None:
        """
        Append a new audit log entry.
        IP resolution priority:
          1. request object (extracts via trusted method)
          2. explicit ip_address parameter (threaded from router)
          3. None (background/internal operations)
        """
        try:
            # Get next sequence number
            result = await self.db.execute(
                select(func.max(AuditLog.sequence_num))
            )
            max_seq: int | None = result.scalar_one_or_none()
            seq = 1 if max_seq is None else max_seq + 1

            # Get previous hash for chain
            if seq == 1:
                prev_hash = GENESIS_HASH
            else:
                prev_result = await self.db.execute(
                    select(AuditLog.entry_hash).where(
                        AuditLog.sequence_num == seq - 1
                    )
                )
                prev_hash = prev_result.scalar_one() or GENESIS_HASH

            # Build entry
            now = datetime.now(timezone.utc)
            ts_str = now.isoformat()
            entry_hash = compute_hash(seq, ts_str, user_id, action, outcome, prev_hash)

            ip_address_final: str | None = ip_address
            user_agent: str | None = None
            if request:
                ip_address_final = _extract_client_ip(request) or ip_address
                user_agent = request.headers.get("User-Agent", "")[:500]

            entry = AuditLog(
                id=generate_uuid(),
                sequence_num=seq,
                timestamp=now,
                user_id=user_id,
                event_type=event_type,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                outcome=outcome,
                ip_address=ip_address_final,
                user_agent=user_agent,
                metadata_json=json.dumps(metadata) if metadata else None,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )
            self.db.add(entry)
            await self.db.flush()
            return entry

        except Exception as exc:
            # Audit failure must NEVER crash the caller
            logger.warning("AuditService.log failed internally: %s", exc, exc_info=True)
            return None

    async def verify_chain(self) -> dict:
        """
        Recalculate every entry's hash and confirm chain integrity.
        Returns {"verified": bool, "entries_checked": int, "first_error_at_sequence": int|None}
        """
        result = await self.db.execute(
            select(AuditLog).order_by(AuditLog.sequence_num)
        )
        entries = list(result.scalars().all())

        if not entries:
            return {"verified": True, "entries_checked": 0, "first_error_at_sequence": None}

        expected_prev = GENESIS_HASH
        for entry in entries:
            ts_str = entry.timestamp.isoformat() if entry.timestamp.tzinfo else (
                entry.timestamp.replace(tzinfo=timezone.utc).isoformat()
            )
            expected_hash = compute_hash(
                entry.sequence_num, ts_str, entry.user_id,
                entry.action, entry.outcome, expected_prev,
            )
            if entry.entry_hash != expected_hash or entry.prev_hash != expected_prev:
                return {
                    "verified": False,
                    "entries_checked": entries.index(entry),
                    "first_error_at_sequence": entry.sequence_num,
                }
            expected_prev = entry.entry_hash

        return {"verified": True, "entries_checked": len(entries), "first_error_at_sequence": None}
