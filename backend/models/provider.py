"""
LLMProvider ORM model — stores configured AI provider/model entries.
API keys are stored in this table but NEVER returned through GET endpoints.
"""
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base
from models.base import TimestampMixin, generate_uuid

# Supported provider type identifiers
PROVIDER_OLLAMA             = "ollama"
PROVIDER_OPENAI             = "openai"
PROVIDER_ANTHROPIC          = "anthropic"
PROVIDER_GEMINI             = "gemini"
PROVIDER_OPENAI_COMPATIBLE  = "openai_compatible"
# Cloud gateway presets — all OpenAI-compatible, routed through
# OpenAICompatibleProvider with preset-specific default base URLs.
PROVIDER_OPENROUTER         = "openrouter"
PROVIDER_OPENCODE_ZEN       = "opencode_zen"
PROVIDER_NVIDIA             = "nvidia"

PROVIDER_TYPES = [
    PROVIDER_OLLAMA,
    PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC,
    PROVIDER_GEMINI,
    PROVIDER_OPENAI_COMPATIBLE,
    PROVIDER_OPENROUTER,
    PROVIDER_OPENCODE_ZEN,
    PROVIDER_NVIDIA,
]

PROVIDER_ENVIRONMENTS = ["local", "cloud", "custom"]


# ---------------------------------------------------------------------------
# Provider presets — metadata shown by the "Add LLM Provider" picker.
#
# Each preset maps to an adapter via build_provider() in services/llm_client.py.
# Model lists are NEVER part of a preset — they are always discovered live from
# the provider API. Adding a new provider later = one entry here + one mapping
# in build_provider().
# ---------------------------------------------------------------------------
PROVIDER_PRESETS: list[dict] = [
    {
        "id": PROVIDER_OPENROUTER,
        "label": "OpenRouter",
        "description": "Access 300+ models (GPT, Claude, Gemini, Llama and more) through one API key.",
        "provider_type": PROVIDER_OPENROUTER,
        "environment": "cloud",
        "default_base_url": "https://openrouter.ai/api/v1",
        "requires_api_key": True,
        "api_key_hint": "sk-or-v1-…",
        "api_key_url": "https://openrouter.ai/settings/keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_OPENCODE_ZEN,
        "label": "OpenCode Zen",
        "description": "Curated gateway of verified models from the OpenCode team — single API key.",
        "provider_type": PROVIDER_OPENCODE_ZEN,
        "environment": "cloud",
        "default_base_url": "https://opencode.ai/zen/v1",
        "requires_api_key": True,
        "api_key_hint": "Zen API key",
        "api_key_url": "https://opencode.ai/zen",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_NVIDIA,
        "label": "NVIDIA NIM",
        "description": "NVIDIA-hosted inference microservices — Nemotron, Llama, Qwen and more.",
        "provider_type": PROVIDER_NVIDIA,
        "environment": "cloud",
        "default_base_url": "https://integrate.api.nvidia.com/v1",
        "requires_api_key": True,
        "api_key_hint": "nvapi-…",
        "api_key_url": "https://build.nvidia.com/",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_OLLAMA,
        "label": "Ollama",
        "description": "Local models on your own machine — fully offline, no data leaves your network.",
        "provider_type": PROVIDER_OLLAMA,
        "environment": "local",
        # From inside the backend container the compose service name resolves;
        # from a host-run backend localhost works. Editable either way.
        "default_base_url": "http://ollama:11434",
        "requires_api_key": False,
        "api_key_hint": None,
        "api_key_url": None,
        "supports_discovery": True,
        "adapter": "OllamaProvider",
    },
    {
        "id": PROVIDER_OPENAI_COMPATIBLE,
        "label": "Custom / OpenAI-Compatible",
        "description": "Any OpenAI-compatible endpoint — vLLM, LM Studio, LocalAI, company gateways.",
        "provider_type": PROVIDER_OPENAI_COMPATIBLE,
        "environment": "custom",
        "default_base_url": "",
        "requires_api_key": False,   # optional — depends on the endpoint
        "api_key_hint": "sk-… (if required by your endpoint)",
        "api_key_url": None,
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
]


class LLMProvider(Base, TimestampMixin):
    """
    Configured LLM provider/model entry.

    Security notes:
    - api_key is stored here and MUST NEVER be returned through any GET endpoint.
    - Services reading this model must explicitly choose whether to include api_key.
    - Audit logs must never include api_key values.
    """
    __tablename__ = "llm_providers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # local | cloud | custom
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    # Base URL — required for Ollama and OpenAI-compatible; optional for cloud providers
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Model name as the provider expects it (e.g. "qwen3:14b", "gpt-4o", "claude-3-5-sonnet-20241022")
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # API key — NEVER expose through API; masked in all responses
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Whether this provider is available for selection
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Capabilities
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_embeddings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Optional description shown in UI
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)

    def __repr__(self) -> str:
        return f"<LLMProvider id={self.id} name={self.name} type={self.provider_type}>"
