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
    docker_path = "/app/data"
    if os.path.isdir(docker_path) or os.environ.get("RUNNING_IN_DOCKER"):
        return docker_path
    return str(Path(__file__).parent.parent / "data")


_DATA_DIR = _resolve_data_dir()


class Settings(BaseSettings):
    # ---- Core ----
    secret_key: str = "change-me-in-production-use-32-random-bytes"
    environment: str = "development"
    data_dir: str = _DATA_DIR
    log_level: str = "INFO"

    # ---- Database ----
    database_url: str = f"sqlite+aiosqlite:///{_DATA_DIR}/sqlite/sovereign.db"

    # ---- External services ----
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    ollama_url: str = "http://host.docker.internal:11434"

    # FRONTEND_ORIGIN is retained for backward compatibility.
    # FRONTEND_ORIGINS can contain a comma-separated allowlist of origins.
    frontend_origin: str = "http://localhost:5173"
    frontend_origins: str = ""

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
    default_max_iterations: int = 50
    default_max_tool_calls: int = 30
    default_max_execution_time_s: int = 600
    default_approval_risk_level: str = "high"
    approval_timeout_minutes: int = 5
    agent_max_subagent_depth: int = 10
    agent_max_subagent_concurrent: int = 5

    # ---- Terminal tools ----
    terminal_enabled: bool = True
    terminal_timeout_s: int = 30
    terminal_max_timeout_s: int = 120

    # ---- Sandbox ----
    sandbox_image: str = "python:3.11-slim"
    sandbox_timeout_s: int = 30
    sandbox_mem_limit_mb: int = 256
    sandbox_cpu_quota: int = 50000

    # ---- Rate limiting ----
    rate_limit_enabled: bool = True
    rate_limit_auth_per_min: int = 30
    rate_limit_upload_per_min: int = 30
    rate_limit_ai_per_min: int = 120

    # ---- Audit ----
    audit_retention_days: int = 365

    # ---- AI Models ----
    default_chat_model: str = "llama3.2:3b"
    default_vision_model: str = ""

    # ---- Neon Object Storage (S3-compatible) ----
    neon_storage_endpoint: str = ""
    neon_storage_region: str = "us-east-2"
    neon_storage_access_key: str = ""
    neon_storage_secret_key: str = ""
    neon_storage_bucket: str = ""

    # ---- Derived paths ----
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


_INSECURE_SECRET_MARKERS = (
    "change-me",
    "your-secret-key-here",
    "dev-secret-key",
    "test-secret",
)


def _apply_storage_env_aliases() -> None:
    """Normalize Neon Console/AWS S3 environment variable names."""
    aliases = {
        "NEON_STORAGE_ENDPOINT": ("NEON_STORAGE_ENDPOINT", "AWS_ENDPOINT_URL_S3"),
        "NEON_STORAGE_REGION": ("NEON_STORAGE_REGION", "AWS_REGION"),
        "NEON_STORAGE_ACCESS_KEY": ("NEON_STORAGE_ACCESS_KEY_ID", "NEON_STORAGE_ACCESS_KEY", "AWS_ACCESS_KEY_ID"),
        "NEON_STORAGE_SECRET_KEY": ("NEON_STORAGE_SECRET_ACCESS_KEY", "NEON_STORAGE_SECRET_KEY", "AWS_SECRET_ACCESS_KEY"),
        "NEON_STORAGE_BUCKET": ("NEON_STORAGE_BUCKET",),
    }
    for target, candidates in aliases.items():
        if os.environ.get(target, "").strip():
            continue
        for source in candidates:
            value = os.environ.get(source, "").strip()
            if value:
                os.environ[target] = value
                break


def _validate_production_secrets(settings: "Settings") -> None:
    """Refuse to boot in production with insecure secrets or missing object storage."""
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

    # Neon Object Storage is required for persistent document storage.
    # Without it, uploads silently go to Render's ephemeral disk and are lost on deploy.
    missing = []
    if not settings.neon_storage_endpoint:
        missing.append("NEON_STORAGE_ENDPOINT")
    if not settings.neon_storage_access_key:
        missing.append("NEON_STORAGE_ACCESS_KEY_ID")
    if not settings.neon_storage_secret_key:
        missing.append("NEON_STORAGE_SECRET_ACCESS_KEY")
    if not settings.neon_storage_bucket:
        missing.append("NEON_STORAGE_BUCKET")
    if missing:
        raise RuntimeError(
            "REFUSING TO START: Neon Object Storage is not configured "
            f"while ENVIRONMENT=production. Missing: {', '.join(missing)}. "
            "Without object storage, uploaded documents will be silently stored on "
            "Render's ephemeral disk and lost on the next deploy. "
            "Set these environment variables in the Render dashboard."
        )


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Call once per process."""
    _apply_storage_env_aliases()
    settings = Settings()
    _validate_production_secrets(settings)
    return settings
