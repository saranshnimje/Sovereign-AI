"""
Integration tests for the document ingestion lifecycle (P0.1) and
embedding version stamping / dimension-drift guard (P0.7/P0.8).

Background ingestion tasks run inline under httpx ASGITransport, so after
the upload POST returns, the terminal status is already persisted.
"""
import io
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

DIM = 768


def _fake_vectors(n: int) -> list[list[float]]:
    return [[0.1] * DIM for _ in range(n)]


async def _make_kb(client: AsyncClient, name: str = "IngestKB") -> str:
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        resp = await client.post("/api/v1/knowledge-bases/", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


# ----------------------------------------------------------------------
# P0.1 — lifecycle reaches a persisted terminal state
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_upload_reaches_indexed_with_real_pipeline(auth_client: AsyncClient):
    """Upload → background pipeline runs → status=indexed persisted (no fake success)."""
    kb_id = await _make_kb(auth_client)

    with patch(
        "services.document_service.EmbeddingService.embed_texts",
        new=AsyncMock(return_value=_fake_vectors(2)),
    ), patch(
        "services.qdrant_service.QdrantService.create_collection", return_value="kb_x"
    ), patch(
        "services.qdrant_service.QdrantService.upsert_vectors"
    ) as upsert_mock:
        resp = await auth_client.post(
            "/api/v1/documents/upload",
            files={"file": ("manual.txt", b"Bearing maintenance procedures. " * 50, "text/plain")},
            data={"kb_id": kb_id, "run_ocr": "false"},
        )
        assert resp.status_code == 202
        doc_id = resp.json()["id"]

        # Background task executed during the request cycle (ASGITransport)
        status_resp = await auth_client.get(f"/api/v1/documents/{doc_id}")
        assert status_resp.status_code == 200
        body = status_resp.json()
        assert body["status"] == "indexed", body
        assert body["chunk_count"] >= 1
        assert body["error_message"] is None

        # P0.7: every indexed vector payload carries embedding stamps
        assert upsert_mock.await_count if hasattr(upsert_mock, "await_count") else upsert_mock.called
        payloads = upsert_mock.call_args.kwargs["payloads"]
        assert len(payloads) >= 1
        for p in payloads:
            assert p["embed_model"]  # stamped model id
            assert p["embed_dim"] == DIM
            assert p["embed_version"]


@pytest.mark.asyncio
async def test_failed_ingestion_persists_error_state(auth_client: AsyncClient):
    """Pipeline failure ⇒ status=failed + real error message persisted. Never READY."""
    kb_id = await _make_kb(auth_client)

    import services.document_service as ds_mod

    with patch.object(ds_mod, "extract_text", new=AsyncMock(side_effect=RuntimeError("corrupt pdf"))):
        resp = await auth_client.post(
            "/api/v1/documents/upload",
            files={"file": ("bad.txt", b"whatever content", "text/plain")},
            data={"kb_id": kb_id, "run_ocr": "false"},
        )
        assert resp.status_code == 202
        doc_id = resp.json()["id"]

    body = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert body["status"] == "failed"
    assert "corrupt pdf" in (body["error_message"] or "")
    failed_steps = [s for s in body["processing_steps"] if s["status"] == "failed"]
    assert len(failed_steps) == 1


@pytest.mark.asyncio
async def test_retry_failed_document_succeeds(auth_client: AsyncClient):
    """Explicit retry re-runs the canonical pipeline and can reach indexed."""
    kb_id = await _make_kb(auth_client)
    import services.document_service as ds_mod

    # First attempt fails
    with patch.object(ds_mod, "extract_text", new=AsyncMock(side_effect=RuntimeError("boom"))):
        resp = await auth_client.post(
            "/api/v1/documents/upload",
            files={"file": ("retry.txt", b"some content " * 20, "text/plain")},
            data={"kb_id": kb_id, "run_ocr": "false"},
        )
        doc_id = resp.json()["id"]
        assert (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()["status"] == "failed"

    # Retry succeeds
    with patch(
        "services.document_service.EmbeddingService.embed_texts",
        new=AsyncMock(return_value=_fake_vectors(2)),
    ), patch(
        "services.qdrant_service.QdrantService.create_collection", return_value="kb_x"
    ), patch("services.qdrant_service.QdrantService.upsert_vectors"):
        retry = await auth_client.post(f"/api/v1/documents/{doc_id}/retry")
        assert retry.status_code == 200
        final = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
        assert final["status"] == "indexed"
        assert final["error_message"] is None


@pytest.mark.asyncio
async def test_retry_non_failed_document_conflict(auth_client: AsyncClient):
    """Retry only applies to failed documents."""
    kb_id = await _make_kb(auth_client)
    with patch(
        "services.document_service.EmbeddingService.embed_texts",
        new=AsyncMock(return_value=_fake_vectors(1)),
    ), patch(
        "services.qdrant_service.QdrantService.create_collection", return_value="kb_x"
    ), patch("services.qdrant_service.QdrantService.upsert_vectors"):
        resp = await auth_client.post(
            "/api/v1/documents/upload",
            files={"file": ("ok.txt", b"content " * 10, "text/plain")},
            data={"kb_id": kb_id, "run_ocr": "false"},
        )
        doc_id = resp.json()["id"]
    r = await auth_client.post(f"/api/v1/documents/{doc_id}/retry")
    assert r.status_code == 409


# ----------------------------------------------------------------------
# P0.8 — dimension-drift guard
# ----------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dimension_mismatch_fails_clearly_and_indexes_nothing(auth_client: AsyncClient):
    """Wrong-dimension vectors must FAIL the job — never truncate/pad/upsert."""
    kb_id = await _make_kb(auth_client)

    with patch(
        "services.document_service.EmbeddingService.embed_texts",
        new=AsyncMock(return_value=[[0.5] * 384]),  # wrong dim vs expected 768
    ), patch(
        "services.qdrant_service.QdrantService.upsert_vectors"
    ) as upsert_mock:
        resp = await auth_client.post(
            "/api/v1/documents/upload",
            files={"file": ("drift.txt", b"dimension drift test " * 30, "text/plain")},
            data={"kb_id": kb_id, "run_ocr": "false"},
        )
        doc_id = resp.json()["id"]

    body = (await auth_client.get(f"/api/v1/documents/{doc_id}")).json()
    assert body["status"] == "failed"
    assert "dimension" in (body["error_message"] or "").lower()
    assert not upsert_mock.called  # nothing invalid reached the vector store
