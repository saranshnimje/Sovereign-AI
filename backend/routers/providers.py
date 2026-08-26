"""
LLM Provider management router.

Security:
- GET endpoints NEVER return api_key (only has_api_key + api_key_masked hint)
- Create/Update/Delete/Test/enable-model are admin-only
- List/Get/model-catalog/presets/preferences are available to any authenticated user
- Model refresh queries the live provider via its adapter (read-only)
"""
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role, get_client_ip
from models.provider import PROVIDER_PRESETS
from models.user import User
from schemas.provider import (
    DiscoveredModel, ModelEnabledUpdate, ModelRecord,
    ProviderCreate, ProviderPreset, ProviderResponse,
    ProviderTestResult, ProviderUpdate,
)
from services.provider_service import ProviderService

router = APIRouter(tags=["providers"])


def _get_svc(db: AsyncSession = Depends(get_db)) -> ProviderService:
    return ProviderService(db)


# ── Presets (any authenticated user) ────────────────────────────
# NOTE: declared before /{provider_id} routes so "presets" is not treated as an id.
@router.get("/presets", response_model=list[ProviderPreset])
async def list_presets(_user=Depends(get_current_user)):
    """Provider presets for the Add-Provider picker."""
    return [ProviderPreset(**p) for p in PROVIDER_PRESETS]


# ── List (any authenticated user) ──────────────────────────────
@router.get("/", response_model=list[ProviderResponse])
async def list_providers(
    _user=Depends(get_current_user),
    svc: ProviderService = Depends(_get_svc),
):
    """Return all providers - api_key is never included."""
    return await svc.list_providers()


# ── Get (any authenticated user) ───────────────────────────────
@router.get("/{provider_id}", response_model=ProviderResponse)
async def get_provider(
    provider_id: str,
    _user=Depends(get_current_user),
    svc: ProviderService = Depends(_get_svc),
):
    return await svc.get(provider_id)


# ── Cached model catalog (any authenticated user) ──────────────
@router.get("/{provider_id}/models", response_model=list[ModelRecord])
async def get_provider_models(
    provider_id: str,
    _user=Depends(get_current_user),
    svc: ProviderService = Depends(_get_svc),
):
    """Return the persisted model catalog for a provider (no live call)."""
    return await svc.get_cached_models(provider_id)


# ── Refresh models from the live provider (any authenticated user) ──
@router.post("/{provider_id}/refresh", response_model=list[ModelRecord])
async def refresh_provider_models(
    provider_id: str,
    _user=Depends(get_current_user),
    svc: ProviderService = Depends(_get_svc),
):
    """
    Discover models live from the provider and upsert the local catalog.
    Newly installed models appear; removed ones are marked unavailable.
    """
    try:
        return await svc.refresh_models(provider_id)
    except HTTPException:
        raise


# ── Enable/disable a discovered model (admin only) ─────────────
@router.patch(
    "/{provider_id}/models/{model_record_id}",
    response_model=ModelRecord,
)
async def set_model_enabled(
    provider_id: str,
    model_record_id: str,
    data: ModelEnabledUpdate,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ProviderService = Depends(_get_svc),
):
    """Enable or disable a discovered model for selection in Chat."""
    return await svc.set_model_enabled(
        provider_id, model_record_id, data.enabled, user_id=admin.id,
        client_ip=get_client_ip(request)
    )


# ── Create (admin only) ────────────────────────────────────────
@router.post("/", response_model=ProviderResponse, status_code=201)
async def create_provider(
    data: ProviderCreate,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ProviderService = Depends(_get_svc),
):
    return await svc.create(data, user_id=admin.id, client_ip=get_client_ip(request))


# ── Update (admin only) ────────────────────────────────────────
@router.put("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    provider_id: str,
    data: ProviderUpdate,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ProviderService = Depends(_get_svc),
):
    return await svc.update(provider_id, data, user_id=admin.id, client_ip=get_client_ip(request))


# ── Delete (admin only) ────────────────────────────────────────
@router.delete("/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    request: Request,
    admin: User = Depends(require_role("admin")),
    svc: ProviderService = Depends(_get_svc),
):
    await svc.delete(provider_id, user_id=admin.id, client_ip=get_client_ip(request))


# ── Test connection (admin only) ───────────────────────────────
@router.post("/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(
    provider_id: str,
    _admin=Depends(require_role("admin")),
    svc: ProviderService = Depends(_get_svc),
):
    """
    Test connectivity to a provider.
    Returns success/latency/error/models_found — NEVER returns the api_key.
    """
    return await svc.test_connection(provider_id)
