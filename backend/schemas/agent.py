"""Pydantic schemas for agent and approval endpoints."""
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator


# ---- Agent Run ----

class AgentRunCreate(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    goal: str
    model_name: str | None = None
    allowed_tools: list[str] | None = None
    kb_ids: list[str] | None = None
    max_iterations: int = 10

    @field_validator("goal")
    @classmethod
    def goal_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Goal cannot be empty")
        if len(v) > 5000:
            raise ValueError("Goal too long (max 5000 chars)")
        return v

    @field_validator("max_iterations")
    @classmethod
    def valid_iterations(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("max_iterations must be between 1 and 20")
        return v


class ToolCallResponse(BaseModel):
    id: str
    step_number: int
    tool_name: str
    input_data: dict
    output_data: dict | None
    status: str
    exit_code: int | None
    duration_ms: int | None
    sandbox_used: bool
    container_id: str | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRunResponse(BaseModel):
    id: str
    goal: str
    status: str
    step_count: int
    iteration_count: int
    result: str | None
    error_message: str | None
    model_name: str | None
    max_iterations: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AgentRunDetail(AgentRunResponse):
    tool_calls: list[ToolCallResponse] = []


# ---- Approval ----

class ApprovalResponse(BaseModel):
    id: str
    agent_run_id: str | None
    requester_id: str
    operation: str
    operation_detail: dict
    risk_level: str
    status: str
    decided_by: str | None
    decided_at: datetime | None
    decision_note: str | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class ApprovalDecision(BaseModel):
    note: str | None = None


class ApprovalReject(BaseModel):
    note: str  # required for rejection

    @field_validator("note")
    @classmethod
    def note_required(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("A note is required when rejecting an approval request")
        return v
