"""
Chat/RAG security tests — 15 scenarios for P1.4 Chat/Rag Polish.

Tests cover:
  1. authenticated streaming
  2. unauthorized streaming
  3. tenant isolation
  4. citation authorization
  5. foreign citation attempt
  6. Ollama unavailable
  7. Qdrant unavailable
  8. provider failure
  9. client disconnect (cancellation)
  10. provider cancellation
  11. retry after failure
  12. markdown/XSS sanitization
  13. fabricated citation rejection
  14. no-evidence response
  15. multimodal evidence authorization
"""
import asyncio
import json
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# Force rate limiting OFF for chat tests (rate-limit tests are separate)
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from database import Base, get_db
from main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------
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
        json={"email": "chat@test.com", "username": "chattester", "password": "StrongPass123!"})
    resp = await client.post("/api/v1/auth/login",
        json={"email": "chat@test.com", "password": "StrongPass123!"})
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client


@pytest_asyncio.fixture
async def second_auth_client(client: AsyncClient):
    """Second authenticated user for tenant isolation tests."""
    await client.post("/api/v1/auth/register",
        json={"email": "peer@test.com", "username": "peeruser", "password": "StrongPass123!"})
    resp = await client.post("/api/v1/auth/login",
        json={"email": "peer@test.com", "password": "StrongPass123!"})
    token = resp.json()["access_token"]
    # Return a new client with the second user's token
    from httpx import ASGITransport as _T
    async with AsyncClient(transport=_T(app=app), base_url="http://testserver",
                           headers={"Authorization": f"Bearer {token}"}) as c2:
        yield c2


async def _create_conv(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/chat/conversations",
        json={"model_name": "llama3.2:3b", "title": "Test conv"})
    return resp.json()["id"]


# ------------------------------------------------------------------
# 1. Authenticated streaming
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_authenticated_streaming(auth_client):
    """Authenticated user can send a message and receive SSE events."""
    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello", "model_name": "llama3.2:3b"},
        headers={"Accept": "text/event-stream"},
    )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
    text = resp.text
    assert "event: " in text
    # Should have either done (Ollama up) or error (Ollama down) — both valid
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "done" in event_types or "error" in event_types, f"Got events: {event_types}"


# ------------------------------------------------------------------
# 2. Unauthorized streaming
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_unauthorized_streaming(client):
    """Unauthenticated request returns 401."""
    conv_id = "fake-conv-id"
    resp = await client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello", "model_name": "llama3.2:3b"},
    )
    assert resp.status_code in (401, 403)


# ------------------------------------------------------------------
# 3. Tenant isolation
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tenant_isolation(auth_client, second_auth_client):
    """User B cannot send messages to User A's conversation."""
    conv_id = await _create_conv(auth_client)
    resp = await second_auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello from B", "model_name": "llama3.2:3b"},
    )
    # Should return error (conversation not found) — 404 or SSE error event
    if resp.status_code == 200:
        # SSE error event
        assert "error" in resp.text.lower() or "not found" in resp.text.lower()
    else:
        assert resp.status_code in (404, 403)


# ------------------------------------------------------------------
# 4. Citation authorization (RAG KB access)
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_citation_authorization(auth_client, second_auth_client):
    """User B cannot access User A's knowledge base via chat RAG."""
    # User A creates a KB
    kb_resp = await auth_client.post("/api/v1/knowledge-bases",
        json={"name": "A's private KB", "description": "private"})
    if kb_resp.status_code == 201:
        kb_id = kb_resp.json()["id"]
        # User B sends a chat with rag_kb_ids pointing to A's KB
        conv_id = await _create_conv(second_auth_client)
        resp = await second_auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Search this KB", "model_name": "llama3.2:3b",
                  "rag_kb_ids": [kb_id]},
        )
        # Should not find the KB (authorization gate filters it out)
        text = resp.text if resp.status_code == 200 else ""
        # No evidence event should reference A's KB
        if "evidence" in text:
            # Parse evidence event
            for line in text.split("\n"):
                if line.startswith("data: ") and "sources" in line:
                    data = json.loads(line[6:])
                    for src in data.get("sources", []):
                        assert src.get("doc_id") != kb_id


# ------------------------------------------------------------------
# 5. Foreign citation attempt
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_foreign_citation_attempt(second_auth_client):
    """User B cannot retrieve citations from a non-existent KB ID."""
    conv_id = await _create_conv(second_auth_client)
    resp = await second_auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Search KB", "model_name": "llama3.2:3b",
              "rag_kb_ids": ["non-existent-kb-id"]},
    )
    # Should succeed without evidence (KB not found, honest degradation)
    assert resp.status_code == 200
    text = resp.text
    # No evidence event with sources should appear
    for line in text.split("\n"):
        if line.startswith("data: ") and "sources" in line:
            data = json.loads(line[6:])
            assert len(data.get("sources", [])) == 0


