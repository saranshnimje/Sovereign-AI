"""
Provider service — CRUD for LLM provider configurations.

Security invariants:
- api_key is NEVER returned in any list/get operation.
- api_key is NEVER included in audit log metadata.
- Only admin can create/update/delete providers.
- Analysts and viewers can list enabled providers (without key).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import delete as _delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.base import generate_uuid
from models.provider import LLMProvider, PROVIDER_OLLAMA
from models.provider_model import ProviderModel
from schemas.provider import (
    DiscoveredModel, ModelRecord, ProviderCreate, ProviderResponse,
    ProviderTestResult, ProviderUpdate,
)
from services.audit_service import AuditService
from services.llm_client import ModelUnavailableError, build_provider

logger = logging.getLogger(__name__)


def _mask_key(api_key: str | None) -> str | None:
    """Safe masked representation — at most the last 4 characters."""
    if not api_key:
        return None
    tail = api_key[-4:] if len(api_key) >= 4 else ""
    return "••••••••" + tail

# Friendly error hints keyed by exception content. Never include api_key or URLs
# containing credentials in the returned message.
_ERROR_HINTS = [
    ("connect", "Connection failed — provider is unreachable"),
    ("timed out", "Connection timed out"),
    ("timeout", "Connection timed out"),
    ("401", "Authentication failed — invalid API key"),
    ("403", "Access denied by provider — check API key permissions"),
    ("404", "Endpoint not found — check the Base URL"),
    ("api key", "Invalid or missing API key"),
]


def _friendly_error(msg: str) -> str:
    low = msg.lower()
    for needle, friendly in _ERROR_HINTS:
        if needle in low:
            return friendly
    return msg[:200]


def _sanitize(msg: str, api_key: str | None) -> str:
    """Strip the raw api_key from any error text before it leaves the service."""
    if api_key and api_key in msg:
        return "Connection error (details hidden for security)"
    return msg


def _parse_custom_headers(raw: str | None) -> dict[str, str] | None:
    """Parse custom_headers JSON string from DB, return dict or None."""
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    return None


def _to_response(p: LLMProvider, model_count: int | None = None) -> ProviderResponse:
    """Convert ORM object to safe schema — api_key deliberately excluded."""
    return ProviderResponse(
        id=p.id,
        name=p.name,
        provider_type=p.provider_type,
        environment=p.environment,
        base_url=p.base_url,
        model_name=p.model_name or "",
        has_api_key=bool(p.api_key),   # boolean only — never the key
        api_key_masked=_mask_key(p.api_key),
        enabled=p.enabled,
        supports_streaming=p.supports_streaming,
        supports_embeddings=p.supports_embeddings,
        description=p.description,
        custom_headers=_parse_custom_headers(p.custom_headers),
        model_count=model_count if model_count is not None else 0,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


async def _model_counts(db: AsyncSession, provider_ids: list[str]) -> dict[str, int]:
    """Count selectable (available + enabled) models per provider in one query."""
    if not provider_ids:
        return {}
    result = await db.execute(
        select(ProviderModel.provider_id, func.count())
        .where(
            ProviderModel.provider_id.in_(provider_ids),
            ProviderModel.status == "available",
            ProviderModel.enabled == True,  # noqa: E712
        )
        .group_by(ProviderModel.provider_id)
    )
    return {pid: n for pid, n in result.all()}


class ProviderService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ------------------------------------------------------------------
    # Create
    # ------------------------------------------------------------------
    async def create(self, data: ProviderCreate, user_id: str,
        client_ip: str | None = None) -> ProviderResponse:
        p = LLMProvider(
            id=generate_uuid(),
            name=data.name,
            provider_type=data.provider_type,
            environment=data.environment,
            base_url=data.base_url,
            model_name=data.model_name or "",
            api_key=data.api_key,
            enabled=data.enabled,
            supports_streaming=data.supports_streaming,
            supports_embeddings=data.supports_embeddings,
            description=data.description,
            custom_headers=json.dumps(data.custom_headers) if data.custom_headers else None,
        )
        self.db.add(p)
        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "config", "provider.created", "success",
            user_id=user_id,
            resource_type="llm_provider", resource_id=p.id,
            # SECURITY: api_key deliberately excluded from audit metadata
            metadata={"name": p.name, "type": p.provider_type},
            ip_address=client_ip,
        )
        return _to_response(p)

    # ------------------------------------------------------------------
    # List
    # ------------------------------------------------------------------
    async def list_providers(self, enabled_only: bool = False) -> list[ProviderResponse]:
        q = select(LLMProvider).order_by(LLMProvider.created_at)
        if enabled_only:
            q = q.where(LLMProvider.enabled == True)  # noqa: E712
        result = await self.db.execute(q)
        providers = list(result.scalars().all())
        counts = await _model_counts(self.db, [p.id for p in providers])
        return [_to_response(p, counts.get(p.id, 0)) for p in providers]

    # ------------------------------------------------------------------
    # Get (safe — no api_key)
    # ------------------------------------------------------------------
    async def get(self, provider_id: str) -> ProviderResponse:
        p = await self._get_raw(provider_id)
        counts = await _model_counts(self.db, [p.id])
        return _to_response(p, counts.get(p.id, 0))

    # ------------------------------------------------------------------
    # Update
    # ------------------------------------------------------------------
    async def update(
        self, provider_id: str, data: ProviderUpdate, user_id: str,
        client_ip: str | None = None,
    ) -> ProviderResponse:
        p = await self._get_raw(provider_id)
        if data.name is not None:
            p.name = data.name
        if data.environment is not None:
            p.environment = data.environment
        if data.base_url is not None:
            p.base_url = data.base_url
        if data.model_name is not None:
            p.model_name = data.model_name
        if data.api_key is not None:
            p.api_key = data.api_key     # replace key — never logged
        if data.enabled is not None:
            p.enabled = data.enabled
        if data.supports_streaming is not None:
            p.supports_streaming = data.supports_streaming
        if data.supports_embeddings is not None:
            p.supports_embeddings = data.supports_embeddings
        if data.description is not None:
            p.description = data.description
        if data.custom_headers is not None:
            p.custom_headers = json.dumps(data.custom_headers) if data.custom_headers else None
        await self.db.flush()

        # Re-fetch to get server-generated updated_at without triggering MissingGreenlet
        updated = await self._get_raw(provider_id)
        counts = await _model_counts(self.db, [provider_id])
        audit = AuditService(self.db)
        await audit.log(
            "config", "provider.updated", "success",
            user_id=user_id,
            resource_type="llm_provider", resource_id=provider_id,
            metadata={"name": updated.name, "type": updated.provider_type},
            ip_address=client_ip,
        )
        return _to_response(updated, counts.get(provider_id, 0))

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------
    async def delete(self, provider_id: str, user_id: str,
        client_ip: str | None = None) -> None:
        p = await self._get_raw(provider_id)
        name = p.name
        await self.db.delete(p)
        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "config", "provider.deleted", "success",
            user_id=user_id,
            resource_type="llm_provider", resource_id=provider_id,
            metadata={"name": name},
            ip_address=client_ip,
        )

    # ------------------------------------------------------------------
    # Test connection
    # ------------------------------------------------------------------
    async def test_connection(self, provider_id: str) -> ProviderTestResult:
        """
        Test connectivity + authentication + model listing against the provider.

        Steps:
          1. health_check()  → endpoint reachable / auth accepted
          2. list_models()   → provider can enumerate its models

        Returns ProviderTestResult — NEVER includes api_key or stack traces.
        """
        p = await self._get_raw(provider_id)
        t0 = time.monotonic()
        try:
            client = build_provider(
                provider_type=p.provider_type,
                base_url=p.base_url,
                api_key=p.api_key,
                custom_headers=_parse_custom_headers(p.custom_headers),
            )
            ok, latency = await client.health_check(p.model_name or None)
            if not ok:
                return ProviderTestResult(
                    success=False,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    provider=p.provider_type,
                    model=p.model_name or "",
                    error="Connection failed — service may be unavailable",
                )

            # Reachable — try enumerating models as part of validation
            models_found: int | None = None
            discovery_error: str | None = None
            first_model: str | None = None
            try:
                raw_models = await client.list_models()
                models_found = len(raw_models)
                logger.info("test_connection provider=%s models_found=%d first_model=%s", provider_id, models_found, first_model)
                for m in raw_models or []:
                    if isinstance(m, dict):
                        first_model = m.get("id") or m.get("name") or m.get("model")
                        if first_model:
                            break
            except ModelUnavailableError as exc:
                discovery_error = _friendly_error(_sanitize(str(exc), p.api_key))
                logger.warning("test_connection provider=%s ModelUnavailableError: %s", provider_id, discovery_error)
            except Exception as exc:
                discovery_error = "Connected, but model listing is not supported by this endpoint"
                logger.warning("test_connection provider=%s list_models exception: %s", provider_id, exc)

            # Skip deep auth probe when models were already listed — that already
            # proves the key works and avoids false negatives on providers where
            # free models use different endpoints (e.g. OpenCode Zen uses
            # /v1/responses for some models, not /v1/chat/completions).
            verify = getattr(client, "verify_auth", None)
            if verify is not None and p.api_key and models_found is None:
                try:
                    auth_ok, auth_msg = await verify(first_model)
                except Exception:
                    auth_ok, auth_msg = None, None
                if auth_ok is False:
                    return ProviderTestResult(
                        success=False,
                        latency_ms=int((time.monotonic() - t0) * 1000),
                        provider=p.provider_type,
                        model=p.model_name or "",
                        error=auth_msg or "Authentication failed",
                        models_found=models_found,
                    )

            elapsed = latency or int((time.monotonic() - t0) * 1000)
            return ProviderTestResult(
                success=True,
                latency_ms=elapsed,
                provider=p.provider_type,
                model=p.model_name or "",
                error=discovery_error,
                models_found=models_found,
            )
        except ModelUnavailableError as exc:
            return ProviderTestResult(
                success=False,
                latency_ms=int((time.monotonic() - t0) * 1000),
                provider=p.provider_type,
                model=p.model_name or "",
                error=_friendly_error(_sanitize(str(exc), p.api_key)),
            )
        except Exception as exc:
            return ProviderTestResult(
                success=False,
                latency_ms=int((time.monotonic() - t0) * 1000),
                provider=p.provider_type,
                model=p.model_name or "",
                error=_friendly_error(_sanitize(str(exc), p.api_key)),
            )

    # ------------------------------------------------------------------
    # Model discovery — live from the provider API via its adapter
    # ------------------------------------------------------------------
    async def discover_models(self, provider_id: str) -> list[DiscoveredModel]:
        """
        Query the provider for its available models using the type-specific adapter.

        Only fields returned by the provider are populated on each DiscoveredModel;
        nothing is fabricated. Raises HTTPException(502/504-style plain errors)
        when the provider cannot be reached or returns a malformed response.
        """
        p = await self._get_raw(provider_id)
        try:
            client = build_provider(
                provider_type=p.provider_type,
                base_url=p.base_url,
                api_key=p.api_key,
                custom_headers=_parse_custom_headers(p.custom_headers),
            )
            reachable, _latency = await client.health_check(None)
            if not reachable:
                raise HTTPException(
                    502,
                    "Connection failed — provider is unreachable",
                )
            raw = await client.list_models()
            logger.info("discover_models: provider=%s raw_count=%d", provider_id, len(raw or []))
        except HTTPException:
            raise
        except ModelUnavailableError as exc:
            raise HTTPException(502, _friendly_error(_sanitize(str(exc), p.api_key)))
        except Exception as exc:
            raise HTTPException(502, _friendly_error(_sanitize(str(exc), p.api_key)))

        results: list[DiscoveredModel] = []
        for m in raw or []:
            if not isinstance(m, dict):
                continue
            name = (
                m.get("id")
                or m.get("model")
                or m.get("name")
            )
            if not name:
                continue  # skip malformed entries rather than fabricating one

            details = m.get("details") or {}
            dm = DiscoveredModel(
                name=str(name),
                display_name=str(name),
                family=(
                    details.get("family")
                    or (str(m.get("owned_by")) if m.get("owned_by") else None)
                    or (m.get("family") if isinstance(m.get("family"), str) else None)
                ),
                parameter_size=details.get("parameter_size"),
                quantization=details.get("quantization_level"),
                size_bytes=m.get("size"),
                modified_at=str(m.get("modified_at")) if m.get("modified_at") else None,
                context_length=(
                    m.get("context_length") if isinstance(m.get("context_length"), int) else None
                ),
                status="available",
            )
            results.append(dm)
        logger.info("discover_models: provider=%s parsed_count=%d names=%s", provider_id, len(results), [r.name for r in results])
        return results

    # ------------------------------------------------------------------
    # Seed the default Ollama provider if no providers exist
    # ------------------------------------------------------------------
    async def seed_default_ollama(self, ollama_url: str) -> None:
        """
        Creates the built-in Ollama provider entry on first startup.
        Idempotent — skips if any provider already exists.

        The seeded provider stores CONNECTION info only; models are discovered
        live from Ollama and are not pinned here.
        """
        result = await self.db.execute(select(LLMProvider).limit(1))
        if result.scalar_one_or_none() is not None:
            return  # already seeded

        p = LLMProvider(
            id=generate_uuid(),
            name="Ollama (local)",
            provider_type=PROVIDER_OLLAMA,
            environment="local",
            base_url=ollama_url,
            model_name="",   # no pinned model — discovery-driven
            enabled=True,
            supports_streaming=True,
            supports_embeddings=True,
            description="Local Ollama instance — no data leaves your network",
        )
        self.db.add(p)
        await self.db.flush()
        logger.info("Seeded default Ollama provider at %s", ollama_url)

    # ------------------------------------------------------------------
    # Model catalog — persisted discovery results (ProviderModel table)
    # ------------------------------------------------------------------
    @staticmethod
    def _record_to_schema(r: ProviderModel) -> ModelRecord:
        return ModelRecord(
            id=r.id,
            provider_id=r.provider_id,
            model_id=r.model_id,
            display_name=r.display_name,
            family=r.family,
            parameter_size=r.parameter_size,
            quantization=r.quantization,
            size_bytes=r.size_bytes,
            modified_at=r.modified_at,
            context_length=r.context_length,
            status=r.status,
            enabled=r.enabled,
        )

    async def refresh_models(self, provider_id: str) -> list[ModelRecord]:
        """
        Discover models live from the provider and upsert the local catalog.

        - New/changed models are inserted or updated.
        - Models no longer reported by the provider are marked
          status="unavailable" (rows preserved — never silently deleted).
        - Returns the refreshed catalog.
        """
        discovered = await self.discover_models(provider_id)
        logger.info("refresh_models: discovered %d models for provider %s", len(discovered), provider_id)
        now = datetime.now(timezone.utc)

        result = await self.db.execute(
            select(ProviderModel).where(ProviderModel.provider_id == provider_id)
        )
        existing = {r.model_id: r for r in result.scalars().all()}

        seen_ids: set[str] = set()
        for dm in discovered:
            seen_ids.add(dm.name)
            row = existing.get(dm.name)
            if row is None:
                self.db.add(ProviderModel(
                    id=generate_uuid(),
                    provider_id=provider_id,
                    model_id=dm.name,
                    display_name=dm.display_name or dm.name,
                    family=dm.family,
                    parameter_size=dm.parameter_size,
                    quantization=dm.quantization,
                    size_bytes=dm.size_bytes,
                    modified_at=dm.modified_at,
                    context_length=dm.context_length,
                    status="available",
                    enabled=True,           # new models start enabled
                    last_seen_at=now,
                ))
            else:
                row.display_name = dm.display_name or dm.name
                row.family = dm.family
                row.parameter_size = dm.parameter_size
                row.quantization = dm.quantization
                row.size_bytes = dm.size_bytes
                row.modified_at = dm.modified_at
                row.context_length = dm.context_length
                row.status = "available"
                row.last_seen_at = now

        # Mark models the provider no longer reports
        for model_id, row in existing.items():
            if model_id not in seen_ids and row.status != "unavailable":
                row.status = "unavailable"

        await self.db.flush()
        return await self.get_cached_models(provider_id)

    async def get_cached_models(self, provider_id: str) -> list[ModelRecord]:
        """Return the persisted catalog for a provider (no live call)."""
        await self._get_raw(provider_id)  # 404 if unknown
        result = await self.db.execute(
            select(ProviderModel)
            .where(ProviderModel.provider_id == provider_id)
            .order_by(ProviderModel.model_id)
        )
        return [self._record_to_schema(r) for r in result.scalars().all()]

    async def list_enabled_models_for_user(self) -> list[ModelRecord]:
        """All available+enabled models across all enabled providers."""
        result = await self.db.execute(
            select(ProviderModel)
            .join(LLMProvider, LLMProvider.id == ProviderModel.provider_id)
            .where(
                ProviderModel.status == "available",
                ProviderModel.enabled == True,      # noqa: E712
                LLMProvider.enabled == True,        # noqa: E712
            )
            .order_by(ProviderModel.provider_id, ProviderModel.model_id)
        )
        return [self._record_to_schema(r) for r in result.scalars().all()]

    async def set_model_enabled(
        self, provider_id: str, model_record_id: str, enabled: bool, user_id: str,
        client_ip: str | None = None,
    ) -> ModelRecord:
        """Enable/disable a discovered model (admin-only via router)."""
        result = await self.db.execute(
            select(ProviderModel).where(
                ProviderModel.id == model_record_id,
                ProviderModel.provider_id == provider_id,
            )
        )
        row = result.scalar_one_or_none()
        if not row:
            raise HTTPException(404, "Model not found for this provider")
        row.enabled = enabled
        await self.db.flush()

        audit = AuditService(self.db)
        await audit.log(
            "config", "provider.model.updated", "success",
            user_id=user_id,
            resource_type="llm_provider", resource_id=provider_id,
            metadata={"model": row.model_id, "enabled": enabled},
            ip_address=client_ip,
        )
        return self._record_to_schema(row)

    # ------------------------------------------------------------------
    # Internal helper — returns raw ORM object (with api_key for internal use)
    # ------------------------------------------------------------------
    async def _get_raw(self, provider_id: str) -> LLMProvider:
        result = await self.db.execute(
            select(LLMProvider).where(LLMProvider.id == provider_id)
        )
        p = result.scalar_one_or_none()
        if not p:
            raise HTTPException(404, f"Provider '{provider_id}' not found")
        return p

    async def get_raw_for_inference(self, provider_id: str) -> LLMProvider:
        """For internal use only — returns ORM object including api_key for building clients."""
        return await self._get_raw(provider_id)
