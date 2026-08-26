"""
ProviderModel ORM model — persisted catalog of models discovered from a provider.

This table is created automatically by Base.metadata.create_all on startup for
existing databases (new tables only — no migration needed).

Models reference their provider by id; credentials are NEVER copied here.
Rows are upserted on every "Refresh Models" action. Models that disappear from
the provider's live listing are marked status="unavailable" (history preserved).
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime
from models.base import generate_uuid


class ProviderModel(Base):
    __tablename__ = "provider_models"
    __table_args__ = (
        UniqueConstraint("provider_id", "model_id", name="uq_provider_model"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    provider_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("llm_providers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Provider-native model identifier (e.g. "llama3.2:3b", "openai/gpt-4.1")
    model_id: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Optional metadata — populated ONLY when the provider API returns it
    family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    parameter_size: Mapped[str | None] = mapped_column(String(50), nullable=True)
    quantization: Mapped[str | None] = mapped_column(String(50), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    modified_at: Mapped[str | None] = mapped_column(String(100), nullable=True)
    context_length: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # available | unavailable (provider no longer reports it)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="available")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    last_seen_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<ProviderModel provider={self.provider_id[:8]} model={self.model_id}>"
