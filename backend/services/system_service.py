"""System status and resource metrics service."""
import asyncio
import json
import logging
import time

import httpx
import psutil
from sqlalchemy import select

from config import get_settings
from schemas.system import ResourceMetrics, ServiceStatus, SystemStatus

logger = logging.getLogger(__name__)
_status_cache: tuple[SystemStatus, float] | None = None
_status_refresh_task: asyncio.Task[SystemStatus] | None = None
_STATUS_TTL = 10.0
_MAX_DASHBOARD_MODELS = 4


async def get_system_status() -> SystemStatus:
    """Return cached system status and coalesce concurrent refreshes."""
    global _status_cache, _status_refresh_task

    now = time.monotonic()
    if _status_cache and now < _status_cache[1]:
        return _status_cache[0]

    task = _status_refresh_task
    if task is None or task.done():
        task = asyncio.create_task(_refresh_system_status())
        _status_refresh_task = task

    try:
        return await task
    finally:
        if task.done() and _status_refresh_task is task:
            _status_refresh_task = None


async def _refresh_system_status() -> SystemStatus:
    """Build a fresh status snapshot without holding DB connections during I/O."""
    global _status_cache
    settings = get_settings()
    services: dict[str, ServiceStatus] = {}
    providers: list[dict] = []
    all_models: list[str] = []

    try:
        from database import AsyncSessionLocal
        from models.provider import LLMProvider
        from models.provider_model import ProviderModel

        async with AsyncSessionLocal() as db:
            provider_result = await db.execute(select(LLMProvider).where(LLMProvider.enabled == True))  # noqa: E712
            enabled_providers = provider_result.scalars().all()
            provider_ids = [p.id for p in enabled_providers]

            if provider_ids:
                model_result = await db.execute(
                    select(ProviderModel.model_id, ProviderModel.display_name)
                    .where(
                        ProviderModel.provider_id.in_(provider_ids),
                        ProviderModel.status == "available",
                        ProviderModel.enabled == True,  # noqa: E712
                    )
                    .order_by(ProviderModel.display_name, ProviderModel.model_id)
                )
                seen_models: set[str] = set()
                for model_id, display_name in model_result.all():
                    name = (display_name or model_id or "").strip()
                    if name and name not in seen_models:
                        seen_models.add(name)
                        all_models.append(name)

            for p in enabled_providers:
                custom_h = None
                if p.custom_headers:
                    try:
                        custom_h = json.loads(p.custom_headers) if isinstance(p.custom_headers, str) else p.custom_headers
                    except (json.JSONDecodeError, TypeError):
                        pass
                providers.append({
                    "id": p.id,
                    "provider_type": p.provider_type,
                    "base_url": p.base_url,
                    "api_key": p.api_key,
                    "custom_headers": custom_h,
                })
    except Exception as exc:
        logger.warning("Failed to load LLM providers/models: %s", exc)

    models_loaded = all_models[:_MAX_DASHBOARD_MODELS]
    if len(all_models) > _MAX_DASHBOARD_MODELS:
        models_loaded.append(f"+{len(all_models) - _MAX_DASHBOARD_MODELS} more models")

    if not providers:
        services["llm"] = ServiceStatus(status="down", detail="Offline")
    else:
        from services.llm_client import build_provider

        async def check_provider(p: dict) -> bool:
            try:
                client = build_provider(
                    provider_type=p["provider_type"],
                    base_url=p["base_url"],
                    api_key=p["api_key"],
                    custom_headers=p["custom_headers"],
                )
                reachable, _latency = await client.health_check(None)
                return bool(reachable)
            except Exception:
                return False

        results = await asyncio.gather(*(check_provider(p) for p in providers), return_exceptions=True)
        healthy_count = sum(result is True for result in results)

        if healthy_count == 0:
            try:
                from database import AsyncSessionLocal
                from models.provider_model import ProviderModel

                async with AsyncSessionLocal() as db:
                    model_result = await db.execute(
                        select(ProviderModel.id).where(
                            ProviderModel.provider_id.in_([p["id"] for p in providers]),
                            ProviderModel.status == "available",
                            ProviderModel.enabled == True,  # noqa: E712
                        ).limit(1)
                    )
                    if model_result.scalar_one_or_none() is not None:
                        healthy_count = 1
            except Exception as exc:
                logger.warning("Failed to inspect enabled provider models: %s", exc)

        services["llm"] = ServiceStatus(
            status="up" if healthy_count else "down",
            detail="Online" if healthy_count else "Offline",
        )

    try:
        t0 = time.monotonic()
        qdrant_headers = {"api-key": settings.qdrant_api_key} if settings.qdrant_api_key else {}
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(settings.qdrant_url + "/healthz", headers=qdrant_headers)
        services["qdrant"] = ServiceStatus(
            status="up" if resp.status_code == 200 else "down",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
    except Exception as exc:
        services["qdrant"] = ServiceStatus(status="down", detail=str(exc)[:120])

    services["database"] = ServiceStatus(status="up")
    resources = _get_resource_metrics()
    down_count = sum(1 for s in services.values() if s.status == "down")
    overall = "healthy" if down_count == 0 else "degraded" if down_count < len(services) else "unhealthy"
    status = SystemStatus(
        status=overall,
        services=services,
        resources=resources,
        models_loaded=models_loaded,
    )
    _status_cache = (status, time.monotonic() + _STATUS_TTL)
    return status


def _get_resource_metrics() -> ResourceMetrics:
    """Return metrics matching the public ResourceMetrics API contract."""
    try:
        cpu = float(psutil.cpu_percent(interval=0.05))
        vm = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return ResourceMetrics(
            cpu_percent=cpu,
            ram_used_gb=vm.used / (1024 ** 3),
            ram_total_gb=vm.total / (1024 ** 3),
            disk_used_gb=disk.used / (1024 ** 3),
            disk_total_gb=disk.total / (1024 ** 3),
            gpu_available=False,
        )
    except Exception as exc:
        logger.warning("Failed to collect resource metrics: %s", exc)
        return ResourceMetrics(
            cpu_percent=0.0,
            ram_used_gb=0.0,
            ram_total_gb=0.0,
            disk_used_gb=0.0,
            disk_total_gb=0.0,
            gpu_available=False,
        )
