"""Integration tests for Knowledge Base and Document API endpoints."""
import io
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient


# ---- Knowledge Base CRUD ----

@pytest.mark.asyncio
async def test_create_knowledge_base(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_test"):
        resp = await auth_client.post("/api/v1/knowledge-bases/", json={
            "name": "Test KB",
            "description": "A test knowledge base",
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Test KB"
    assert data["doc_count"] == 0
    assert "id" in data


@pytest.mark.asyncio
async def test_list_knowledge_bases(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        await auth_client.post("/api/v1/knowledge-bases/", json={"name": "KB-List-Test"})

    resp = await auth_client.get("/api/v1/knowledge-bases/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
    names = [kb["name"] for kb in resp.json()]
    assert "KB-List-Test" in names


@pytest.mark.asyncio
async def test_get_knowledge_base(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        create = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "KBGet"})
    kb_id = create.json()["id"]

    resp = await auth_client.get(f"/api/v1/knowledge-bases/{kb_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == kb_id


@pytest.mark.asyncio
async def test_get_nonexistent_kb_returns_404(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/knowledge-bases/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_kb_name_required(auth_client: AsyncClient):
    resp = await auth_client.post("/api/v1/knowledge-bases/", json={"name": ""})
    assert resp.status_code in (400, 422)


@pytest.mark.asyncio
async def test_create_kb_requires_analyst_role(client: AsyncClient):
    # First user (admin) is already created by auth_client fixture if it ran first,
    # but here we use the bare `client` fixture (no prior users in this test's DB).
    # Register the first user → gets admin role
    await client.post("/api/v1/auth/register", json={
        "email": "admin2@test.com", "username": "adminuser2", "password": "StrongPass123!"
    })
    # Register a second user → gets viewer role
    await client.post("/api/v1/auth/register", json={
        "email": "view@test.com", "username": "viewonly", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "view@test.com", "password": "StrongPass123!"
    })
    viewer_token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {viewer_token}"

    resp = await client.post("/api/v1/knowledge-bases/", json={"name": "Forbidden KB"})
    assert resp.status_code == 403


# ---- Document Upload ----

@pytest.mark.asyncio
async def test_upload_valid_txt_document(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "DocKB"})
    kb_id = kb.json()["id"]

    txt_content = b"This is a valid test document for upload."
    resp = await auth_client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.txt", txt_content, "text/plain")},
        data={"kb_id": kb_id, "run_ocr": "false"},
    )
    assert resp.status_code == 202
    doc = resp.json()
    assert doc["status"] == "pending"
    assert doc["original_name"].endswith(".txt")
    assert doc["kb_id"] == kb_id


@pytest.mark.asyncio
async def test_upload_invalid_extension_rejected(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "DocKB2"})
    kb_id = kb.json()["id"]

    resp = await auth_client.post(
        "/api/v1/documents/upload",
        files={"file": ("malware.exe", b"MZ\x90\x00", "application/octet-stream")},
        data={"kb_id": kb_id},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_empty_file_rejected(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "DocKB3"})
    kb_id = kb.json()["id"]

    resp = await auth_client.post(
        "/api/v1/documents/upload",
        files={"file": ("empty.txt", b"", "text/plain")},
        data={"kb_id": kb_id},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_upload_nonexistent_kb_rejected(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/v1/documents/upload",
        files={"file": ("test.txt", b"content here", "text/plain")},
        data={"kb_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_documents_for_kb(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "DocListKB"})
    kb_id = kb.json()["id"]

    await auth_client.post(
        "/api/v1/documents/upload",
        files={"file": ("a.txt", b"content A", "text/plain")},
        data={"kb_id": kb_id, "run_ocr": "false"},
    )

    resp = await auth_client.get(f"/api/v1/documents/?kb_id={kb_id}")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


@pytest.mark.asyncio
async def test_get_document_returns_status(auth_client: AsyncClient):
    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "StatusKB"})
    kb_id = kb.json()["id"]

    upload = await auth_client.post(
        "/api/v1/documents/upload",
        files={"file": ("doc.txt", b"test content here", "text/plain")},
        data={"kb_id": kb_id, "run_ocr": "false"},
    )
    doc_id = upload.json()["id"]

    resp = await auth_client.get(f"/api/v1/documents/{doc_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert "processing_steps" in data
    assert isinstance(data["processing_steps"], list)


# ---- RAG Query ----

@pytest.mark.asyncio
async def test_kb_query_with_mocked_rag(auth_client: AsyncClient):
    """Query endpoint returns proper structure even when Qdrant has no results."""
    from unittest.mock import AsyncMock, patch

    with patch("services.qdrant_service.QdrantService.create_collection", return_value="kb_x"):
        kb = await auth_client.post("/api/v1/knowledge-bases/", json={"name": "QueryKB"})
    kb_id = kb.json()["id"]

    # Patch embed_query and search so no real Ollama/Qdrant needed
    with patch.object(
        __import__("services.embedding_service", fromlist=["EmbeddingService"]).EmbeddingService,
        "embed_query",
        new=AsyncMock(return_value=[0.1] * 768),
    ), patch("services.qdrant_service.QdrantService.search", return_value=[]):
        resp = await auth_client.post(
            f"/api/v1/knowledge-bases/{kb_id}/query",
            json={"query": "What is this about?", "generate_answer": False},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "answer" in data
    assert "sources" in data
    assert isinstance(data["sources"], list)
    assert data["low_confidence"] is True
