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
PROVIDER_OLLAMA_DOCKER      = "ollama_docker"
PROVIDER_OPENAI             = "openai"
PROVIDER_ANTHROPIC          = "anthropic"
PROVIDER_GEMINI             = "gemini"
PROVIDER_OPENAI_COMPATIBLE  = "openai_compatible"
# Cloud gateway presets
PROVIDER_OPENROUTER         = "openrouter"
PROVIDER_OPENCODE_ZEN       = "opencode_zen"
PROVIDER_NVIDIA             = "nvidia"
PROVIDER_GROQ               = "groq"
PROVIDER_TOGETHER           = "together"
PROVIDER_DEEPSEEK           = "deepseek"
PROVIDER_MISTRAL            = "mistral"
PROVIDER_COHERE             = "cohere"
PROVIDER_PERPLEXITY         = "perplexity"
PROVIDER_FIREWORKS          = "fireworks"
PROVIDER_AI21               = "ai21"
PROVIDER_CLOUDFLARE         = "cloudflare"
PROVIDER_AZURE_OPENAI       = "azure_openai"
PROVIDER_HUGGINGFACE        = "huggingface"
PROVIDER_REPLICATE           = "replicate"
PROVIDER_bedrock            = "bedrock"
PROVIDER_OLLAMA_COMPATIBLE  = "ollama_compatible"

