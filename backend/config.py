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

    # ---- Audit ----
    audit_retention_days: int = 365

    # ---- AI Models (defaults shown in .env.example) ----
    default_chat_model: str = "llama3.2:3b"

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


@lru_cache
def get_settings() -> Settings:
    """Return cached Settings instance. Call once per process."""
    return Settings()
