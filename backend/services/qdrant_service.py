"""
Qdrant vector database service.
Wraps the qdrant-client to provide collection management, upsert, search, and delete.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any

from config import get_settings

logger = logging.getLogger(__name__)


class QdrantError(Exception):
    pass


def _collection_name(kb_id: str) -> str:
    """Derive a safe Qdrant collection name from a knowledge-base UUID."""
    # Use only the UUID with kb_ prefix — never accept raw user input as collection name
    safe = kb_id.replace("-", "_")
    return f"kb_{safe}"


class QdrantService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._client = None

    def _get_client(self):
        if self._client is None:
            from qdrant_client import QdrantClient  # type: ignore
            self._client = QdrantClient(url=self.settings.qdrant_url, timeout=10)
        return self._client

    # ------------------------------------------------------------------
    # Collection management
    # ------------------------------------------------------------------
    def create_collection(self, kb_id: str, vector_size: int) -> str:
        """
        Create a Qdrant collection for this knowledge base.
        Returns the collection name.
        Idempotent — does not raise if collection already exists.
        """
        from qdrant_client.models import Distance, VectorParams  # type: ignore

        cname = _collection_name(kb_id)
        client = self._get_client()
        try:
            existing = [c.name for c in client.get_collections().collections]
            if cname not in existing:
                client.create_collection(
                    collection_name=cname,
                    vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
                )
                logger.info("Created Qdrant collection: %s (dim=%d)", cname, vector_size)
            return cname
        except Exception as exc:
            raise QdrantError(f"Failed to create collection '{cname}': {exc}") from exc

    def delete_collection(self, kb_id: str) -> None:
        """Delete the Qdrant collection for a knowledge base."""
        cname = _collection_name(kb_id)
        try:
            client = self._get_client()
            client.delete_collection(cname)
            logger.info("Deleted Qdrant collection: %s", cname)
        except Exception as exc:
            logger.warning("Could not delete collection '%s': %s", cname, exc)

    def collection_exists(self, kb_id: str) -> bool:
        try:
            cname = _collection_name(kb_id)
            existing = [c.name for c in self._get_client().get_collections().collections]
            return cname in existing
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Vector operations
    # ------------------------------------------------------------------
    def upsert_vectors(
        self,
        kb_id: str,
        vectors: list[list[float]],
        payloads: list[dict[str, Any]],
        ids: list[str] | None = None,
    ) -> None:
        """
        Insert or update vectors with payload.
        ids: list of stable UUID strings (one per vector).
             If None, UUIDs are generated automatically.
        """
        from qdrant_client.models import PointStruct  # type: ignore

        cname = _collection_name(kb_id)
        if ids is None:
            ids = [str(uuid.uuid4()) for _ in vectors]

        points = [
            PointStruct(id=str(pid), vector=vec, payload=pay)
            for pid, vec, pay in zip(ids, vectors, payloads)
        ]

        try:
            self._get_client().upsert(collection_name=cname, points=points)
        except Exception as exc:
            raise QdrantError(f"Upsert failed for collection '{cname}': {exc}") from exc

    def delete_document_vectors(self, kb_id: str, doc_id: str) -> None:
        """Delete all vectors whose payload.doc_id == doc_id."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue  # type: ignore

        cname = _collection_name(kb_id)
        try:
            self._get_client().delete(
                collection_name=cname,
                points_selector=Filter(
                    must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                ),
            )
        except Exception as exc:
            logger.warning(
                "Could not delete vectors for doc '%s' in '%s': %s", doc_id, cname, exc
            )

    def search(
        self,
        kb_id: str,
        query_vector: list[float],
        top_k: int = 5,
        score_threshold: float = 0.0,
    ) -> list[dict[str, Any]]:
        """
        Semantic search. Returns list of dicts with 'id', 'score', and payload fields.
        """
        cname = _collection_name(kb_id)
        try:
            results = self._get_client().search(
                collection_name=cname,
                query_vector=query_vector,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )
            return [
                {"id": str(r.id), "score": r.score, **(r.payload or {})}
                for r in results
            ]
        except Exception as exc:
            raise QdrantError(f"Search failed in '{cname}': {exc}") from exc

    def health_check(self) -> bool:
        """Return True if Qdrant is reachable."""
        try:
            self._get_client().get_collections()
            return True
        except Exception:
            return False