PROVIDER_TYPES = [
    PROVIDER_OLLAMA, PROVIDER_OLLAMA_DOCKER, PROVIDER_OPENAI,
    PROVIDER_ANTHROPIC, PROVIDER_GEMINI, PROVIDER_OPENAI_COMPATIBLE,
    PROVIDER_OPENROUTER, PROVIDER_OPENCODE_ZEN, PROVIDER_NVIDIA,
    PROVIDER_GROQ, PROVIDER_TOGETHER, PROVIDER_DEEPSEEK, PROVIDER_MISTRAL,
    PROVIDER_COHERE, PROVIDER_PERPLEXITY, PROVIDER_FIREWORKS, PROVIDER_AI21,
    PROVIDER_CLOUDFLARE, PROVIDER_AZURE_OPENAI, PROVIDER_HUGGINGFACE,
    PROVIDER_REPLICATE, PROVIDER_bedrock, PROVIDER_OLLAMA_COMPATIBLE,
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
        "id": PROVIDER_OLLAMA,
        "label": "Ollama (Local Machine)",
        "description": "Ollama running on your system — fully offline, no data leaves your network.",
        "provider_type": PROVIDER_OLLAMA,
        "environment": "local",
        "default_base_url": "http://host.docker.internal:11434",
        "requires_api_key": False,
        "api_key_hint": None,
        "api_key_url": None,
        "supports_discovery": True,
        "adapter": "OllamaProvider",
    },
    {
        "id": PROVIDER_OLLAMA_DOCKER,
        "label": "Ollama (Docker)",
        "description": "Ollama running inside Docker — for containerized deployments.",
        "provider_type": PROVIDER_OLLAMA,
        "environment": "local",
        "default_base_url": "http://ollama:11434",
        "requires_api_key": False,
        "api_key_hint": None,
        "api_key_url": None,
        "supports_discovery": True,
        "adapter": "OllamaProvider",
    },
    {
        "id": PROVIDER_OPENAI,
        "label": "OpenAI",
        "description": "GPT-4o, GPT-4.1, o3, o4-mini and more via the OpenAI API.",
        "provider_type": PROVIDER_OPENAI,
        "environment": "cloud",
        "default_base_url": "https://api.openai.com",
        "requires_api_key": True,
        "api_key_hint": "sk-…",
        "api_key_url": "https://platform.openai.com/api-keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_ANTHROPIC,
        "label": "Anthropic",
        "description": "Claude Opus, Sonnet, Haiku — via the Anthropic Messages API.",
        "provider_type": PROVIDER_ANTHROPIC,
        "environment": "cloud",
        "default_base_url": "https://api.anthropic.com",
        "requires_api_key": True,
        "api_key_hint": "sk-ant-…",
        "api_key_url": "https://console.anthropic.com/settings/keys",
        "supports_discovery": False,
        "adapter": "AnthropicProvider",
    },
    {
        "id": PROVIDER_GEMINI,
        "label": "Google Gemini",
        "description": "Gemini 2.5 Pro, Flash and more — Google's multimodal AI.",
        "provider_type": PROVIDER_GEMINI,
        "environment": "cloud",
        "default_base_url": "https://generativelanguage.googleapis.com",
        "requires_api_key": True,
        "api_key_hint": "AIza…",
        "api_key_url": "https://aistudio.google.com/apikey",
        "supports_discovery": True,
        "adapter": "GeminiProvider",
    },
    {
        "id": PROVIDER_GROQ,
        "label": "Groq",
        "description": "Ultra-fast inference on Llama, Mixtral, Gemma and more — LPU-powered.",
        "provider_type": PROVIDER_GROQ,
        "environment": "cloud",
        "default_base_url": "https://api.groq.com/openai/v1",
        "requires_api_key": True,
        "api_key_hint": "gsk_…",
        "api_key_url": "https://console.groq.com/keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_TOGETHER,
        "label": "Together AI",
        "description": "Open-source models at scale — Llama, Qwen, DeepSeek, Mixtral and 200+ more.",
        "provider_type": PROVIDER_TOGETHER,
        "environment": "cloud",
        "default_base_url": "https://api.together.xyz/v1",
        "requires_api_key": True,
        "api_key_hint": "tok_…",
        "api_key_url": "https://api.together.xyz/settings/api-keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_DEEPSEEK,
        "label": "DeepSeek",
        "description": "DeepSeek-V3, DeepSeek-R1 — advanced reasoning and coding models.",
        "provider_type": PROVIDER_DEEPSEEK,
        "environment": "cloud",
        "default_base_url": "https://api.deepseek.com",
        "requires_api_key": True,
        "api_key_hint": "sk-…",
        "api_key_url": "https://platform.deepseek.com/api_keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_MISTRAL,
        "label": "Mistral AI",
        "description": "Mistral Large, Medium, Small — European AI at its finest.",
        "provider_type": PROVIDER_MISTRAL,
        "environment": "cloud",
        "default_base_url": "https://api.mistral.ai/v1",
        "requires_api_key": True,
        "api_key_hint": "mist-…",
        "api_key_url": "https://console.mistral.ai/api-keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_COHERE,
        "label": "Cohere",
        "description": "Command R+, Command R — enterprise-grade LLMs with RAG support.",
        "provider_type": PROVIDER_COHERE,
        "environment": "cloud",
        "default_base_url": "https://api.cohere.com/v2",
        "requires_api_key": True,
        "api_key_hint": "…",
        "api_key_url": "https://dashboard.cohere.com/api-keys",
        "supports_discovery": False,
        "adapter": "CohereProvider",
    },
    {
        "id": PROVIDER_PERPLEXITY,
        "label": "Perplexity",
        "description": "Sonar models — AI with real-time web search grounding.",
        "provider_type": PROVIDER_PERPLEXITY,
        "environment": "cloud",
        "default_base_url": "https://api.perplexity.ai",
        "requires_api_key": True,
        "api_key_hint": "pplx-…",
        "api_key_url": "https://www.perplexity.ai/settings/api",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_FIREWORKS,
        "label": "Fireworks AI",
        "description": "Fast inference on open-source models — Llama, Qwen, Mixtral and more.",
        "provider_type": PROVIDER_FIREWORKS,
        "environment": "cloud",
        "default_base_url": "https://api.fireworks.ai/inference/v1",
        "requires_api_key": True,
        "api_key_hint": "fw_…",
        "api_key_url": "https://fireworks.ai/account/api-keys",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_AI21,
        "label": "AI21 Labs",
        "description": "Jamba, Jurassic — long-context models with SSM+Transformer hybrid.",
        "provider_type": PROVIDER_AI21,
        "environment": "cloud",
        "default_base_url": "https://api.ai21.com/studio/v1",
        "requires_api_key": True,
        "api_key_hint": "…",
        "api_key_url": "https://www.ai21.com/account/api-key",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_CLOUDFLARE,
        "label": "Cloudflare Workers AI",
        "description": "Run AI models on Cloudflare's global network — Llama, Mistral, Gemma.",
        "provider_type": PROVIDER_CLOUDFLARE,
        "environment": "cloud",
        "default_base_url": "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1",
        "requires_api_key": True,
        "api_key_hint": "Cloudflare API token",
        "api_key_url": "https://dash.cloudflare.com/profile/api-tokens",
        "supports_discovery": False,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_AZURE_OPENAI,
        "label": "Azure OpenAI",
        "description": "OpenAI models hosted on Microsoft Azure — enterprise compliance and SLAs.",
        "provider_type": PROVIDER_AZURE_OPENAI,
        "environment": "cloud",
        "default_base_url": "",
        "requires_api_key": True,
        "api_key_hint": "Azure API key",
        "api_key_url": "https://portal.azure.com",
        "supports_discovery": False,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_HUGGINGFACE,
        "label": "Hugging Face Inference",
        "description": "Serverless inference on 200k+ open-source models — free tier available.",
        "provider_type": PROVIDER_HUGGINGFACE,
        "environment": "cloud",
        "default_base_url": "https://api-inference.huggingface.co/v1",
        "requires_api_key": True,
        "api_key_hint": "hf_…",
        "api_key_url": "https://huggingface.co/settings/tokens",
        "supports_discovery": True,
        "adapter": "OpenAICompatibleProvider",
    },
    {
        "id": PROVIDER_REPLICATE,
        "label": "Replicate",
        "description": "Run open-source models via API — Llama, Flux, Stable Diffusion and more.",
        "provider_type": PROVIDER_REPLICATE,
        "environment": "cloud",
        "default_base_url": "https://api.replicate.com/v1",
        "requires_api_key": True,
        "api_key_hint": "r8_…",
        "api_key_url": "https://replicate.com/account/api-tokens",
        "supports_discovery": False,
        "adapter": "OpenAICompatibleProvider",
    },
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
        "default_custom_headers": {"HTTP-Referer": "https://sovereign-ai.app", "X-OpenRouter-Title": "Sovereign AI Workbench"},
    },
    {
        "id": PROVIDER_OPENCODE_ZEN,
        "label": "OpenCode Zen",
        "description": "7 free models (Big Pickle, MiMo-V2.5, Nemotron 3 Ultra, etc.) — no credit card required.",
        "provider_type": PROVIDER_OPENCODE_ZEN,
        "environment": "cloud",
        "default_base_url": "https://opencode.ai/zen/v1",
        "requires_api_key": True,
        "api_key_hint": "Zen API key",
        "api_key_url": "https://opencode.ai/auth",
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
        "id": PROVIDER_OLLAMA_COMPATIBLE,
        "label": "Custom Ollama-Compatible",
        "description": "Any Ollama-compatible endpoint — Jan, LM Studio (Ollama mode), etc.",
        "provider_type": PROVIDER_OLLAMA_COMPATIBLE,
        "environment": "custom",
        "default_base_url": "",
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
        "requires_api_key": False,
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
    environment: Mapped[str] = mapped_column(String(20), nullable=False, default="local")
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    model_name: Mapped[str] = mapped_column(String(200), nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_embeddings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    custom_headers: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<LLMProvider id={self.id} name={self.name} type={self.provider_type}>"
