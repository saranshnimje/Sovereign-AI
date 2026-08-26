"""Unit tests for QdrantService — qdrant-client mocked."""
import pytest
from unittest.mock import MagicMock, patch


def _make_mock_client(collections=None):
    """Build a mock QdrantClient."""
    mock_client = MagicMock()
    # get_collections returns an object whose .collections is a list
    # Each item needs a .name string attribute (not a MagicMock with name= kwarg)
    col_items = []
    for cname in (collections or []):
        item = MagicMock(spec=[])  # blank spec so .name works as attribute
        item.name = cname
        col_items.append(item)
    col_mock = MagicMock()
    col_mock.collections = col_items
    mock_client.get_collections.return_value = col_mock
    mock_client.create_collection.return_value = None
    mock_client.delete_collection.return_value = None
    mock_client.upsert.return_value = None
    mock_client.search.return_value = []
    return mock_client


def test_collection_name_derivation():
    from services.qdrant_service import _collection_name
    cname = _collection_name("abc-123")
    assert cname == "kb_abc_123"
    assert "-" not in cname


def test_create_collection_calls_client():
    from services.qdrant_service import QdrantService
    svc = QdrantService()
    mock_client = _make_mock_client()
    svc._client = mock_client

    cname = svc.create_collection("test-kb-id", vector_size=768)
    assert cname.startswith("kb_")
    mock_client.create_collection.assert_called_once()


def test_create_collection_idempotent():
    from services.qdrant_service import QdrantService, _collection_name
    svc = QdrantService()
    kb_id = "idempotent-kb"
    # Pre-populate collection as already existing
    mock_client = _make_mock_client(collections=[_collection_name(kb_id)])
    svc._client = mock_client

    svc.create_collection(kb_id, 768)
    # Should NOT call create_collection since it already exists
    mock_client.create_collection.assert_not_called()


def test_upsert_vectors():
    from services.qdrant_service import QdrantService
    svc = QdrantService()
    svc._client = _make_mock_client()

    svc.upsert_vectors(
        kb_id="kb1",
        vectors=[[0.1] * 768, [0.2] * 768],
        payloads=[{"content": "a"}, {"content": "b"}],
    )
    svc._client.upsert.assert_called_once()


def test_search_returns_formatted_results():
    from services.qdrant_service import QdrantService
    svc = QdrantService()
    mock_client = _make_mock_client()

    # Set up search return value
    hit = MagicMock()
    hit.id = "point-1"
    hit.score = 0.91
    hit.payload = {"doc_id": "d1", "content": "hello", "filename": "test.pdf"}
    mock_client.search.return_value = [hit]
    svc._client = mock_client

    results = svc.search("kb1", query_vector=[0.1] * 768, top_k=3)
    assert len(results) == 1
    assert results[0]["score"] == 0.91
    assert results[0]["doc_id"] == "d1"


def test_search_qdrant_error_raises():
    from services.qdrant_service import QdrantService, QdrantError
    svc = QdrantService()
    mock_client = _make_mock_client()
    mock_client.search.side_effect = Exception("connection refused")
    svc._client = mock_client

    with pytest.raises(QdrantError):
        svc.search("kb1", query_vector=[0.1] * 768)


def test_delete_document_vectors():
    from services.qdrant_service import QdrantService
    svc = QdrantService()
    mock_client = _make_mock_client()
    svc._client = mock_client

    svc.delete_document_vectors("kb1", "doc-id-123")
    mock_client.delete.assert_called_once()


def test_health_check_true():
    from services.qdrant_service import QdrantService
    svc = QdrantService()
    svc._client = _make_mock_client()
    assert svc.health_check() is True


def test_health_check_false_on_exception():
    from services.qdrant_service import QdrantService
    svc = QdrantService()
    mock_client = _make_mock_client()
    mock_client.get_collections.side_effect = Exception("offline")
    svc._client = mock_client
    assert svc.health_check() is False
