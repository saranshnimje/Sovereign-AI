"""Pydantic schemas for chat endpoints."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class ConversationCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    model_name: str
    title: str | None = None
    system_prompt: str | None = None


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    model_name: str
    system_prompt: str | None
    context_mode: str
    created_at: datetime
    updated_at: datetime
    message_count: int = 0

    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())   # agent-mode extras: tool_mode/tools/plugin_mode
    content: str
    model_name: str | None = None
    # Provider whose connection should serve this message. When omitted the
    # chat-role-bound provider (or default local Ollama) is used.
    provider_id: str | None = None
    rag_kb_ids: list[str] | None = None

    @field_validator("content")
    @classmethod
    def content_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Message content cannot be empty")
        if len(v) > 32000:
            raise ValueError("Message too long (max 32,000 chars)")
        return v


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    token_count: int | None
    finish_reason: str | None
    created_at: datetime
    metadata: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse] = []
