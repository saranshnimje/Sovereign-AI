"""
Pydantic schemas for LLM provider endpoints.

SECURITY: api_key is WRITE-ONLY.
- ProviderResponse (returned by GET) NEVER includes api_key.
- ProviderCreate / ProviderUpdate accept api_key for write operations only.
- has_api_key (bool) is included in responses so the UI can show a masked indicator.
"""
import json
from datetime import datetime
from pydantic import BaseModel, ConfigDict, field_validator
from models.provider import PROVIDER_TYPES, PROVIDER_ENVIRONMENTS


class ProviderCreate(BaseModel):
    """Fields accepted when creating a new provider. api_key is optional."""
    model_config = ConfigDict(protected_namespaces=())

    name: str
    provider_type: str
    environment: str = "local"
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None       # write-only — never returned
    enabled: bool = True
    supports_streaming: bool = True
    supports_embeddings: bool = False
    description: str | None = None
    custom_headers: dict[str, str] | None = None  # e.g. {"X-Title": "MyApp"}

    @field_validator("name")
    @classmethod
    def name_not_empty(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        if len(v) > 100:
            raise ValueError("Name too long (max 100 chars)")
        return v

    @field_validator("provider_type")
    @classmethod
    def valid_type(cls, v: str) -> str:
        if v not in PROVIDER_TYPES:
            raise ValueError(f"provider_type must be one of: {PROVIDER_TYPES}")
        return v

    @field_validator("environment")
    @classmethod
    def valid_env(cls, v: str) -> str:
        if v not in PROVIDER_ENVIRONMENTS:
            raise ValueError(f"environment must be one of: {PROVIDER_ENVIRONMENTS}")
        return v

    @field_validator("model_name")
    @classmethod
    def model_optional(cls, v: str | None) -> str | None:
        """Legacy field — kept for backward compatibility but no longer required."""
        if v is None:
            return None
        v = v.strip()
        return v or None


class ProviderUpdate(BaseModel):
    """Fields accepted when updating an existing provider."""
    model_config = ConfigDict(protected_namespaces=())

    name: str | None = None
    environment: str | None = None
    base_url: str | None = None
    model_name: str | None = None
    api_key: str | None = None       # write-only — None means "don't change"
    enabled: bool | None = None
    supports_streaming: bool | None = None
    supports_embeddings: bool | None = None
    description: str | None = None
    custom_headers: dict[str, str] | None = None  # None = don't change, {} = clear


class ProviderResponse(BaseModel):
    """
    Safe provider representation returned by all GET endpoints.
    api_key is NEVER included — only has_api_key (bool) and a MASKED hint
    showing at most the last 4 characters (e.g. "••••••••abcd").
    """
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())

    id: str
    name: str
    provider_type: str
    environment: str
    base_url: str | None
    model_name: str = ""
    has_api_key: bool         # True if an api_key is stored; never the key itself
    api_key_masked: str | None = None   # "••••••••abcd" — last 4 chars max
    enabled: bool
    supports_streaming: bool
    supports_embeddings: bool
    description: str | None
    custom_headers: dict[str, str] | None = None  # returned for display (no secrets in header values)
    model_count: int = 0      # discovered models persisted for this provider
    created_at: datetime
    updated_at: datetime


class ProviderPreset(BaseModel):
    """Preset metadata shown in the Add-Provider picker."""
    model_config = ConfigDict(protected_namespaces=())

    id: str
    label: str
    description: str
    provider_type: str
    environment: str
    default_base_url: str
    requires_api_key: bool
    api_key_hint: str | None = None
    api_key_url: str | None = None
    supports_discovery: bool = True
    adapter: str


class ModelRecord(BaseModel):
    """A persisted, discovered model belonging to a provider."""
    model_config = ConfigDict(protected_namespaces=())

    id: str
    provider_id: str
    model_id: str
    display_name: str | None = None
    family: str | None = None
    parameter_size: str | None = None
    quantization: str | None = None
    size_bytes: int | None = None
    modified_at: str | None = None
    context_length: int | None = None
    status: str = "available"
    enabled: bool = True


class ModelEnabledUpdate(BaseModel):
    enabled: bool


class UserModelPreference(BaseModel):
    """Per-user preferred chat model."""
    model_config = ConfigDict(protected_namespaces=())
    provider_id: str | None = None
    model_name: str


class DiscoveredModel(BaseModel):
    """
    A model available from a connected provider.

    Only fields the provider API actually returns are populated.
    Nothing is fabricated client- or server-side.
    """
    model_config = ConfigDict(protected_namespaces=())

    name: str                          # provider-native model id/name
    display_name: str = ""
    family: str | None = None          # e.g. "llama", or owned_by for OpenAI-style APIs
    parameter_size: str | None = None  # Ollama details.parameter_size
    quantization: str | None = None    # Ollama quantization_level
    size_bytes: int | None = None
    modified_at: str | None = None
    context_length: int | None = None  # only if provider exposes it (rare)
    vision_capable: bool | None = None # only set when the provider reports it
    embedding_capable: bool | None = None
    status: str = "available"


class ProviderTestResult(BaseModel):
    """Result of a connection test. Never includes api_key or stack traces."""
    success: bool
    latency_ms: int | None = None
    provider: str
    model: str = ""
    error: str | None = None    # plain error message — never a stack trace or secret
    models_found: int | None = None  # number of models discovered, if listing succeeded