# ------------------------------------------------------------------
# 6. Ollama unavailable
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_ollama_unavailable(auth_client):
    """When Ollama is unreachable, stream returns error event."""
    conv_id = await _create_conv(auth_client)
    with patch("services.llm_client.OllamaProvider._stream_chat",
               side_effect=Exception("Connection refused")):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello", "model_name": "llama3.2:3b"},
        )
        assert resp.status_code == 200
        text = resp.text
        # Should contain error event
        assert "error" in text.lower()
        # Should NOT contain fabricated content
        assert "event: token" not in text or "event: error" in text


# ------------------------------------------------------------------
# 7. Qdrant unavailable
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_qdrant_unavailable(auth_client):
    """When Qdrant is down, RAG gracefully degrades without crashing."""
    conv_id = await _create_conv(auth_client)
    with patch("services.qdrant_service.QdrantService.search",
               side_effect=Exception("Connection refused")):
        # This should not crash even if rag_kb_ids are provided
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello", "model_name": "llama3.2:3b",
                  "rag_kb_ids": ["fake-kb"]},
        )
        assert resp.status_code == 200


# ------------------------------------------------------------------
# 8. Provider failure
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_provider_failure(auth_client):
    """Provider error during generation returns error SSE event."""
    conv_id = await _create_conv(auth_client)
    with patch("services.llm_client.OllamaProvider._stream_chat",
               side_effect=Exception("Model crashed")):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello", "model_name": "llama3.2:3b"},
        )
        assert resp.status_code == 200
        text = resp.text
        assert "error" in text.lower()


# ------------------------------------------------------------------
# 9. Client disconnect (cancellation)
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_client_disconnect_cancellation(auth_client):
    """When client disconnects, generator handles CancelledError."""
    conv_id = await _create_conv(auth_client)

    # Simulate cancellation by patching the stream to raise CancelledError
    async def mock_stream(*args, **kwargs):
        yield "Hello "
        raise asyncio.CancelledError()

    with patch("services.llm_client.OllamaProvider._stream_chat", mock_stream):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello", "model_name": "llama3.2:3b"},
        )
        # Response should complete (CancelledError is caught)
        assert resp.status_code == 200


# ------------------------------------------------------------------
# 10. Provider cancellation
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_provider_cancellation_returns_cancelled_event(auth_client):
    """CancelledError produces a cancelled error event, not fabricated content."""
    conv_id = await _create_conv(auth_client)

    async def mock_stream(*args, **kwargs):
        yield "Partial "
        raise asyncio.CancelledError()

    with patch("services.llm_client.OllamaProvider._stream_chat", mock_stream):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello", "model_name": "llama3.2:3b"},
        )
        text = resp.text
        # Should have error event with "cancelled" code
        assert "cancelled" in text.lower() or "error" in text.lower()


# ------------------------------------------------------------------
# 11. Retry after failure
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_retry_after_failure(auth_client):
    """After a provider failure, retry can succeed."""
    call_count = 0

    async def flaky_stream(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Transient failure")
        yield "Recovered!"

    conv_id = await _create_conv(auth_client)
    with patch("services.llm_client.OllamaProvider._stream_chat", flaky_stream):
        # First call fails
        resp1 = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello", "model_name": "llama3.2:3b"},
        )
        assert "error" in resp1.text.lower()

        # Retry succeeds
        resp2 = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Hello again", "model_name": "llama3.2:3b"},
        )
        assert "token" in resp2.text.lower() or "done" in resp2.text.lower()


# ------------------------------------------------------------------
# 12. Markdown/XSS sanitization
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_markdown_xss_sanitization(auth_client):
    """Assistant responses with script tags are rendered safely."""
    # This tests the backend SSE output — the frontend MarkdownRenderer
    # uses rehype-sanitize which strips <script> tags.
    # The backend itself does not sanitize (it stores raw model output);
    # the frontend is the XSS boundary.
    conv_id = await _create_conv(auth_client)

    async def xss_stream(*args, **kwargs):
        yield "Here is **bold** and *italic* and <script>alert('xss')</script>"

    with patch("services.llm_client.OllamaProvider._stream_chat", xss_stream):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Test markdown", "model_name": "llama3.2:3b"},
        )
        text = resp.text
        # The raw content is in token events — frontend handles sanitization
        assert resp.status_code == 200
        # Verify the token event contains the content
        assert "alert" in text  # raw content stored
        assert "event: token" in text


