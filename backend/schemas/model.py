"""Pydantic schemas for model management endpoints."""
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ModelInfo(BaseModel):
    name: str
    display_name: str
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    size_bytes: int | None = None
    context_length: int | None = None
    roles: list[str] = []
    status: str = "available"  # available | loading | unavailable
    modified_at: str | None = None


class ModelPullRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    model_name: str


class ModelRoleRequest(BaseModel):
    model_config = ConfigDict(protected_namespaces=())
    role: str  # chat | embedding | vision
    model_name: str
    # Optional provider this model belongs to. When set, inference requests for
    # this role are routed to that provider's connection instead of the default
    # local Ollama instance.
    provider_id: str | None = None


class UserModelPrefUpdate(BaseModel):
    """Per-user preferred chat model — write payload."""
    model_config = ConfigDict(protected_namespaces=())
    provider_id: str | None = None
    model_name: str


class UserModelPrefResponse(BaseModel):
    """Per-user preferred chat model — read payload."""
    model_config = ConfigDict(protected_namespaces=())
    provider_id: str | None = None
    model_name: str | None = None
    updated_at: datetime | None = None
