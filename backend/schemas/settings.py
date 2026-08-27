"""Pydantic schemas for system settings and dashboard summary."""
from pydantic import BaseModel, field_validator


class SystemSettings(BaseModel):
    """Runtime-configurable settings stored in the SQLite settings table."""
    # RAG
    default_chunk_size: int = 512
    default_chunk_overlap: int = 50
    default_top_k: int = 5
    default_score_threshold: float = 0.6

    # Agent
    default_max_iterations: int = 10
    approval_timeout_minutes: int = 5

    # Sandbox
    sandbox_timeout_s: int = 30
    sandbox_mem_limit_mb: int = 256
    sandbox_cpu_quota: int = 50000  # 50% of one CPU

    # Upload
    max_upload_size_mb: int = 50

    @field_validator("default_chunk_size")
    @classmethod
    def valid_chunk_size(cls, v: int) -> int:
        if not 64 <= v <= 4096:
            raise ValueError("Chunk size must be between 64 and 4096")
        return v

    @field_validator("default_chunk_overlap")
    @classmethod
    def valid_overlap(cls, v: int) -> int:
        if not 0 <= v <= 512:
            raise ValueError("Overlap must be between 0 and 512")
        return v

    @field_validator("default_max_iterations")
    @classmethod
    def valid_iterations(cls, v: int) -> int:
        if not 1 <= v <= 20:
            raise ValueError("Max iterations must be 1–20")
        return v

    @field_validator("approval_timeout_minutes")
    @classmethod
    def valid_timeout(cls, v: int) -> int:
        if not 1 <= v <= 60:
            raise ValueError("Approval timeout must be 1–60 minutes")
        return v

    @field_validator("sandbox_timeout_s")
    @classmethod
    def valid_sandbox_timeout(cls, v: int) -> int:
        if not 5 <= v <= 300:
            raise ValueError("Sandbox timeout must be 5–300 seconds")
        return v

    @field_validator("sandbox_mem_limit_mb")
    @classmethod
    def valid_mem(cls, v: int) -> int:
        if not 64 <= v <= 4096:
            raise ValueError("Memory limit must be 64–4096 MB")
        return v

    @field_validator("max_upload_size_mb")
    @classmethod
    def valid_upload(cls, v: int) -> int:
        if not 1 <= v <= 500:
            raise ValueError("Max upload size must be 1–500 MB")
        return v


class DashboardSummary(BaseModel):
    """Aggregated counts for the dashboard."""
    knowledge_base_count: int = 0
    document_count: int = 0
    agent_run_count: int = 0
    pending_approval_count: int = 0
    total_audit_events: int = 0
    sensor_analysis_count: int = 0
    incident_count: int = 0
    critical_risk_count: int = 0
    high_risk_count: int = 0
