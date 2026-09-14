"""
FastAPI dependency injection helpers.
All protected endpoints use these Depends() functions for auth and role checks.
"""
from fastapi import Cookie, Depends, HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from config import Settings, get_settings
from database import get_db
from models.user import User
from services.auth_service import AuthService
from services.llm_client import OllamaClient

_bearer = HTTPBearer(auto_error=False)

# Singleton LLM client (one per process)
_llm_client: OllamaClient | None = None


def get_llm_client() -> OllamaClient:
    global _llm_client
    settings = get_settings()
    if _llm_client is None:
        _llm_client = OllamaClient(settings.ollama_url)
    return _llm_client


async def resolve_llm_for_role_async(db: AsyncSession, role: str):
    """
    Return the LLM client for a given role ("chat" | "embedding" | "vision").

    If the role has a provider_id bound in the model-roles config, a client is
    built from that provider's stored connection (base_url + api_key).
    Otherwise falls back to the default local Ollama singleton.

    If the bound provider was deleted, gracefully falls back to the default.
    Never returns or logs provider credentials.
    """
    from services.model_service import _load_roles
    from services.llm_client import build_provider
    from sqlalchemy import select as _select
    from models.provider import LLMProvider

    async def _resolve() -> OllamaClient:
        roles = _load_roles()
        provider_id = roles.get(f"{role}_provider_id")
        if not provider_id:
            return get_llm_client()

        result = await db.execute(_select(LLMProvider).where(LLMProvider.id == provider_id))
        provider = result.scalar_one_or_none()
        if provider is None:
            return get_llm_client()

        return build_provider(
            provider_type=provider.provider_type,
            base_url=provider.base_url,
            api_key=provider.api_key,
            custom_headers=provider.custom_headers if hasattr(provider, 'custom_headers') and provider.custom_headers else None,
        )

    return _resolve()


async def resolve_llm_with_failover(
    db: AsyncSession,
    role: str,
    exclude_provider_id: str | None = None,
    error: str | None = None,
):
    """
    Resolve an LLM client with provider failover.

    When the primary provider fails (429, timeout, 5xx), this function
    tries the next available provider for the same role.

    Returns: (llm_client, provider_id) or raises if no providers available.
    """
    from services.model_service import _load_roles
    from services.llm_client import build_provider
    from sqlalchemy import select as _select
    from models.provider import LLMProvider
    from services.provider_health import get_health_tracker, classify_provider_error

    health_tracker = get_health_tracker()

    # If there was an error, record it for the failing provider
    if error and exclude_provider_id:
        is_rate_limit, _ = classify_provider_error(error)
        health_tracker.record_failure(exclude_provider_id, error, is_rate_limit)

    # Get all providers bound to this role, or all enabled providers
    roles = _load_roles()
    provider_id = roles.get(f"{role}_provider_id")

    # Get all enabled providers
    result = await db.execute(
        _select(LLMProvider).where(LLMProvider.enabled == True)
    )
    all_providers = list(result.scalars().all())

    # Sort: prefer the bound provider, then by health
    def sort_key(p):
        health = health_tracker.get(p.id)
        return (0 if p.id == provider_id else 1, health.consecutive_failures, health.avg_latency_ms)

    all_providers.sort(key=sort_key)

    # Try each provider
    for prov in all_providers:
        if prov.id == exclude_provider_id:
            continue  # Skip the one that just failed
        health = health_tracker.get(prov.id)
        if not health.is_available():
            continue  # Skip unhealthy providers
        try:
            client = build_provider(
                provider_type=prov.provider_type,
                base_url=prov.base_url,
                api_key=prov.api_key,
                custom_headers=prov.custom_headers if hasattr(prov, 'custom_headers') and prov.custom_headers else None,
            )
            return client, prov.id
        except Exception as exc:
            health_tracker.record_failure(prov.id, str(exc))
            continue

    # Fallback to default Ollama
    return get_llm_client(), None


# ------------------------------------------------------------------
# Auth dependencies
# ------------------------------------------------------------------

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Verify Bearer JWT. Raises 401 if missing or invalid."""
    if not credentials or not credentials.credentials:
        raise HTTPException(401, "Not authenticated")
    service = AuthService(db)
    return await service.verify_token(credentials.credentials)


def get_client_ip(request) -> str | None:
    """Extract real client IP — shared utility for audit propagation."""
    from services.audit_service import _extract_client_ip
    return _extract_client_ip(request)


def require_role(*roles: str):
    """Dependency factory — verifies the current user has one of the given roles."""

    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                403,
                f"Insufficient permissions. Required: {list(roles)}, have: {user.role}",
            )
        return user

    return _check


# Convenience shortcuts used in routers
CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_role("admin"))
AnalystRequired = Depends(require_role("analyst", "admin"))