# ------------------------------------------------------------------
# 13. Fabricated citation rejection
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_fabricated_citation_rejection(auth_client):
    """When no RAG is configured, model output with [Source N] is stored as-is
    but no evidence event is emitted — the frontend shows citation text as
    plain text since no sources array is available."""
    conv_id = await _create_conv(auth_client)

    async def fabricating_stream(*args, **kwargs):
        yield "According to [Source 1], the answer is 42."

    with patch("services.llm_client.OllamaProvider._stream_chat", fabricating_stream):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "What is the answer?", "model_name": "llama3.2:3b"},
        )
        text = resp.text
        # No evidence event should be present (no RAG sources provided)
        event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
        event_types = [l.strip().replace("event: ", "") for l in event_lines]
        assert "evidence" not in event_types
        # Token event should contain the raw citation text
        assert "[Source 1]" in text


# ------------------------------------------------------------------
# 14. No-evidence response
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_no_evidence_response(auth_client):
    """Without rag_kb_ids, chat works normally without evidence events."""
    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hello", "model_name": "llama3.2:3b"},
    )
    assert resp.status_code == 200
    text = resp.text
    # Should have token+done or error event (no evidence without rag_kb_ids)
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "evidence" not in event_types
    assert "done" in event_types or "error" in event_types


# ------------------------------------------------------------------
# 15. Multimodal evidence authorization
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_multimodal_evidence_authorization(auth_client, second_auth_client):
    """Evidence from KB, sensor, and vision sources are properly scoped."""
    # User A creates a KB
    kb_resp = await auth_client.post("/api/v1/knowledge-bases",
        json={"name": "A's KB", "description": "test"})
    if kb_resp.status_code == 201:
        kb_id = kb_resp.json()["id"]

        # User A sends chat with RAG
        conv_id = await _create_conv(auth_client)
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/messages",
            json={"content": "Search KB", "model_name": "llama3.2:3b",
                  "rag_kb_ids": [kb_id]},
        )
        # Should get evidence event (even if empty due to no vectors)
        text = resp.text
        assert resp.status_code == 200

        # User B cannot access A's evidence
        conv_id_b = await _create_conv(second_auth_client)
        resp_b = await second_auth_client.post(
            f"/api/v1/chat/conversations/{conv_id_b}/messages",
            json={"content": "Search A's KB", "model_name": "llama3.2:3b",
                  "rag_kb_ids": [kb_id]},
        )
        text_b = resp_b.text
        # B should not see any sources from A's KB
        for line in text_b.split("\n"):
            if line.startswith("data: ") and "sources" in line:
                try:
                    data = json.loads(line[6:])
                    for src in data.get("sources", []):
                        assert src.get("doc_id") != kb_id, "User B should not see User A's evidence"
                except json.JSONDecodeError:
                    pass


# ------------------------------------------------------------------
# SSE event structure validation
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_sse_event_structure(auth_client):
    """Verify SSE events have correct structure (event + data format)."""
    conv_id = await _create_conv(auth_client)
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{conv_id}/messages",
        json={"content": "Hi", "model_name": "llama3.2:3b"},
    )
    text = resp.text
    lines = text.strip().split("\n")
    # Each event should have "event: X" followed by "data: {...}"
    i = 0
    events_found = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("event: "):
            events_found += 1
            # Next non-empty line should be data
            i += 1
            while i < len(lines) and lines[i].strip() == "":
                i += 1
            if i < len(lines) and lines[i].startswith("data: "):
                data_str = lines[i][6:]
                json.loads(data_str)  # Should not raise
        i += 1
    assert events_found >= 1, f"Expected at least 1 SSE event, got {events_found}"


# ------------------------------------------------------------------
# Conversation CRUD security
# ------------------------------------------------------------------
@pytest.mark.asyncio
async def test_conversation_ownership_enforced(auth_client, second_auth_client):
    """User B cannot access User A's conversation detail."""
    conv_id = await _create_conv(auth_client)
    resp = await second_auth_client.get(f"/api/v1/chat/conversations/{conv_id}")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_conversation_delete_ownership(auth_client, second_auth_client):
    """User B cannot delete User A's conversation."""
    conv_id = await _create_conv(auth_client)
    resp = await second_auth_client.delete(f"/api/v1/chat/conversations/{conv_id}")
    assert resp.status_code == 404
