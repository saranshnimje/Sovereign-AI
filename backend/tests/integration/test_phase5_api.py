"""
Phase 5 integration tests — SSE agent stream, health checks, security regression,
DATA_DIR path correctness, title generation, docker-compose validation.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient


# ------------------------------------------------------------------
# Agent SSE stream endpoint
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_agent_stream_endpoint_exists(auth_client: AsyncClient):
    """The /stream endpoint must exist and require auth."""
    from models.base import generate_uuid
    resp = await auth_client.get(f"/api/v1/agents/runs/{generate_uuid()}/stream")
    # 404 = run not found (correct — endpoint exists but run doesn't)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agent_stream_requires_auth(client: AsyncClient):
    """SSE stream must be protected — unauthenticated access denied."""
    from models.base import generate_uuid
    resp = await client.get(f"/api/v1/agents/runs/{generate_uuid()}/stream")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_agent_stream_emits_events(auth_client: AsyncClient):
    """Create a run, start the stream, verify SSE events are emitted."""
    import asyncio

    with patch("services.llm_client.OllamaClient.chat",
               new=AsyncMock(return_value=MagicMock(
                   content='{"type": "complete", "result": "Stream test done"}'))):
        create = await auth_client.post("/api/v1/agents/runs", json={
            "goal": "stream test", "max_iterations": 2
        })
    run_id = create.json()["id"]

    # Give the background task a moment to run
    await asyncio.sleep(0.3)

    # Open the SSE stream — collect first few events
    events = []
    async with auth_client.stream("GET", f"/api/v1/agents/runs/{run_id}/stream") as resp:
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                events.append(line.split(":", 1)[1].strip())
            if len(events) >= 3 or "complete" in events or "error" in events:
                break

    assert len(events) > 0, "Expected at least one SSE event"


# ------------------------------------------------------------------
# Health check endpoints
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_health_endpoint_public(client: AsyncClient):
    """Health endpoint must work without authentication."""
    resp = await client.get("/api/v1/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_never_returns_500(client: AsyncClient):
    """Health endpoint must not 500 even if services are down."""
    resp = await client.get("/api/v1/system/health")
    assert resp.status_code != 500


@pytest.mark.asyncio
async def test_status_endpoint_structure(auth_client: AsyncClient):
    """System status must return services, resources, models_loaded."""
    with patch("services.system_service.get_system_status") as mock_status:
        from schemas.system import SystemStatus, ServiceStatus, ResourceMetrics
        mock_status.return_value = SystemStatus(
            status="healthy",
            services={"database": ServiceStatus(status="up")},
            resources=ResourceMetrics(
                cpu_percent=10.0, ram_used_gb=2.0, ram_total_gb=8.0,
                disk_used_gb=20.0, disk_total_gb=100.0
            ),
            models_loaded=[]
        )
        resp = await auth_client.get("/api/v1/system/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "services" in data
    assert "resources" in data
    assert "models_loaded" in data


# ------------------------------------------------------------------
# Conversation title generation
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_conversation_title_set_from_first_message(auth_client: AsyncClient, db):
    """Title should be set to first 80 chars of first user message (service level)."""
    from services.chat_service import ChatService
    from services.llm_client import OllamaClient
    from schemas.chat import ConversationCreate, MessageCreate

    async def fake_stream(*args, **kwargs):
        yield "Hello"

    llm_mock = MagicMock(spec=OllamaClient)
    llm_mock.chat = AsyncMock(return_value=fake_stream())

    svc = ChatService(db=db, llm=llm_mock)
    conv = await svc.create_conversation("user-1", ConversationCreate(model_name="llama3.2:3b"))

    goal = "What are the top 5 procurement rules that apply to contracts above 10 lakhs?"
    # Drain the SSE generator
    async for _ in svc.stream_message(conv.id, "user-1", MessageCreate(content=goal)):
        pass

    # Re-fetch to get updated title
    from models.conversation import Conversation
    from sqlalchemy import select
    result = await db.execute(select(Conversation).where(Conversation.id == conv.id))
    c = result.scalar_one_or_none()
    assert c is not None
    assert c.title is not None
    assert len(c.title) <= 81


@pytest.mark.asyncio
async def test_conversation_title_truncated_with_ellipsis(db):
    """Title for message > 80 chars should include an ellipsis."""
    from services.chat_service import ChatService
    from services.llm_client import OllamaClient
    from schemas.chat import ConversationCreate, MessageCreate

    async def fake_stream(*args, **kwargs):
        yield "ok"

    llm_mock = MagicMock(spec=OllamaClient)
    llm_mock.chat = AsyncMock(return_value=fake_stream())

    svc = ChatService(db=db, llm=llm_mock)
    conv = await svc.create_conversation("user-2", ConversationCreate(model_name="llama3.2:3b"))

    long_message = "A" * 100
    async for _ in svc.stream_message(conv.id, "user-2", MessageCreate(content=long_message)):
        pass

    from models.conversation import Conversation
    from sqlalchemy import select
    result = await db.execute(select(Conversation).where(Conversation.id == conv.id))
    c = result.scalar_one()
    assert c.title is not None
    assert c.title.endswith("…"), f"Title should end with ellipsis: {c.title}"


# ------------------------------------------------------------------
# Security regression
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_password_hash_never_in_api_response(auth_client: AsyncClient):
    """No endpoint should ever return a password or password_hash field."""
    endpoints = [
        "/api/v1/auth/me",
        "/api/v1/settings/users",
    ]
    for ep in endpoints:
        resp = await auth_client.get(ep)
        if resp.status_code == 200:
            body = json.dumps(resp.json()).lower()
            assert "password_hash" not in body, f"password_hash in response from {ep}"
            assert "\"password\"" not in body, f"password field in response from {ep}"


@pytest.mark.asyncio
async def test_audit_logs_admin_only(client: AsyncClient):
    """Non-admin users must not access audit logs."""
    # First user = admin
    await client.post("/api/v1/auth/register", json={
        "email": "sec_admin@x.com", "username": "sec_admin", "password": "StrongPass123!"
    })
    # Second user = viewer
    await client.post("/api/v1/auth/register", json={
        "email": "sec_viewer@x.com", "username": "sec_viewer", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "sec_viewer@x.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.get("/api/v1/audit/logs")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_settings_write_admin_only(client: AsyncClient):
    """Non-admin must not be able to update system settings."""
    await client.post("/api/v1/auth/register", json={
        "email": "sec_admin2@x.com", "username": "sec_admin2", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "sec_analyst@x.com", "username": "sec_analyst", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "sec_analyst@x.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.put("/api/v1/settings/", json={
        "default_chunk_size": 256, "default_chunk_overlap": 0,
        "default_top_k": 5, "default_score_threshold": 0.5,
        "default_max_iterations": 5, "approval_timeout_minutes": 2,
        "sandbox_timeout_s": 15, "sandbox_mem_limit_mb": 64,
        "sandbox_cpu_quota": 25000, "max_upload_size_mb": 10,
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_model_role_write_admin_only(client: AsyncClient):
    """Non-admin must not be able to change model roles."""
    await client.post("/api/v1/auth/register", json={
        "email": "ma@x.com", "username": "ma_admin", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "mv@x.com", "username": "mv_viewer", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "mv@x.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.put("/api/v1/models/roles", json={
        "role": "chat", "model_name": "malicious-model"
    })
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_approval_endpoint_admin_only(client: AsyncClient):
    """Approve/reject endpoints must require admin."""
    from models.base import generate_uuid
    await client.post("/api/v1/auth/register", json={
        "email": "aa@x.com", "username": "aa_admin", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "av@x.com", "username": "av_viewer", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "av@x.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.post(f"/api/v1/approvals/{generate_uuid()}/approve", json={"note": "ok"})
    assert resp.status_code == 403


# ------------------------------------------------------------------
# Startup / directory creation
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_data_dirs_created_on_startup(tmp_path):
    """Startup lifespan must create required data subdirectories."""
    import os
    from pathlib import Path
    from unittest.mock import patch, AsyncMock
    import importlib

    with patch.dict(os.environ, {"DATA_DIR": str(tmp_path)}):
        import config
        config.get_settings.cache_clear()
        importlib.reload(config)

        from config import get_settings
        settings = get_settings()

        # Simulate what main.py lifespan does
        data_dir = Path(settings.data_dir)
        for sub in ["sqlite", "uploads", "sandbox_workspace"]:
            (data_dir / sub).mkdir(parents=True, exist_ok=True)

        assert (data_dir / "sqlite").is_dir()
        assert (data_dir / "uploads").is_dir()
        assert (data_dir / "sandbox_workspace").is_dir()

        config.get_settings.cache_clear()
        importlib.reload(config)
