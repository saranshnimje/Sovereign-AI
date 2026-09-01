"""System status and resource metrics service."""
import logging
import time
from functools import lru_cache

import httpx
import psutil

from config import get_settings
from schemas.system import ResourceMetrics, ServiceStatus, SystemStatus

logger = logging.getLogger(__name__)

# Simple in-process cache: (data, expiry_timestamp)
_status_cache: tuple[SystemStatus, float] | None = None
_STATUS_TTL = 5.0  # seconds


async def get_system_status() -> SystemStatus:
    """Return cached system status (refreshed every 5 seconds)."""
    global _status_cache
    now = time.monotonic()

    if _status_cache and now < _status_cache[1]:
        return _status_cache[0]

    settings = get_settings()
    services: dict[str, ServiceStatus] = {}

    # --- Ollama health ---
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.ollama_url + "/")
        latency = int((time.monotonic() - t0) * 1000)
        services["ollama"] = ServiceStatus(
            status="up" if resp.status_code < 500 else "down", latency_ms=latency
        )
    except Exception as exc:
        services["ollama"] = ServiceStatus(status="down", detail=str(exc)[:120])

    # --- Qdrant health ---
    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.qdrant_url + "/healthz")
        latency = int((time.monotonic() - t0) * 1000)
        services["qdrant"] = ServiceStatus(
            status="up" if resp.status_code == 200 else "down", latency_ms=latency
        )
    except Exception as exc:
        services["qdrant"] = ServiceStatus(status="down", detail=str(exc)[:120])

    # --- Database is always "up" if we got this far ---
    services["database"] = ServiceStatus(status="up")

    # --- Resource metrics ---
    resources = _get_resource_metrics()

    # --- Loaded models (currently running in memory) ---
    models_loaded: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.ollama_url + "/api/ps")
        if resp.status_code == 200:
            models_loaded = [m["name"] for m in resp.json().get("models", [])]
    except Exception:
        pass

    # Determine overall health
    down_count = sum(1 for s in services.values() if s.status == "down")
    if down_count == 0:
        overall = "healthy"
    elif down_count < len(services):
        overall = "degraded"
    else:
        overall = "unhealthy"

    status = SystemStatus(
        status=overall,
        services=services,
        resources=resources,
        models_loaded=models_loaded,
    )
    _status_cache = (status, time.monotonic() + _STATUS_TTL)
    return status


def _get_resource_metrics() -> ResourceMetrics:
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return ResourceMetrics(
            cpu_percent=round(cpu, 1),
            ram_used_gb=round(vm.used / (1024**3), 2),
            ram_total_gb=round(vm.total / (1024**3), 2),
            disk_used_gb=round(disk.used / (1024**3), 1),
            disk_total_gb=round(disk.total / (1024**3), 1),
            gpu_available=False,
        )
    except Exception:
        return ResourceMetrics(
            cpu_percent=0.0,
            ram_used_gb=0.0,
            ram_total_gb=0.0,
            disk_used_gb=0.0,
            disk_total_gb=0.0,
        )
