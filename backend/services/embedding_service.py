"""
Embedding service — generates vectors via local Ollama or cloud providers.
Batches inputs to avoid OOM on large documents.
Falls back to OpenAI-compatible embedding endpoints for cloud providers.
"""
from __future__ import annotations
import logging

from config import get_settings
from services.llm_client import ModelUnavailableError, OllamaClient, BaseLLMProvider

logger = logging.getLogger(__name__)

_KNOWN_DIMS: dict[str, int] = {
    "nomic-embed-text": 768,
    "mxbai-embed-large": 1024,
    "all-minilm": 384,
    "bge-large": 1024,
    "bge-m3": 1024,
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "embed-english-v3.0": 1024,
    "embed-english-light-v3.0": 384,
    "embed-multilingual-v3.0": 1024,
    "Cohere/embed-english-v3.0": 1024,
}


def get_expected_dimension(model_name: str) -> int:
    """Return the expected vector dimension for a model, defaulting to 768."""
    lowered = (model_name or "").lower()
    for key, dim in _KNOWN_DIMS.items():
        if key.lower() in lowered:
            return dim
    return 768


class EmbeddingService:
    def __init__(self, llm: BaseLLMProvider | OllamaClient) -> None:
        self.llm = llm
        self.settings = get_settings()

    async def embed_texts(
        self,
        texts: list[str],
        model: str,
        batch_size: int | None = None,
    ) -> list[list[float]]:
        if not texts:
            return []

        bs = batch_size or self.settings.embedding_batch_size
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            try:
                resp = await self.llm.embed(model=model, texts=batch)
                all_embeddings.extend(resp.embeddings)
                continue
            except Exception as native_exc:
                logger.debug("Native embedding path failed; trying cloud fallback: %s", native_exc)

            try:
                embeddings = await self._cloud_embed(model, batch)
                all_embeddings.extend(embeddings)
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Embedding request failed for model '{model}': {exc}"
                ) from exc

        return all_embeddings

    async def _cloud_candidates(self, llm) -> list[tuple[str, str | None, str]]:
        """Resolve cloud provider URLs from the runtime wrapper or DB configuration."""
        candidates: list[tuple[str, str | None, str]] = []
        providers = getattr(llm, "providers", None)
        if providers:
            for client, _configured_model, label in providers:
                base_url = getattr(client, "base_url", None) or getattr(client, "_base_url", None)
                api_key = getattr(client, "_api_key", None) or getattr(client, "api_key", None)
                if base_url:
                    candidates.append((str(base_url), api_key, str(label)))

        base_url = getattr(llm, "base_url", None) or getattr(llm, "_base_url", None)
        api_key = getattr(llm, "_api_key", None) or getattr(llm, "api_key", None)
        if base_url:
            candidate = (str(base_url), api_key, llm.__class__.__name__)
            if candidate not in candidates:
                candidates.append(candidate)

        # Background ingestion may receive the legacy local Ollama client.
        # Resolve enabled cloud providers directly so KB ingestion does not
        # depend on whether the request path constructed a provider wrapper.
        try:
            from database import AsyncSessionLocal
            from models.provider import LLMProvider
            from sqlalchemy import select
            from services.llm_client import build_provider
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(LLMProvider).where(LLMProvider.enabled == True))
                db_providers = list(result.scalars().all())
            for provider in db_providers:
                try:
                    client = build_provider(
                        provider_type=provider.provider_type,
                        base_url=provider.base_url,
                        api_key=provider.api_key,
                        custom_headers=getattr(provider, "custom_headers", None),
                    )
                    provider_base = getattr(client, "base_url", None) or getattr(client, "_base_url", None)
                    provider_key = getattr(client, "_api_key", None) or getattr(client, "api_key", None)
                    if provider_base:
                        candidate = (str(provider_base), provider_key, str(provider.name))
                        if candidate not in candidates:
                            candidates.append(candidate)
                except Exception as exc:
                    logger.warning("Skipping embedding provider %s: %s", provider.name, exc)
        except Exception as exc:
            logger.warning("Unable to load DB embedding providers: %s", exc)

        return candidates

    async def _cloud_embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Use OpenAI-compatible embeddings for configured cloud providers."""
        import httpx

        candidates = await self._cloud_candidates(self.llm)
        if not candidates:
            raise ModelUnavailableError("No provider base URL available for cloud embeddings")

        errors: list[str] = []
        for base_url, api_key, label in candidates:
            base = base_url.rstrip("/")
            url = f"{base}/embeddings" if base.endswith("/v1") else f"{base}/v1/embeddings"
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            request_model = model
            if label.lower().find("openrouter") >= 0 and model.startswith("text-embedding-"):
                request_model = f"openai/{model}"

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(
                        url,
                        json={"model": request_model, "input": texts},
                        headers=headers,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                embeddings = [item["embedding"] for item in data.get("data", [])]
                if not embeddings:
                    raise ModelUnavailableError("Embedding provider returned no vectors")
                return embeddings
            except Exception as exc:
                errors.append(f"{label}: {exc}")
                continue

        raise ModelUnavailableError("All cloud embedding providers failed. " + " | ".join(errors[-4:]))

    async def embed_query(self, query: str, model: str) -> list[float]:
        results = await self.embed_texts([query], model)
        return results[0] if results else []

    async def check_model_available(self, model: str) -> bool:
        try:
            result = await self.embed_texts(["test"], model)
            return len(result) > 0 and len(result[0]) > 0
        except Exception:
            return False
