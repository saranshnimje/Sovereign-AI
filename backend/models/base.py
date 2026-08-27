"""
Shared base utilities for all ORM models.
"""
import uuid
from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from database import UTCDateTime


def generate_uuid() -> str:
    """Generate a new UUID v4 string."""
    return str(uuid.uuid4())


class TimestampMixin:
    """
    Adds created_at / updated_at columns to any model.

    NOTE: server-side defaults (func.now()) expire these attributes after
    flush. Code that mutates rows and then serialises them in the same
    request must `await db.refresh(obj)` first (see reset_document_for_reprocess)
    — a lazy refresh from sync context raises MissingGreenlet under AsyncSession.
    """

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False,
    )
