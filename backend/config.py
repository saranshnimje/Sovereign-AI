"""
Application configuration — loads from environment variables via pydantic-settings.
All secrets come from the environment; never hard-coded here.
"""
import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


def _resolve_data_dir() -> str:
    """
    Determine the data directory.
    Priority:
      1. DATA_DIR environment variable (explicit override)
      2. /app/data  — the Docker volume mount point
    This avoids creating C:\\app\\data on Windows local dev.
    """
    env_val = os.environ.get("DATA_DIR", "").strip()
    if env_val:
        return env_val
    # Inside Docker the path exists; outside it may not.
    # Fall back to a local ./data directory for non-Docker dev.
    docker_path = "/app/data"
    if os.path.isdir(docker_path) or os.environ.get("RUNNING_IN_DOCKER"):
        return docker_path
    # Local development fallback — relative to project root
    return str(Path(__file__).parent.parent / "data")


_DATA_DIR = _resolve_data_dir()


class Settings(BaseSettings):
    # ---- Core ----
    secret_key: str = "change-me-in-production-use-32-random-bytes"
    # deployment mode: "development" (permissive) | "production" (fail-fast on insecure secrets)
    environment: str = "development"
    # DATA_DIR lets operators override where all persistent files live.
    # Docker: /app/data (volume-mounted).  Local dev: auto-detected.
    data_dir: str = _DATA_DIR
    log_level: str = "INFO"

    # ---- Database ----
    # If DATABASE_URL is set explicitly it takes precedence.
    # Otherwise constructed from data_dir so it moves with the volume.
    database_url: str = f"sqlite+aiosqlite:///{_DATA_DIR}/sqlite/sovereign.db"

    # ---- External services ----
    qdrant_url: str = "http://qdrant:6333"
    ollama_url: str = "http://host.docker.internal:11434"
    frontend_origin: str = "http://localhost:5173"

    # ---- Auth ----
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_min: int = 60
    jwt_refresh_ttl_days: int = 7

    # ---- Uploads ----
    max_upload_size_mb: int = 50
    allowed_mime_types: list[str] = [
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "text/plain",
        "text/markdown",
        "text/csv",
        "image/png",
        "image/jpeg",
        "image/webp",
    ]

    # ---- RAG ----
    default_embedding_model: str = "nomic-embed-text"
    default_chunk_size: int = 512
    default_chunk_overlap: int = 50
    default_top_k: int = 5
    default_score_threshold: float = 0.6
    embedding_batch_size: int = 32

    # ---- Agent ----
    default_max_iterations: int = 10
    default_approval_risk_level: str = "high"
    approval_timeout_minutes: int = 5

    # ---- Sandbox ----
    sandbox_image: str = "python:3.11-slim"
    sandbox_timeout_s: int = 30
    sandbox_mem_limit_mb: int = 256
    sandbox_cpu_quota: int = 50000  # 50% of one CPU

    # ---- Rate limiting (in-process sliding window, per client IP) ----
    # Disable with RATE_LIMIT_ENABLED=false. Limits are requests/minute/IP.
    # NOTE: per-process scope — multiple uvicorn workers each enforce their own bucket.
    rate_limit_enabled: bool = True
    rate_limit_auth_per_min: int = 30
    rate_limit_upload_per_min: int = 30
    rate_limit_ai_per_min: int = 120

    # ---- Audit ----
    audit_retention_days: int = 365

    # ---- AI Models (defaults shown in .env.example) ----
    default_chat_model: str = "llama3.2:3b"
    # Local vision-capable Ollama model for inspection images (e.g. "llava:7b").
    # EMPTY means vision is NOT configured — endpoints must then report
    # "Vision analysis unavailable" honestly instead of guessing.
    default_vision_model: str = ""

    # ---- Derived paths (read-only properties) ----
    @property
    def upload_dir(self) -> str:
        return str(Path(self.data_dir) / "uploads")

    @property
    def sandbox_workspace(self) -> str:
        return str(Path(self.data_dir) / "sandbox_workspace")

    @property
    def model_roles_file(self) -> str:
        return str(Path(self.data_dir) / "model_roles.json")

    @property
    def system_settings_file(self) -> str:
        return str(Path(self.data_dir) / "system_settings.json")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


# Secrets that must never reach production
_INSECURE_SECRET_MARKERS = (
    "change-me",
    "your-secret-key-here",
    "dev-secret-key",
    "test-secret",
)


def _validate_production_secrets(settings: "Settings") -> None:
    """
    Fail-fast guard: refuse to boot in production with insecure secrets.

    Development is explicitly permitted to use documented defaults.
    Production requires a real, high-entropy SECRET_KEY — the application
    will NOT silently generate or fall back to an insecure one.
    """
    if settings.environment.strip().lower() != "production":
        return

    key = settings.secret_key.strip()
    lowered = key.lower()
    if len(key) < 32:
        raise RuntimeError(
            "REFUSING TO START: SECRET_KEY is shorter than 32 characters "
            "and ENVIRONMENT=production. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    for marker in _INSECURE_SECRET_MARKERS:
        if marker in lowered:
            raise RuntimeError(
                "REFUSING TO START: SECRET_KEY looks like a placeholder/default value "
                f"('{marker}') while ENVIRONMENT=production. Set a real secret via "
                "the SECRET_KEY environment variable."
            )


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Call once per process."""
    settings = Settings()
    _validate_production_secrets(settings)
    return settings
