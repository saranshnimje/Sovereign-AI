"""
Data management: Organizations + Data Sources.

Isolation model:
- Organization has owner_id; non-admin users see/manage only their own orgs.
- Each organization owns exactly one KnowledgeBase (created on demand) whose
  Qdrant collection is collection-per-org -> retrieval isolation is structural.
- data_sources.config_json holds connection details; secret-looking keys are
  MASKED on every read path and never logged.
- Organization.details_json stores rich company data (employees, departments,
  contacts, financials, infrastructure) as structured JSON for search queries.
New tables -> created safely by Base.metadata.create_all.
"""
import json as _json
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime
from models.base import generate_uuid


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(80), nullable=True)
    location: Mapped[str | None] = mapped_column(String(200), nullable=True)
    website: Mapped[str | None] = mapped_column(String(300), nullable=True)
    founded: Mapped[str | None] = mapped_column(String(20), nullable=True)
    employee_count: Mapped[str | None] = mapped_column(String(30), nullable=True)
    revenue: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ceo: Mapped[str | None] = mapped_column(String(120), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    email: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Rich structured data: employees, departments, infrastructure, financials
    details_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kb_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False)

    @property
    def details(self) -> dict:
        if self.details_json:
            try:
                return _json.loads(self.details_json)
            except (ValueError, TypeError):
                return {}
        return {}

    @details.setter
    def details(self, value: dict) -> None:
        self.details_json = _json.dumps(value) if value else None


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    org_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True)
    # direct | file | location | database | web | api
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # JSON config. Secrets (keys matching key/token/secret/password) are masked
    # on read; never logged, never returned unmasked.
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pending | connected | syncing | indexed | failed | disabled
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)
    doc_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False)
