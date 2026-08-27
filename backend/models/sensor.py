"""
SensorAnalysis ORM model — results of deterministic CSV sensor analysis.

One row per uploaded sensor dataset. The full deterministic payload
(stats/anomalies/risk/schema/quality) is persisted as JSON in result_json;
AI explanation is stored SEPARATELY so it can never be confused with (or
alter) computed numbers.
"""
from datetime import datetime

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime
from models.base import generate_uuid


class SensorAnalysis(Base):
    __tablename__ = "sensor_analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # pending | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- dataset facts (denormalised for listing/filtering) ---
    encoding: Mapped[str | None] = mapped_column(String(20), nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timestamp_column: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Full deterministic payload: schema, quality, stats, anomalies, risk, meta
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI explanation lives OUTSIDE result_json — never mixed with numbers.
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_explanation_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<SensorAnalysis id={self.id} name={self.original_name} status={self.status}>"
