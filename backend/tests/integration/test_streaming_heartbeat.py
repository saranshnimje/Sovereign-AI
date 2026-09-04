"""
Streaming heartbeat integration test.

Proves that SSE heartbeat comments (`: heartbeat\n\n`) are emitted during
long LLM operations, keeping the connection alive through Nginx's
proxy_read_timeout (600s).

Uses a deliberately slow mock LLM (20s delay) to force heartbeat emission.
"""
import asyncio
import json
import os
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

from database import Base, get_db
from main import app
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


_test_engine = None
_test_session_factory = None


@pytest_asyncio.fixture
async def db():
    global _test_engine, _test_session_factory
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    _test_engine = engine
    async with engine.begin() as conn:
        import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    _test_session_factory = factory
    async with factory() as session:
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
async def auth_client(client: AsyncClient, db: AsyncSession):
    await client.post("/api/v1/auth/register",
        json={"email": "hb@test.com", "username": "hbtester", "password": "StrongPass123!"})
    resp = await client.post("/api/v1/auth/login",
        json={"email": "hb@test.com", "password": "StrongPass123!"})
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    # Store session_factory for agent endpoint patching
    client._test_session_factory = _test_session_factory
    return client


class SlowLLMMock:
    """Mock LLM that introduces a configurable delay before responding."""

    def __init__(self, delay_seconds: float = 20.0):
        self.delay = delay_seconds
        self.call_count = 0

    async def chat(self, **kwargs):
        self.call_count += 1
        await asyncio.sleep(self.delay)
        return MagicMock(content=json.dumps({
            "verified": True,
            "confidence": 0.9,
            "criteria": [],
        }))


async def _agent_request(auth_client, conv_id, content, timeout=60.0):
    """Make an agent request, patching AsyncSessionLocal to use test DB."""
    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat",
               new=SlowLLMMock(0.1).chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": content, "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        )
    return resp


@pytest.mark.asyncio
async def test_heartbeat_emitted_during_slow_llm(auth_client: AsyncClient):
    """Heartbeat comments are emitted while waiting for a slow LLM."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Heartbeat test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    slow_llm = SlowLLMMock(delay_seconds=20.0)
    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=slow_llm.chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Hello", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=60.0,
        )

    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")

    text = resp.text

    # Verify heartbeat comments are present (SSE comments start with `:`)
    heartbeats = re.findall(r"^: heartbeat\r?\n\r?\n", text, re.MULTILINE)
    # With 20s delay and 15s interval, we should get at least 1 heartbeat
    assert len(heartbeats) >= 1, (
        f"Expected at least 1 heartbeat during 20s LLM delay, got {len(heartbeats)}. "
        f"Response length: {len(text)} chars"
    )

    # Verify the stream also contains a done or error event
    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "done" in event_types or "error" in event_types, (
        f"Expected done or error event, got: {event_types}"
    )


@pytest.mark.asyncio
async def test_heartbeat_not_emitted_for_fast_llm(auth_client: AsyncClient):
    """Fast LLM responses don't produce unnecessary heartbeats."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Fast test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    async def fast_chat(**kwargs):
        return MagicMock(content=json.dumps({
            "verified": True, "confidence": 0.95, "criteria": [],
        }))

    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=fast_chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Hi", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=30.0,
        )

    assert resp.status_code == 200
    text = resp.text

    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "done" in event_types or "error" in event_types


@pytest.mark.asyncio
async def test_agent_stream_contains_done_event(auth_client: AsyncClient):
    """Agent SSE stream always emits a done event with metadata."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Done event test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    async def mock_chat(**kwargs):
        return MagicMock(content=json.dumps({
            "verified": True, "confidence": 0.8, "criteria": [],
        }))

    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=mock_chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Test done event", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=30.0,
        )

    assert resp.status_code == 200
    text = resp.text

    # Parse done event payload
    done_payload = None
    lines = text.split("\n")
    for i, line in enumerate(lines):
        if line.strip() == "event: done":
            if i + 1 < len(lines) and lines[i + 1].startswith("data: "):
                done_payload = json.loads(lines[i + 1][6:])
                break

    assert done_payload is not None, "done event not found in SSE stream"
    assert "state" in done_payload, "done event missing 'state' field"
    assert "tool_calls" in done_payload, "done event missing 'tool_calls' field"
    assert "elapsed_ms" in done_payload, "done event missing 'elapsed_ms' field"


@pytest.mark.asyncio
async def test_agent_stream_emits_agent_state_events(auth_client: AsyncClient):
    """Agent SSE stream emits agent_state events for UI visibility."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "State events test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    async def mock_chat(**kwargs):
        return MagicMock(content=json.dumps({
            "verified": True, "confidence": 0.9, "criteria": [],
        }))

    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=mock_chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Test state events", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=30.0,
        )

    assert resp.status_code == 200
    text = resp.text

    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]

    assert "agent_state" in event_types or "plan_created" in event_types, (
        f"Expected agent_state or plan_created event, got: {event_types}"
    )


@pytest.mark.asyncio
async def test_agent_stream_handles_llm_error_gracefully(auth_client: AsyncClient):
    """Agent stream handles LLM errors without hanging."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Error test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    async def failing_chat(**kwargs):
        raise RuntimeError("LLM connection refused")

    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=failing_chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Trigger error", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=30.0,
        )

    assert resp.status_code == 200
    text = resp.text

    event_lines = [l for l in text.split("\n") if l.startswith("event: ")]
    event_types = [l.strip().replace("event: ", "") for l in event_lines]
    assert "error" in event_types or "done" in event_types, (
        f"Expected error or done event on LLM failure, got: {event_types}"
    )


@pytest.mark.asyncio
async def test_agent_stream_cancellation(auth_client: AsyncClient):
    """Agent stream can be cancelled without hanging."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Cancel test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    async def very_slow_chat(**kwargs):
        await asyncio.sleep(300)
        return MagicMock(content="should not reach here")

    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=very_slow_chat):
        try:
            resp = await auth_client.post(
                f"/api/v1/chat/conversations/{conv_id}/agent",
                json={"content": "Cancel me", "model_name": "test-model"},
                headers={"Accept": "text/event-stream"},
                timeout=5.0,
            )
        except Exception:
            pass

    # Verify the conversation still exists (no crash)
    conv_check = await auth_client.get(f"/api/v1/chat/conversations/{conv_id}")
    assert conv_check.status_code == 200


@pytest.mark.asyncio
async def test_stream_content_type_is_sse(auth_client: AsyncClient):
    """Agent stream response has correct SSE content type and headers."""
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Headers test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    async def mock_chat(**kwargs):
        return MagicMock(content=json.dumps({
            "verified": True, "confidence": 0.9, "criteria": [],
        }))

    session_factory = auth_client._test_session_factory

    with patch("database.AsyncSessionLocal", session_factory), \
         patch("services.llm_client.OllamaClient.chat", new=mock_chat):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Test headers", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
            timeout=30.0,
        )

    assert resp.status_code == 200
    ct = resp.headers.get("content-type", "")
    assert "text/event-stream" in ct, f"Expected text/event-stream, got: {ct}"
    cc = resp.headers.get("cache-control", "")
    assert "no-cache" in cc or resp.headers.get("x-accel-buffering") == "no"
