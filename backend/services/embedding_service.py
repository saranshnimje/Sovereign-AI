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
    "text-embedding-004": 768,
    "text-embedding-005": 768,
    "embedding-001": 768,
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

    async def _cloud_candidates(self, llm) -> list[tuple[BaseLLMProvider, str]]:
        """Resolve cloud provider client objects from the runtime wrapper or DB.

        Returns list of (provider_client, label) for providers that support
        embeddings. Each client has its own native embed() method that knows
        the correct API format (OpenAI-compatible, Gemini, Cohere, etc.).
        """
        candidates: list[tuple[BaseLLMProvider, str]] = []

        # Collect from the runtime failover wrapper (request-path providers)
        providers = getattr(llm, "providers", None)
        if providers:
            for client, _configured_model, label in providers:
                # Skip Ollama — it already failed in the native path
                from services.llm_client import OllamaProvider
                if isinstance(client, OllamaProvider):
                    continue
                candidates.append((client, str(label)))

        # Background ingestion receives the legacy Ollama client.
        # Resolve enabled cloud providers directly from the DB.
        try:
            from database import AsyncSessionLocal
            from models.provider import LLMProvider
            from sqlalchemy import select
            from services.llm_client import build_provider
            async with AsyncSessionLocal() as db:
                result = await db.execute(select(LLMProvider).where(LLMProvider.enabled == True))
                db_providers = list(result.scalars().all())
            seen_labels = {label for _, label in candidates}
            for provider in db_providers:
                if provider.provider_type in ("ollama", "ollama_compatible", "ollama_docker"):
                    continue
                try:
                    client = build_provider(
                        provider_type=provider.provider_type,
                        base_url=provider.base_url,
                        api_key=provider.api_key,
                        custom_headers=getattr(provider, "custom_headers", None),
                    )
                    label = str(provider.name)
                    if label not in seen_labels:
                        candidates.append((client, label))
                        seen_labels.add(label)
                except Exception as exc:
                    logger.warning("Skipping embedding provider %s: %s", provider.name, exc)
        except Exception as exc:
            logger.warning("Unable to load DB embedding providers: %s", exc)

        return candidates

    # Provider-specific embedding model fallbacks: when the KB's configured
    # model is not available on a cloud provider, try these in order.
    _CLOUD_MODEL_FALLBACKS: dict[str, list[str]] = {
        "openrouter": ["openai/text-embedding-3-small", "openai/text-embedding-ada-002"],
        "openai": ["text-embedding-3-small", "text-embedding-ada-002"],
        "openai_compatible": ["text-embedding-3-small"],
        "groq": ["text-embedding-3-small"],
        "together": ["togethercomputer/mpnet-base-v2"],
        "nvidia": ["NV-Embed-QA"],
        "mistral": ["mistral-embed"],
        "cohere": ["embed-english-v3.0"],
        "huggingface": ["sentence-transformers/all-MiniLM-L6-v2"],
        "gemini": ["text-embedding-004", "text-embedding-005"],
    }

    async def _cloud_embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Embed via cloud provider objects using their native embed() methods.

        Each provider (Gemini, Cohere, OpenAI-compatible, etc.) knows its own
        correct API endpoint and request format. This avoids constructing
        raw HTTP requests that only work for OpenAI-compatible providers.
        """
        candidates = await self._cloud_candidates(self.llm)
        if not candidates:
            raise ModelUnavailableError("No cloud embedding providers available")

        # Build model variants: original + provider-specific fallbacks
        all_errors: list[str] = []

        for provider_client, label in candidates:
            label_lower = label.lower()
            model_variants: list[str] = [model]
            for provider_key, fallbacks in self._CLOUD_MODEL_FALLBACKS.items():
                if provider_key in label_lower:
                    for fb in fallbacks:
                        if fb not in model_variants:
                            model_variants.append(fb)
                    break

            provider_errors: list[str] = []
            for try_model in model_variants:
                try:
                    resp = await provider_client.embed(model=try_model, texts=texts)
                    if resp.embeddings:
                        logger.info(
                            "Cloud embedding succeeded via %s model=%s dims=%d",
                            label, try_model, len(resp.embeddings[0]),
                        )
                        return resp.embeddings
                    provider_errors.append(f"{try_model}: returned no vectors")
                except Exception as exc:
                    provider_errors.append(f"{try_model}: {exc}")
                    continue

            all_errors.append(f"{label}: {'; '.join(provider_errors[-3:])}")

        raise ModelUnavailableError(
            "All cloud embedding providers failed. " + " | ".join(all_errors[-4:])
        )

    async def embed_query(self, query: str, model: str) -> list[float]:
        results = await self.embed_texts([query], model)
        return results[0] if results else []

    async def check_model_available(self, model: str) -> bool:
        try:
            result = await self.embed_texts(["test"], model)
            return len(result) > 0 and len(result[0]) > 0
        except Exception:
            return False
