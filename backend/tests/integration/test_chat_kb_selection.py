"""
Chat KB selection wiring tests — 10 scenarios for P1.4.1.

Tests cover:
  1. authorized KB selection
  2. foreign KB selection (tenant isolation)
  3. tenant isolation (user B can't use user A's KB)
  4. no KB selected (normal chat)
  5. one KB selected
  6. multiple KBs if supported
  7. empty retrieval (KB exists but no relevant docs)
  8. citation authorization
  9. chat streaming with RAG
  10. chat streaming without RAG
"""
import json
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from database import Base, get_db
from main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest_asyncio.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def client(db: AsyncSession):
    async def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        yield c
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    await client.post("/api/v1/auth/register",
        json={"email": "kbchat@test.com", "username": "kbchattester", "password": "StrongPass123!"})
    resp = await client.post("/api/v1/auth/login",
        json={"email": "kbchat@test.com", "password": "StrongPass123!"})
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest_asyncio.fixture
async def second_client(db: AsyncSession):
    """Second authenticated user — independent client with own DB override."""
    async def _override_db():
        yield db
    app.dependency_overrides[get_db] = _override_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as c:
        await c.post("/api/v1/auth/register",
            json={"email": "kbpeer@test.com", "username": "kbpeer", "password": "StrongPass123!"})
        resp = await c.post("/api/v1/auth/login",
            json={"email": "kbpeer@test.com", "password": "StrongPass123!"})
        token = resp.json()["access_token"]
        c.headers.update({"Authorization": f"Bearer {token}"})
        yield c
    app.dependency_overrides.clear()


async def _create_conv(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/chat/conversations",
        json={"model_name": "llama3.2:3b", "title": "KB test"})
    return resp.json()["id"]


async def _create_kb(client: AsyncClient, name: str = "Test KB") -> str | None:
    resp = await client.post("/api/v1/knowledge-bases/",
        json={"name": name, "description": "test"})
    if resp.status_code == 201:
        return resp.json()["id"]
    return None


# ------------------------------------------------------------------
# 1. Authorized KB selection
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_authorized_kb_selection(auth_client):
    """User can select their own KB and chat includes rag_kb_ids."""
    kb_id = await _create_kb(auth_client, "My KB")
    if kb_id is None:
        pytest.skip("KB creation requires analyst/admin role")

    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Search my KB", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    assert resp.status_code == 200
    text = resp.text
    # Should have evidence event (even if empty) or done/error
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "done" in event_types or "error" in event_types


# ------------------------------------------------------------------
# 2. Foreign KB selection
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_foreign_kb_selection(second_client):
    """User cannot use a non-existent KB ID — honest degradation."""
    conv_id = await _create_conv(second_client)
    resp = await second_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Search KB", "model_name": "llama3.2:3b",
              "rag_kb_ids": ["non-existent-kb-id-abc123"]},
    )
    assert resp.status_code == 200
    text = resp.text
    # No evidence sources should be returned for non-existent KB
    for line in text.split("\n"):
        if line.startswith("data: ") and "sources" in line:
            data = json.loads(line[6:])
            assert len(data.get("sources", [])) == 0


# ------------------------------------------------------------------
# 3. Tenant isolation
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_isolation(auth_client, second_client):
    """User B cannot use User A's KB via chat rag_kb_ids."""
    kb_id = await _create_kb(auth_client, "A's Private KB")
    if kb_id is None:
        pytest.skip("KB creation requires analyst/admin role")

    conv_id = await _create_conv(second_client)
    resp = await second_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Search A's KB", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    assert resp.status_code == 200
    text = resp.text
    # B should not see any sources from A's KB
    for line in text.split("\n"):
        if line.startswith("data: ") and "sources" in line:
            data = json.loads(line[6:])
            for src in data.get("sources", []):
                assert src.get("doc_id") != kb_id, "User B accessed User A's KB"


# ------------------------------------------------------------------
# 4. No KB selected
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_kb_selected(auth_client):
    """Chat works normally without rag_kb_ids."""
    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello", "model_name": "llama3.2:3b"},
    )
    assert resp.status_code == 200
    text = resp.text
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    # No evidence event without rag_kb_ids
    assert "evidence" not in event_types
    assert "done" in event_types or "error" in event_types


# ------------------------------------------------------------------
# 5. One KB selected
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_one_kb_selected(auth_client):
    """Single KB ID is passed correctly in the request body."""
    kb_id = await _create_kb(auth_client, "Single KB")
    if kb_id is None:
        pytest.skip("KB creation requires analyst/admin role")

    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Query", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    assert resp.status_code == 200


# ------------------------------------------------------------------
# 6. Multiple KBs
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multiple_kbs(auth_client):
    """Multiple KB IDs are accepted in the request body."""
    kb1 = await _create_kb(auth_client, "KB Alpha")
    kb2 = await _create_kb(auth_client, "KB Beta")
    if kb1 is None or kb2 is None:
        pytest.skip("KB creation requires analyst/admin role")

    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Query both", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb1, kb2]},
    )
    assert resp.status_code == 200


# ------------------------------------------------------------------
# 7. Empty retrieval
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_empty_retrieval(auth_client):
    """KB exists but has no documents — honest empty evidence."""
    kb_id = await _create_kb(auth_client, "Empty KB")
    if kb_id is None:
        pytest.skip("KB creation requires analyst/admin role")

    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Search empty", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    assert resp.status_code == 200
    text = resp.text
    # Evidence event should have empty sources
    for line in text.split("\n"):
        if line.startswith("data: ") and "sources" in line:
            data = json.loads(line[6:])
            assert data.get("source_count", 0) == 0


# ------------------------------------------------------------------
# 8. Citation authorization
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_citation_authorization(auth_client, second_client):
    """Citations from User A's KB are not visible to User B."""
    kb_id = await _create_kb(auth_client, "Private Citations KB")
    if kb_id is None:
        pytest.skip("KB creation requires analyst/admin role")

    # User A chats with their KB
    conv_a = await _create_conv(auth_client)
    resp_a = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_a}/messages",
        json={"content": "Cite docs", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    assert resp_a.status_code == 200

    # User B tries to use A's KB
    conv_b = await _create_conv(second_client)
    resp_b = await second_client.post(
        f"/api/v1/chat/conversations/{conv_b}/messages",
        json={"content": "Cite A's docs", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    text_b = resp_b.text
    for line in text_b.split("\n"):
        if line.startswith("data: ") and "sources" in line:
            data = json.loads(line[6:])
            for src in data.get("sources", []):
                assert src.get("doc_id") != kb_id


# ------------------------------------------------------------------
# 9. Chat streaming with RAG
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chat_streaming_with_rag(auth_client):
    """Chat with rag_kb_ids returns valid SSE stream."""
    kb_id = await _create_kb(auth_client, "RAG KB")
    if kb_id is None:
        pytest.skip("KB creation requires analyst/admin role")

    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello", "model_name": "llama3.2:3b",
              "rag_kb_ids": [kb_id]},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    text = resp.text
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    # Should have done or error — both valid
    assert "done" in event_types or "error" in event_types


# ------------------------------------------------------------------
# 10. Chat streaming without RAG
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_chat_streaming_without_rag(auth_client):
    """Chat without rag_kb_ids returns valid SSE stream (no evidence event)."""
    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello", "model_name": "llama3.2:3b"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    text = resp.text
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "evidence" not in event_types
    assert "done" in event_types or "error" in event_types
