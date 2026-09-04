"""AgentRun, ToolCall, and ApprovalRequest ORM models."""
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from database import Base, UTCDateTime
from models.base import TimestampMixin, generate_uuid

if TYPE_CHECKING:
    from models.user import User


class AgentRun(Base, TimestampMixin):
    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    goal: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending"
    )  # pending | running | completed | failed | awaiting_approval | cancelled | timed_out
    plan_json: Mapped[str | None] = mapped_column("plan", Text, nullable=True)
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    step_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    iteration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    max_iterations: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    todo_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    goal_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    current_step_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_verification_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship(back_populates="agent_runs")
    tool_calls: Mapped[list["ToolCall"]] = relationship(
        back_populates="agent_run", cascade="all, delete-orphan"
    )
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="agent_run"
    )

    def __repr__(self) -> str:
        return f"<AgentRun id={self.id} status={self.status}>"


class ToolCall(Base):
    __tablename__ = "tool_calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    agent_run_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_number: Mapped[int] = mapped_column(Integer, nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    input_json: Mapped[str] = mapped_column("input_data", Text, nullable=False)
    output_json: Mapped[str | None] = mapped_column("output_data", Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # success | failed | timeout | rejected
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sandbox_used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    container_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False
    )

    agent_run: Mapped["AgentRun"] = relationship(back_populates="tool_calls")

    def __repr__(self) -> str:
        return f"<ToolCall id={self.id} tool={self.tool_name} status={self.status}>"


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    agent_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("agent_runs.id"), nullable=True
    )
    tool_call_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("tool_calls.id"), nullable=True
    )
    requester_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    operation_detail_json: Mapped[str] = mapped_column(
        "operation_detail", Text, nullable=False
    )
    risk_level: Mapped[str] = mapped_column(
        String(20), nullable=False
    )  # low | medium | high | critical
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending"
    )  # pending | approved | rejected | expired
    decided_by: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id"), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False
    )

    agent_run: Mapped["AgentRun"] = relationship(back_populates="approval_requests")

    def __repr__(self) -> str:
        return f"<ApprovalRequest id={self.id} status={self.status}>"


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    run_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime, default=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<AgentEvent id={self.id} type={self.event_type}>"
