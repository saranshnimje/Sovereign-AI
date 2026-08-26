"""Pydantic schemas for system endpoints."""
from pydantic import BaseModel


class ServiceStatus(BaseModel):
    status: str  # up | down | unknown
    latency_ms: int | None = None
    detail: str | None = None


class ResourceMetrics(BaseModel):
    cpu_percent: float
    ram_used_gb: float
    ram_total_gb: float
    disk_used_gb: float
    disk_total_gb: float
    gpu_available: bool = False


class SystemStatus(BaseModel):
    status: str  # healthy | degraded | unhealthy
    services: dict[str, ServiceStatus]
    resources: ResourceMetrics
    models_loaded: list[str] = []


class HealthResponse(BaseModel):
    status: str = "ok"
