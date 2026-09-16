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
from services.llm_client import OllamaClient, ModelUnavailableError

_bearer = HTTPBearer(auto_error=False)
_llm_client: OllamaClient | None = None


def get_llm_client() -> OllamaClient:
    global _llm_client
    settings = get_settings()
    if _llm_client is None:
        _llm_client = OllamaClient(settings.ollama_url)
    return _llm_client


class _FailoverLLM:
    """Provider failover wrapper used by agent/chat runtime.

    The selected role provider is tried first. On quota/rate-limit, timeout,
    connectivity, or provider-unavailable errors, the next enabled provider is
    tried automatically. Each provider keeps its own configured model name.
    """
    def __init__(self, providers):
        self.providers = providers
        self._cursor = 0

    async def chat(self, model, messages, stream=False, temperature=0.7, max_tokens=2048, system_prompt=None):
        errors = []
        if not self.providers:
            raise ModelUnavailableError("No configured LLM providers are available")
        for offset in range(len(self.providers)):
            idx = (self._cursor + offset) % len(self.providers)
            client, configured_model, label = self.providers[idx]
            effective_model = configured_model or model
            try:
                result = await client.chat(
                    model=effective_model,
                    messages=messages,
                    stream=stream,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                )
                self._cursor = idx
                return result
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                logger = __import__("logging").getLogger(__name__)
                logger.warning("LLM provider failed; trying next provider: %s", label, exc_info=True)
        raise ModelUnavailableError("All configured LLM providers failed. " + " | ".join(errors[-4:]))

    async def embed(self, model, texts):
        errors = []
        for client, configured_model, label in self.providers:
            try:
                return await client.embed(configured_model or model, texts)
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        raise ModelUnavailableError("All configured embedding providers failed. " + " | ".join(errors[-4:]))


async def resolve_llm_for_role_async(db: AsyncSession, role: str):
    """Resolve a role LLM with automatic provider failover."""
    from services.model_service import _load_roles
    from services.llm_client import build_provider
    from sqlalchemy import select as _select
    from models.provider import LLMProvider

    roles = _load_roles()
    bound_provider_id = roles.get(f"{role}_provider_id")
    result = await db.execute(_select(LLMProvider).where(LLMProvider.enabled == True))
    all_providers = list(result.scalars().all())

    # Prefer the role-bound provider, then the remaining enabled providers.
    all_providers.sort(key=lambda p: 0 if p.id == bound_provider_id else 1)
    providers = []
    for provider in all_providers:
        try:
            client = build_provider(
                provider_type=provider.provider_type,
                base_url=provider.base_url,
                api_key=provider.api_key,
                custom_headers=provider.custom_headers if hasattr(provider, 'custom_headers') and provider.custom_headers else None,
            )
            providers.append((client, getattr(provider, "model_name", None), provider.name))
        except Exception as exc:
            __import__("logging").getLogger(__name__).warning(
                "Skipping unavailable provider %s: %s", provider.name, exc
            )

    if providers:
        return _FailoverLLM(providers)
    return get_llm_client()


async def resolve_llm_with_failover(
    db: AsyncSession,
    role: str,
    exclude_provider_id: str | None = None,
    error: str | None = None,
):
    """Resolve an LLM client with provider failover."""
    from services.model_service import _load_roles
    from services.llm_client import build_provider
    from sqlalchemy import select as _select
    from models.provider import LLMProvider
    from services.provider_health import get_health_tracker, classify_provider_error

    health_tracker = get_health_tracker()
    if error and exclude_provider_id:
        is_rate_limit, _ = classify_provider_error(error)
        health_tracker.record_failure(exclude_provider_id, error, is_rate_limit)

    roles = _load_roles()
    provider_id = roles.get(f"{role}_provider_id")
    result = await db.execute(_select(LLMProvider).where(LLMProvider.enabled == True))
    all_providers = list(result.scalars().all())

    def sort_key(p):
        health = health_tracker.get(p.id)
        return (0 if p.id == provider_id else 1, health.consecutive_failures, health.avg_latency_ms)

    all_providers.sort(key=sort_key)
    for prov in all_providers:
        if prov.id == exclude_provider_id:
            continue
        health = health_tracker.get(prov.id)
        if not health.is_available():
            continue
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

    raise ModelUnavailableError(
        "All configured LLM providers are unavailable. Check provider health status and API keys."
    )


# ------------------------------------------------------------------
# Auth dependencies
# ------------------------------------------------------------------
async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(401, "Not authenticated")
    service = AuthService(db)
    return await service.verify_token(credentials.credentials)


def get_client_ip(request) -> str | None:
    from services.audit_service import _extract_client_ip
    return _extract_client_ip(request)


def require_role(*roles: str):
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(403, f"Insufficient permissions. Required: {list(roles)}, have: {user.role}")
        return user
    return _check


CurrentUser = Depends(get_current_user)
AdminRequired = Depends(require_role("admin"))
AnalystRequired = Depends(require_role("analyst", "admin"))
