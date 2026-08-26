"""Unit tests for EmbeddingService — Ollama client mocked."""
import pytest
from unittest.mock import AsyncMock, MagicMock
from services.embedding_service import EmbeddingService, get_expected_dimension
from services.llm_client import EmbeddingResponse, ModelUnavailableError


def _make_svc(mock_embed_fn=None):
    llm = MagicMock()
    llm.embed = AsyncMock(return_value=EmbeddingResponse(
        embeddings=[[0.1] * 768],
        model="nomic-embed-text",
        tokens=10,
    ))
    if mock_embed_fn:
        llm.embed = mock_embed_fn
    return EmbeddingService(llm)


@pytest.mark.asyncio
async def test_embed_single_text():
    svc = _make_svc()
    result = await svc.embed_texts(["hello world"], "nomic-embed-text")
    assert len(result) == 1
    assert len(result[0]) == 768


@pytest.mark.asyncio
async def test_embed_empty_list_returns_empty():
    svc = _make_svc()
    result = await svc.embed_texts([], "nomic-embed-text")
    assert result == []


@pytest.mark.asyncio
async def test_embed_query_returns_vector():
    svc = _make_svc()
    vec = await svc.embed_query("test query", "nomic-embed-text")
    assert len(vec) == 768


@pytest.mark.asyncio
async def test_embed_batch_calls_api_multiple_times():
    call_count = 0
    async def batched_embed(model, texts):
        nonlocal call_count
        call_count += 1
        return EmbeddingResponse(
            embeddings=[[0.1] * 768 for _ in texts],
            model=model,
        )

    from unittest.mock import AsyncMock
    llm = MagicMock()
    llm.embed = batched_embed
    svc = EmbeddingService(llm)

    # With batch_size=2 and 5 texts, should call API 3 times
    await svc.embed_texts(["t"] * 5, "nomic-embed-text", batch_size=2)
    assert call_count == 3


@pytest.mark.asyncio
async def test_model_unavailable_propagates():
    llm = MagicMock()
    llm.embed = AsyncMock(side_effect=ModelUnavailableError("offline"))
    svc = EmbeddingService(llm)
    with pytest.raises(ModelUnavailableError):
        await svc.embed_texts(["text"], "nomic-embed-text")


def test_get_expected_dimension_known_models():
    assert get_expected_dimension("nomic-embed-text") == 768
    assert get_expected_dimension("mxbai-embed-large") == 1024
    assert get_expected_dimension("all-minilm") == 384


def test_get_expected_dimension_unknown_defaults_768():
    assert get_expected_dimension("some-unknown-model-v1") == 768
