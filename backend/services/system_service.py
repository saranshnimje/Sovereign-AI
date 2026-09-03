"""System status and resource metrics service."""
import json
import logging
import time
from functools import lru_cache

import httpx
import psutil
from sqlalchemy import select

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

    # --- Check actual configured LLM providers ---
    try:
        from database import async_session_factory
        from models.provider import LLMProvider

        async with async_session_factory() as db:
            result = await db.execute(
                select(LLMProvider).where(LLMProvider.enabled == True)  # noqa: E712
            )
            providers = result.scalars().all()

            if not providers:
                services["llm"] = ServiceStatus(status="down", detail="no providers configured")
            else:
                # Check each provider's health
                from services.llm_client import build_provider, _parse_custom_headers
                from services.provider_service import _parse_custom_headers as _ph

                healthy_count = 0
                total = len(providers)
                details = []

                for p in providers:
                    try:
                        custom_h = None
                        if p.custom_headers:
                            try:
                                custom_h = json.loads(p.custom_headers) if isinstance(p.custom_headers, str) else p.custom_headers
                            except (json.JSONDecodeError, TypeError):
                                pass

                        client = build_provider(
                            provider_type=p.provider_type,
                            base_url=p.base_url,
                            api_key=p.api_key,
                            custom_headers=custom_h,
                        )
                        reachable, latency = await client.health_check(None)
                        if reachable:
                            healthy_count += 1
                            details.append(f"{p.name}: up ({latency}ms)")
                        else:
                            details.append(f"{p.name}: down")
                    except Exception as exc:
                        details.append(f"{p.name}: error")

                if healthy_count > 0:
                    services["llm"] = ServiceStatus(
                        status="up",
                        detail="Online",
                    )
                else:
                    services["llm"] = ServiceStatus(
                        status="down",
                        detail="Offline",
                    )

    except Exception as exc:
        logger.warning("Failed to check LLM providers: %s", exc)
        services["llm"] = ServiceStatus(status="down", detail=str(exc)[:120])

    # --- Qdrant health ---
    try:
        t0 = time.monotonic()
        qdrant_headers = {}
        if settings.qdrant_api_key:
            qdrant_headers["api-key"] = settings.qdrant_api_key
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.qdrant_url + "/healthz", headers=qdrant_headers)
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
