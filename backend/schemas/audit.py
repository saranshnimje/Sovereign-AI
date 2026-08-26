"""Pydantic schemas for audit endpoints."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AuditLogResponse(BaseModel):
    id: str
    sequence_num: int
    timestamp: datetime
    user_id: str | None
    event_type: str
    action: str
    resource_type: str | None
    resource_id: str | None
    outcome: str
    ip_address: str | None
    metadata: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class AuditVerifyResponse(BaseModel):
    verified: bool
    entries_checked: int
    first_error_at_sequence: int | None = None
    message: str
