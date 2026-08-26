"""Unit tests for RAGService — external services fully mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from services.embedding_service import EmbeddingService
from services.llm_client import ChatResponse, EmbeddingResponse, ModelUnavailableError
from services.qdrant_service import QdrantService
from services.rag_service import RagService


def _make_rag(
    vectors=None,
    search_results=None,
    llm_answer="The answer is X.",
    embed_raises=None,
    llm_raises=None,
):
    # LLM mock
    llm = MagicMock()
    if llm_raises:
        llm.chat = AsyncMock(side_effect=llm_raises)
    else:
        llm.chat = AsyncMock(return_value=ChatResponse(
            content=llm_answer, model="llama3.2:3b"
        ))
    if embed_raises:
        llm.embed = AsyncMock(side_effect=embed_raises)
    else:
        llm.embed = AsyncMock(return_value=EmbeddingResponse(
            embeddings=[[0.1] * 768], model="nomic-embed-text"
        ))

    # Qdrant mock
    qdrant = MagicMock(spec=QdrantService)
    qdrant.search.return_value = search_results or []

    embedding_svc = EmbeddingService(llm)
    return RagService(llm=llm, embedding_svc=embedding_svc, qdrant_svc=qdrant)


@pytest.mark.asyncio
async def test_empty_qdrant_returns_low_confidence():
    svc = _make_rag(search_results=[])
    result = await svc.query("kb1", "nomic-embed-text", "llama3.2:3b", "test?")
    assert result.low_confidence is True
    assert result.answer is None
    assert result.sources == []


@pytest.mark.asyncio
async def test_successful_rag_query():
    results = [{
        "id": "c1", "score": 0.88,
        "doc_id": "d1", "filename": "doc.pdf",
        "page_number": 2, "content": "Relevant text here.",
    }]
    svc = _make_rag(search_results=results, llm_answer="Based on doc.pdf: The answer is X.")
    result = await svc.query(
        "kb1", "nomic-embed-text", "llama3.2:3b", "What is X?",
        generate_answer=True,
    )
    assert result.answer is not None
    assert len(result.sources) == 1
    assert result.sources[0].filename == "doc.pdf"
    assert result.sources[0].page_number == 2
    assert result.sources[0].score == 0.88
    assert result.low_confidence is False


@pytest.mark.asyncio
async def test_generate_answer_false_skips_llm():
    results = [{"id": "c1", "score": 0.9, "doc_id": "d1", "filename": "f.pdf",
                "page_number": None, "content": "text"}]
    svc = _make_rag(search_results=results)
    result = await svc.query(
        "kb1", "nomic-embed-text", "llama3.2:3b", "query?",
        generate_answer=False,
    )
    assert result.answer is None
    assert result.generation_ms is None
    assert len(result.sources) == 1


@pytest.mark.asyncio
async def test_embedding_unavailable_returns_error():
    svc = _make_rag(embed_raises=ModelUnavailableError("no embedding model"))
    result = await svc.query("kb1", "nomic-embed-text", "llama3.2:3b", "test?")
    assert result.error is not None
    assert "unavailable" in result.error.lower() or "embedding" in result.error.lower()


@pytest.mark.asyncio
async def test_llm_unavailable_returns_sources_without_answer():
    results = [{"id": "c1", "score": 0.85, "doc_id": "d1", "filename": "f.txt",
                "page_number": None, "content": "some text"}]
    svc = _make_rag(
        search_results=results,
        llm_raises=ModelUnavailableError("no llm"),
    )
    result = await svc.query(
        "kb1", "nomic-embed-text", "llama3.2:3b", "test?",
        generate_answer=True,
    )
    # Sources should still be present even though generation failed
    assert len(result.sources) == 1
    assert result.answer is None


@pytest.mark.asyncio
async def test_source_has_required_citation_fields():
    results = [{
        "id": "chunk-uuid", "score": 0.77,
        "doc_id": "doc-uuid", "filename": "report.pdf",
        "page_number": 5, "content": "Cited text.",
    }]
    svc = _make_rag(search_results=results)
    result = await svc.query(
        "kb1", "nomic-embed-text", "llama3.2:3b", "q?",
        generate_answer=False,
    )
    src = result.sources[0]
    assert src.chunk_id == "chunk-uuid"
    assert src.doc_id == "doc-uuid"
    assert src.filename == "report.pdf"
    assert src.page_number == 5
