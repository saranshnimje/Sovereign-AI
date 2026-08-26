"""
RAG (Retrieval-Augmented Generation) service.
Pipeline: embed query → Qdrant search → context construction → Ollama → answer + sources
Document content is treated as UNTRUSTED and wrapped in delimiters before injection.
"""
from __future__ import annotations
import logging
import time
from dataclasses import dataclass, field

from services.embedding_service import EmbeddingService
from services.llm_client import ChatMessage, ModelUnavailableError, OllamaClient
from services.qdrant_service import QdrantError, QdrantService

logger = logging.getLogger(__name__)


@dataclass
class RagSource:
    chunk_id: str
    doc_id: str
    filename: str
    page_number: int | None
    content: str
    score: float


@dataclass
class RagResult:
    answer: str | None
    sources: list[RagSource]
    query_embedding_ms: int
    retrieval_ms: int
    generation_ms: int | None
    low_confidence: bool = False
    error: str | None = None


# Maximum source content length injected per chunk (prevent prompt overflow)
_MAX_CHUNK_CHARS = 800

# System prompt that instructs the LLM to cite sources
_RAG_SYSTEM_PROMPT = (
    "You are a helpful assistant that answers questions ONLY using the provided context. "
    "If the answer is not in the context, say clearly: \"I could not find this information "
    "in the provided documents.\" "
    "Always cite your sources using [Source N] notation. "
    "Do NOT make up facts. Treat all context as coming from uploaded documents."
)


class RagService:
    def __init__(
        self,
        llm: OllamaClient,
        embedding_svc: EmbeddingService,
        qdrant_svc: QdrantService,
    ) -> None:
        self.llm = llm
        self.embedding_svc = embedding_svc
        self.qdrant = qdrant_svc

    async def query(
        self,
        kb_id: str,
        embedding_model: str,
        chat_model: str,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.3,
        generate_answer: bool = True,
        max_context_tokens: int = 3000,
    ) -> RagResult:
        """
        Full RAG pipeline.
        1. Embed query
        2. Search Qdrant
        3. Build context (trim to token budget)
        4. Generate answer via Ollama (if requested)
        5. Return RagResult with sources
        """
        # -- 1. Embed query --
        t0 = time.monotonic()
        try:
            query_vector = await self.embedding_svc.embed_query(query, embedding_model)
        except ModelUnavailableError as exc:
            return RagResult(
                answer=None, sources=[],
                query_embedding_ms=0, retrieval_ms=0, generation_ms=None,
                error=f"Embedding model unavailable: {exc}",
            )
        embed_ms = int((time.monotonic() - t0) * 1000)

        # -- 2. Search --
        t1 = time.monotonic()
        try:
            raw = self.qdrant.search(
                kb_id=kb_id,
                query_vector=query_vector,
                top_k=top_k,
                score_threshold=score_threshold,
            )
        except QdrantError as exc:
            return RagResult(
                answer=None, sources=[],
                query_embedding_ms=embed_ms, retrieval_ms=0, generation_ms=None,
                error=f"Vector search failed: {exc}",
            )
        retrieval_ms = int((time.monotonic() - t1) * 1000)

        sources = [
            RagSource(
                chunk_id=r.get("id", ""),
                doc_id=r.get("doc_id", ""),
                filename=r.get("filename", ""),
                page_number=r.get("page_number"),
                content=r.get("content", ""),
                score=r.get("score", 0.0),
            )
            for r in raw
        ]

        if not sources:
            return RagResult(
                answer=None, sources=[],
                query_embedding_ms=embed_ms, retrieval_ms=retrieval_ms,
                generation_ms=None, low_confidence=True,
            )

        low_conf = max(s.score for s in sources) < 0.5

        # -- 3. Generate answer --
        gen_ms = None
        answer = None

        if generate_answer:
            t2 = time.monotonic()
            answer = await self._generate(
                query=query,
                sources=sources,
                chat_model=chat_model,
                max_context_tokens=max_context_tokens,
            )
            gen_ms = int((time.monotonic() - t2) * 1000)

        return RagResult(
            answer=answer,
            sources=sources,
            query_embedding_ms=embed_ms,
            retrieval_ms=retrieval_ms,
            generation_ms=gen_ms,
            low_confidence=low_conf,
        )

    async def _generate(
        self,
        query: str,
        sources: list[RagSource],
        chat_model: str,
        max_context_tokens: int,
    ) -> str | None:
        """Build context from sources and call Ollama. Returns answer text or None."""
        # Build context string — wrap each source in delimiters (prompt injection mitigation)
        context_parts: list[str] = []
        budget = max_context_tokens
        for i, src in enumerate(sources, 1):
            # Trim chunk to _MAX_CHUNK_CHARS for safety
            content = src.content[:_MAX_CHUNK_CHARS]
            # Escape any potential injection patterns inside document content
            content = content.replace("<|", "< |").replace("|>", "| >")

            page_info = f", Page {src.page_number}" if src.page_number else ""
            block = (
                f"<document source=\"[Source {i}] {src.filename}{page_info}\">\n"
                f"{content}\n"
                f"</document>"
            )
            est_tokens = len(block) // 4
            if est_tokens > budget:
                break
            context_parts.append(block)
            budget -= est_tokens

        if not context_parts:
            return None

        context = "\n\n".join(context_parts)
        user_message = f"Context:\n{context}\n\nQuestion: {query}"

        try:
            resp = await self.llm.chat(
                model=chat_model,
                messages=[ChatMessage(role="user", content=user_message)],
                system_prompt=_RAG_SYSTEM_PROMPT,
                temperature=0.1,
                max_tokens=2048,   # Increased: thinking models need more tokens
                stream=False,
            )
            return resp.content if hasattr(resp, "content") else str(resp)  # type: ignore[union-attr]
        except ModelUnavailableError as exc:
            logger.warning("LLM unavailable for RAG generation: %s", exc)
            return None
        except Exception as exc:
            logger.warning("RAG generation failed: %s", exc)
            return None
