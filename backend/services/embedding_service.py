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

# Known vector dimensions for common embedding models
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
        """Embed texts, preferring native provider embeddings and then cloud fallback."""
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
                # Cloud providers commonly inherit BaseLLMProvider.embed(), which
                # deliberately raises ModelUnavailableError. Do not stop ingestion
                # there; try the provider's OpenAI-compatible /embeddings endpoint.
                logger.debug("Native embedding path failed; trying cloud fallback: %s", native_exc)

            try:
                embeddings = await self._cloud_embed(model, batch)
                all_embeddings.extend(embeddings)
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Embedding request failed for model '{model}': {exc}"
                ) from exc

        return all_embeddings

    @staticmethod
    def _cloud_candidates(llm) -> list[tuple[str, str | None, str]]:
        """Return (base_url, api_key, label) candidates from the resolved LLM."""
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
        return candidates

    async def _cloud_embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """Use OpenAI-compatible embeddings for configured cloud providers."""
        import httpx

        candidates = self._cloud_candidates(self.llm)
        if not candidates:
            raise ModelUnavailableError("No provider base URL available for cloud embeddings")

        errors: list[str] = []
        for base_url, api_key, label in candidates:
            base = base_url.rstrip("/")
            # OpenRouter/OpenAI-compatible providers commonly already include /v1.
            url = f"{base}/embeddings" if base.endswith("/v1") else f"{base}/v1/embeddings"
            headers = {"Content-Type": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

            # OpenRouter exposes OpenAI embedding models with the provider prefix.
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
        """Embed a single query string."""
        results = await self.embed_texts([query], model)
        return results[0] if results else []

    async def check_model_available(self, model: str) -> bool:
        """Return True if the embedding model responds correctly."""
        try:
            result = await self.embed_texts(["test"], model)
            return len(result) > 0 and len(result[0]) > 0
        except Exception:
            return False
