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
    """Provider/model failover wrapper used by chat and agent runtime."""
    def __init__(self, providers):
        self.providers = providers
        self._cursor = 0

    @staticmethod
    def _candidate_models(provider_type, configured_model, requested_model):
        primary = configured_model or requested_model
        candidates = [primary] if primary else []
        if provider_type == "gemini":
            for fallback_model in ("gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash"):
                if fallback_model not in candidates:
                    candidates.append(fallback_model)
        return candidates

    async def chat(self, model, messages, stream=False, temperature=0.7, max_tokens=2048, system_prompt=None):
        errors = []
        if not self.providers:
            raise ModelUnavailableError("No configured LLM providers are available")
        for offset in range(len(self.providers)):
            idx = (self._cursor + offset) % len(self.providers)
            client, configured_model, label = self.providers[idx]
            provider_type = getattr(client, "provider_type", None) or ""
            if not provider_type:
                provider_type = "gemini" if "gemini" in label.lower() or "gemini" in (configured_model or model or "").lower() else ""
            candidates = self._candidate_models(provider_type, configured_model, model)
            for effective_model in candidates or [model]:
                try:
                    result = await client.chat(model=effective_model, messages=messages, stream=stream, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt)
                    self._cursor = idx
                    return result
                except Exception as exc:
                    errors.append(f"{label}/{effective_model}: {exc}")
                    import logging
                    logging.getLogger(__name__).warning("LLM provider/model failed; trying next candidate: %s/%s", label, effective_model, exc_info=True)
        raise ModelUnavailableError("All configured LLM providers/models failed. " + " | ".join(errors[-8:]))

    async def embed(self, model, texts):
        errors = []
        for client, configured_model, label in self.providers:
            try:
                return await client.embed(configured_model or model, texts)
            except Exception as exc:
                errors.append(f"{label}: {exc}")
        raise ModelUnavailableError("All configured embedding providers failed. " + " | ".join(errors[-4:]))

    async def health_check(self, model=None):
        """Return aggregate provider health for system status and provider tests."""
        for client, configured_model, _label in self.providers:
            try:
                reachable, latency = await client.health_check(configured_model or model)
                if reachable:
                    return True, latency
            except Exception:
                continue
        return False, None

    async def list_models(self):
        models = []
        for client, _configured_model, _label in self.providers:
            try:
                models.extend(await client.list_models())
            except Exception:
                continue
        return models


class _ExplicitProviderFailover:
    """Wrap a UI-selected provider and fail over using DB-configured models."""
    def __init__(self, primary, base_url: str | None, provider_type: str | None):
        self._primary = primary
        self._base_url = (base_url or "").rstrip("/")
        self._provider_type = provider_type
        self._failed_over = False
        self.provider_type = provider_type

    async def chat(self, model, messages, stream=False, temperature=0.7, max_tokens=2048, system_prompt=None):
        candidates = [model] if model else []
        if self._provider_type == "gemini":
            for fallback_model in ("gemini-2.5-flash-lite", "gemini-3.5-flash-lite", "gemini-2.5-flash"):
                if fallback_model not in candidates:
                    candidates.append(fallback_model)
        errors = []
        for effective_model in candidates or [model]:
            try:
                return await self._primary.chat(model=effective_model, messages=messages, stream=stream, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt)
            except Exception as primary_exc:
                errors.append(f"{self._provider_type}/{effective_model}: {primary_exc}")
                import logging
                logging.getLogger(__name__).warning("Explicit provider/model failed: %s/%s; trying fallback candidate", self._provider_type, effective_model, exc_info=True)
        if self._failed_over:
            raise ModelUnavailableError("Selected provider failed after model fallbacks: " + " | ".join(errors[-4:]))
        self._failed_over = True
        fallback = await self._resolve_fallback()
        if fallback is None:
            raise ModelUnavailableError("Selected provider failed and no alternate enabled provider is configured. " + " | ".join(errors[-4:]))
        client, fallback_model, label = fallback
        try:
            return await client.chat(model=fallback_model or model, messages=messages, stream=stream, temperature=temperature, max_tokens=max_tokens, system_prompt=system_prompt)
        except Exception as fallback_exc:
            raise ModelUnavailableError(f"Selected provider and fallback provider failed: {'; '.join(errors[-2:])}; {fallback_exc}") from fallback_exc

    async def embed(self, model, texts):
        return await self._primary.embed(model, texts)

    async def health_check(self, model=None):
        return await self._primary.health_check(model)

    async def list_models(self):
        return await self._primary.list_models()

    async def verify_auth(self, model=None):
        verifier = getattr(self._primary, "verify_auth", None)
        if verifier:
            return await verifier(model)
        return None, None

    async def _resolve_fallback(self):
        try:
            from database import AsyncSessionLocal
            from models.provider import LLMProvider
            from services.llm_client import build_provider as raw_build_provider
            from sqlalchemy import select
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(LLMProvider).where(LLMProvider.enabled == True))
                providers = list(result.scalars().all())
            for provider in providers:
                if (provider.base_url or "").rstrip("/") == self._base_url and provider.provider_type == self._provider_type:
                    continue
                try:
                    client = raw_build_provider(provider_type=provider.provider_type, base_url=provider.base_url, api_key=provider.api_key, custom_headers=provider.custom_headers if hasattr(provider, "custom_headers") and provider.custom_headers else None)
                    return client, getattr(provider, "model_name", None), provider.name
                except Exception:
                    continue
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Unable to resolve explicit-provider fallback: %s", exc)
        return None


