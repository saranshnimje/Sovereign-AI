"""AuditLog ORM model — append-only, hash-chained."""
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime
from models.base import generate_uuid


class AuditLog(Base):
    """
    Immutable audit log entry.
    No update or delete operations should ever be performed on this table.
    Hash chain: entry_hash = SHA256(seq:ts:user_id:action:outcome:prev_hash)
    """

    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    sequence_num: Mapped[int] = mapped_column(
        Integer, unique=True, nullable=False, index=True
    )
    timestamp: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False, index=True
    )
    # Keep audit history when a user is deleted; the event remains immutable and
    # the actor reference is anonymized by setting user_id to NULL.
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    session_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # auth | model | document | rag | agent | tool | sandbox | approval | config | error | security
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    outcome: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # success | failure | pending
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    metadata_json: Mapped[str | None] = mapped_column("metadata", Text, nullable=True)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    def __repr__(self) -> str:
        return f"<AuditLog seq={self.sequence_num} action={self.action}>"
