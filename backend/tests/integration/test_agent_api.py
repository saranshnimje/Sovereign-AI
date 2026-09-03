"""
Integration tests for Agent API endpoints.
Tests the agents router (read-only + cancel) and the agent chat endpoint.
External services (LLM, Docker sandbox) are fully mocked.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

from models.base import generate_uuid


# ------------------------------------------------------------------
# Agent run management (agents router — read-only + cancel)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_agent_runs_empty(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/agents/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "items" in data
    assert "total" in data
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_get_nonexistent_run_404(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/agents/runs/nonexistent-id")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_cancel_nonexistent_run_404(auth_client: AsyncClient):
    resp = await auth_client.post(f"/api/v1/agents/runs/{generate_uuid()}/cancel")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_run_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/agents/runs")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_cancel_requires_admin(client: AsyncClient):
    # Register admin + viewer
    await client.post("/api/v1/auth/register", json={
        "email": "adm_api@e.com", "username": "adm_api", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "viewer_api@e.com", "username": "viewer_api", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "viewer_api@e.com", "password": "StrongPass123!"
    })
    token = resp.json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"

    resp = await client.post(f"/api/v1/agents/runs/{generate_uuid()}/cancel")
    assert resp.status_code == 403


# ------------------------------------------------------------------
# Agent chat endpoint (the real agent loop via AgentRuntime)
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_chat_requires_conversation(auth_client: AsyncClient):
    """Agent chat must reference a valid conversation."""
    resp = await auth_client.post(
        f"/api/v1/chat/conversations/{generate_uuid()}/agent",
        json={"content": "test", "model_name": "test-model"}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_chat_requires_auth(client: AsyncClient):
    resp = await client.post(
        f"/api/v1/chat/conversations/{generate_uuid()}/agent",
        json={"content": "test", "model_name": "test-model"}
    )
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_agent_chat_sse_emits_events(auth_client: AsyncClient):
    """Agent chat returns SSE stream with events."""
    # Create a conversation
    conv_resp = await auth_client.post("/api/v1/chat/conversations", json={
        "title": "Agent test", "model_name": "test-model"
    })
    conv_id = conv_resp.json()["id"]

    # We can't easily test the full SSE stream without a real LLM,
    # but we can verify the endpoint exists and returns proper SSE headers
    with patch("services.llm_client.OllamaClient.chat",
               new=AsyncMock(return_value=MagicMock(
                   content="I can help you with that."))):
        resp = await auth_client.post(
            f"/api/v1/chat/conversations/{conv_id}/agent",
            json={"content": "Hello", "model_name": "test-model"},
            headers={"Accept": "text/event-stream"},
        )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers.get("content-type", "")