from services import llm_client as _llm_client_module
_raw_build_provider = _llm_client_module.build_provider


def _build_provider_with_runtime_failover(provider_type, base_url, api_key, timeout=600.0, custom_headers=None):
    primary = _raw_build_provider(provider_type=provider_type, base_url=base_url, api_key=api_key, timeout=timeout, custom_headers=custom_headers)
    return _ExplicitProviderFailover(primary, base_url, provider_type)


_llm_client_module.build_provider = _build_provider_with_runtime_failover


async def _build_failover(db: AsyncSession, preferred_provider_id: str | None = None, role: str = "chat"):
    from services.model_service import _load_roles
    from sqlalchemy import select as _select
    from models.provider import LLMProvider
    roles = _load_roles()
    preferred = preferred_provider_id or roles.get(f"{role}_provider_id")
    result = await db.execute(_select(LLMProvider).where(LLMProvider.enabled == True))
    all_providers = list(result.scalars().all())
    all_providers.sort(key=lambda p: 0 if p.id == preferred else 1)
    providers = []
    for provider in all_providers:
        try:
            client = _raw_build_provider(provider_type=provider.provider_type, base_url=provider.base_url, api_key=provider.api_key, custom_headers=provider.custom_headers if hasattr(provider, 'custom_headers') and provider.custom_headers else None)
            try:
                client.provider_type = provider.provider_type
            except Exception:
                pass
            providers.append((client, getattr(provider, "model_name", None), provider.name))
        except Exception as exc:
            import logging
            logging.getLogger(__name__).warning("Skipping unavailable provider %s: %s", provider.name, exc)
    return _FailoverLLM(providers) if providers else get_llm_client()


async def resolve_llm_for_role_async(db: AsyncSession, role: str):
    return await _build_failover(db, role=role)


async def resolve_llm_for_provider_async(db: AsyncSession, provider_id: str, role: str = "chat"):
    return await _build_failover(db, preferred_provider_id=provider_id, role=role)


async def resolve_llm_with_failover(db: AsyncSession, role: str, exclude_provider_id: str | None = None, error: str | None = None):
    from services.model_service import _load_roles
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
            client = _raw_build_provider(provider_type=prov.provider_type, base_url=prov.base_url, api_key=prov.api_key, custom_headers=prov.custom_headers if hasattr(prov, 'custom_headers') and prov.custom_headers else None)
            try:
                client.provider_type = prov.provider_type
            except Exception:
                pass
            return client, prov.id
        except Exception as exc:
            health_tracker.record_failure(prov.id, str(exc))
    raise ModelUnavailableError("All configured LLM providers are unavailable. Check provider health status and API keys.")


async def get_current_user(credentials: HTTPAuthorizationCredentials | None = Security(_bearer), db: AsyncSession = Depends(get_db)) -> User:
    if not credentials or not credentials.credentials:
        raise HTTPException(401, "Not authenticated")
    return await AuthService(db).verify_token(credentials.credentials)


def get_client_ip(request) -> str | None:
    from services.audit_service import _extract_client_ip
    return _extract_client_ip(request)
