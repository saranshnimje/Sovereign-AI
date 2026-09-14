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
    "nomic-embed-text":  768,
    "mxbai-embed-large": 1024,
    "all-minilm":        384,
    "bge-large":         1024,
    "bge-m3":            1024,
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
    for key, dim in _KNOWN_DIMS.items():
        if key in model_name.lower():
            return dim
    return 768  # safe default


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
        """
        Embed a list of texts. Batches requests to avoid OOM.
        Returns list of float vectors in the same order as input texts.
        Raises ModelUnavailableError if provider is unreachable.
        """
        if not texts:
            return []

        bs = batch_size or self.settings.embedding_batch_size
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            try:
                # Try the standard Ollama embed method first
                resp = await self.llm.embed(model=model, texts=batch)
                all_embeddings.extend(resp.embeddings)
            except ModelUnavailableError:
                raise
            except AttributeError:
                # Provider doesn't have embed method — try OpenAI-compatible /v1/embeddings
                try:
                    embeddings = await self._cloud_embed(model, batch)
                    all_embeddings.extend(embeddings)
                except Exception as exc:
                    raise ModelUnavailableError(
                        f"Embedding request failed for model '{model}': {exc}"
                    ) from exc
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Embedding request failed for model '{model}': {exc}"
                ) from exc

        return all_embeddings

    async def _cloud_embed(self, model: str, texts: list[str]) -> list[list[float]]:
        """
        Fallback embedding via OpenAI-compatible /v1/embeddings endpoint.
        Used for cloud providers that support the OpenAI embeddings API.
        """
        import httpx

        base_url = getattr(self.llm, "base_url", None) or getattr(self.llm, "_base_url", None)
        api_key = getattr(self.llm, "_api_key", None)
        if not base_url:
            raise ModelUnavailableError("No base URL available for cloud embeddings")

        url = f"{base_url.rstrip('/')}/v1/embeddings"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json={"model": model, "input": texts}, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        embeddings = [item["embedding"] for item in data.get("data", [])]
        return embeddings

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
