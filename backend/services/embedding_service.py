"""
Embedding service — generates vectors via local Ollama /api/embed endpoint.
Batches inputs to avoid OOM on large documents.
"""
from __future__ import annotations
import logging

from config import get_settings
from services.llm_client import ModelUnavailableError, OllamaClient

logger = logging.getLogger(__name__)

# Known vector dimensions for common Ollama embedding models
_KNOWN_DIMS: dict[str, int] = {
    "nomic-embed-text":  768,
    "mxbai-embed-large": 1024,
    "all-minilm":        384,
    "bge-large":         1024,
    "bge-m3":            1024,
}


def get_expected_dimension(model_name: str) -> int:
    """Return the expected vector dimension for a model, defaulting to 768."""
    for key, dim in _KNOWN_DIMS.items():
        if key in model_name.lower():
            return dim
    return 768  # safe default for nomic-embed-text


class EmbeddingService:
    def __init__(self, llm: OllamaClient) -> None:
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
        Raises ModelUnavailableError if Ollama is unreachable.
        """
        if not texts:
            return []

        bs = batch_size or self.settings.embedding_batch_size
        all_embeddings: list[list[float]] = []

        for i in range(0, len(texts), bs):
            batch = texts[i : i + bs]
            try:
                resp = await self.llm.embed(model=model, texts=batch)
                all_embeddings.extend(resp.embeddings)
            except ModelUnavailableError:
                raise
            except Exception as exc:
                raise ModelUnavailableError(
                    f"Embedding request failed for model '{model}': {exc}"
                ) from exc

        return all_embeddings

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
