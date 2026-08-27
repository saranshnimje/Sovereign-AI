"""
Incident ORM model — industrial investigation workspace.

An incident LINKS existing authorised artefacts (a knowledge base for
document evidence, a sensor analysis for measured evidence) and stores the
investigation outcome:

  evidence_json   snapshot of exactly which citations + sensor anomalies were
                  collected (server-side, ownership-checked at collection time)
  risk_json       DETERMINISTIC rule-based assessment (never LLM-derived)
  ai_analysis     Ollama interpretation of the supplied evidence (separate
                  column so it can never be confused with measured data)
  recommendation  action summary extracted from AI output, labelled as such

Approval of high-risk recommendations reuses the EXISTING ApprovalRequest
queue (operation_detail carries incident_id) — no second approval system.
"""
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base, UTCDateTime
from models.base import generate_uuid


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    owner_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    machine: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    asset_tag: Mapped[str | None] = mapped_column(String(120), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Authorised artefact links (validated against ownership at attach/investigate time)
    kb_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("knowledge_bases.id"), nullable=True
    )
    sensor_analysis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("sensor_analyses.id"), nullable=True
    )

    # created | analyzing | completed | failed
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="created")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Evidence snapshot: {"documents": [...], "sensors": [...], "insufficient_evidence": bool}
    evidence_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Deterministic rules result: {"level", "score", "rules_hit": [...], ...}
    risk_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    # AI interpretation — never mixed with measured values
    ai_model: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ai_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Recommendation (action text labelled as AI-provided; risk level deterministic)
    recommendation_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    recommendation_risk_level: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_request_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("approval_requests.id"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), onupdate=func.now(), nullable=False)

    def __repr__(self) -> str:
        return f"<Incident id={self.id} title={self.title} status={self.status}>"
