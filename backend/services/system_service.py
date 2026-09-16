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
_status_cache: tuple[SystemStatus, float] | None = None
_STATUS_TTL = 5.0


async def get_system_status() -> SystemStatus:
    global _status_cache
    now = time.monotonic()
    if _status_cache and now < _status_cache[1]:
        return _status_cache[0]

    settings = get_settings()
    services: dict[str, ServiceStatus] = {}

    try:
        from database import AsyncSessionLocal
        from models.provider import LLMProvider
        from models.provider_model import ProviderModel

        async with AsyncSessionLocal() as db:
            result = await db.execute(select(LLMProvider).where(LLMProvider.enabled == True))  # noqa: E712
            providers = result.scalars().all()
            if not providers:
                services["llm"] = ServiceStatus(status="down", detail="Offline")
            else:
                from services.llm_client import build_provider
                healthy_count = 0
                for p in providers:
                    try:
                        custom_h = None
                        if p.custom_headers:
                            try:
                                custom_h = json.loads(p.custom_headers) if isinstance(p.custom_headers, str) else p.custom_headers
                            except (json.JSONDecodeError, TypeError):
                                pass
                        client = build_provider(provider_type=p.provider_type, base_url=p.base_url, api_key=p.api_key, custom_headers=custom_h)
                        reachable, _latency = await client.health_check(None)
                        if reachable:
                            healthy_count += 1
                    except Exception:
                        pass

                if healthy_count == 0:
                    model_result = await db.execute(
                        select(ProviderModel).where(
                            ProviderModel.provider_id.in_([p.id for p in providers]),
                            ProviderModel.status == "available",
                            ProviderModel.enabled == True,  # noqa: E712
                        )
                    )
                    if model_result.scalars().first():
                        healthy_count = 1

                services["llm"] = ServiceStatus(status="up" if healthy_count else "down", detail="Online" if healthy_count else "Offline")
    except Exception as exc:
        logger.warning("Failed to check LLM providers: %s", exc)
        services["llm"] = ServiceStatus(status="down", detail=str(exc)[:120])

    try:
        t0 = time.monotonic()
        qdrant_headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.qdrant_url + "/healthz", headers=qdrant_headers)
        services["qdrant"] = ServiceStatus(status="up" if resp.status_code == 200 else "down", latency_ms=int((time.monotonic() - t0) * 1000))
    except Exception as exc:
        services["qdrant"] = ServiceStatus(status="down", detail=str(exc)[:120])

    services["database"] = ServiceStatus(status="up")
    resources = _get_resource_metrics()
    models_loaded: list[str] = []
    down_count = sum(1 for s in services.values() if s.status == "down")
    overall = "healthy" if down_count == 0 else "degraded" if down_count < len(services) else "unhealthy"
    status = SystemStatus(status=overall, services=services, resources=resources, models_loaded=models_loaded)
    _status_cache = (status, time.monotonic() + _STATUS_TTL)
    return status


def _get_resource_metrics() -> ResourceMetrics:
    try:
        cpu = psutil.cpu_percent(interval=0.1)
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return ResourceMetrics(cpu_percent=cpu, memory_percent=vm.percent, disk_percent=disk.percent)
    except Exception:
        return ResourceMetrics()
