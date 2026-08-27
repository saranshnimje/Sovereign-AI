"""
Phase 4 integration tests — settings, dashboard, model management, audit, user management.
"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient


# ------------------------------------------------------------------
# Settings
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_settings_admin_only(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/settings/")
    assert resp.status_code == 200
    data = resp.json()
    assert "default_chunk_size" in data
    assert "default_max_iterations" in data
    assert "sandbox_timeout_s" in data


@pytest.mark.asyncio
async def test_get_settings_requires_admin(client: AsyncClient):
    # Register admin + viewer
    await client.post("/api/v1/auth/register", json={
        "email": "admin@s.com", "username": "admins", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "viewer@s.com", "username": "viewers", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "viewer@s.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.get("/api/v1/settings/")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_update_settings_persists(auth_client: AsyncClient):
    # Patch where the router actually calls it (imported symbol)
    with patch("routers.settings.save_settings") as mock_save:
        resp = await auth_client.put("/api/v1/settings/", json={
            "default_chunk_size": 256,
            "default_chunk_overlap": 25,
            "default_top_k": 3,
            "default_score_threshold": 0.5,
            "default_max_iterations": 5,
            "approval_timeout_minutes": 3,
            "sandbox_timeout_s": 20,
            "sandbox_mem_limit_mb": 128,
            "sandbox_cpu_quota": 25000,
            "max_upload_size_mb": 25,
        })
    assert resp.status_code == 200
    assert resp.json()["default_chunk_size"] == 256
    mock_save.assert_called_once()


@pytest.mark.asyncio
async def test_settings_validation_rejects_bad_values(auth_client: AsyncClient):
    resp = await auth_client.put("/api/v1/settings/", json={
        "default_chunk_size": 10000,  # exceeds max 4096
        "default_chunk_overlap": 0,
        "default_top_k": 5,
        "default_score_threshold": 0.6,
        "default_max_iterations": 10,
        "approval_timeout_minutes": 5,
        "sandbox_timeout_s": 30,
        "sandbox_mem_limit_mb": 256,
        "sandbox_cpu_quota": 50000,
        "max_upload_size_mb": 50,
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_settings_validation_bad_iterations(auth_client: AsyncClient):
    resp = await auth_client.put("/api/v1/settings/", json={
        "default_chunk_size": 512,
        "default_chunk_overlap": 50,
        "default_top_k": 5,
        "default_score_threshold": 0.6,
        "default_max_iterations": 99,  # exceeds max 20
        "approval_timeout_minutes": 5,
        "sandbox_timeout_s": 30,
        "sandbox_mem_limit_mb": 256,
        "sandbox_cpu_quota": 50000,
        "max_upload_size_mb": 50,
    })
    assert resp.status_code == 422


# ------------------------------------------------------------------
# Dashboard summary
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_dashboard_summary_accessible(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/settings/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "knowledge_base_count" in data
    assert "document_count" in data
    assert "agent_run_count" in data
    assert "pending_approval_count" in data
    assert "total_audit_events" in data


@pytest.mark.asyncio
async def test_dashboard_summary_includes_operational_metrics(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/settings/summary")
    assert resp.status_code == 200
    data = resp.json()
    assert "sensor_analysis_count" in data
    assert "incident_count" in data
    assert "critical_risk_count" in data
    assert "high_risk_count" in data
    assert isinstance(data["sensor_analysis_count"], int)
    assert isinstance(data["incident_count"], int)
    assert isinstance(data["critical_risk_count"], int)
    assert isinstance(data["high_risk_count"], int)
    assert data["sensor_analysis_count"] == 0
    assert data["incident_count"] == 0
    assert data["critical_risk_count"] == 0
    assert data["high_risk_count"] == 0


@pytest.mark.asyncio
async def test_dashboard_summary_unauthenticated_denied(client: AsyncClient):
    resp = await client.get("/api/v1/settings/summary")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_system_activity_endpoint(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/system/activity?limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_activity_contains_required_fields(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/system/activity?limit=10")
    assert resp.status_code == 200
    for item in resp.json()["items"]:
        assert "event_type" in item
        assert "action" in item
        assert "outcome" in item
        assert "timestamp" in item
        # Security: must NOT expose full metadata
        assert "password" not in json.dumps(item).lower()


# ------------------------------------------------------------------
# Model management
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_models_authenticated(auth_client: AsyncClient):
    with patch("services.llm_client.OllamaClient.list_models",
               new=AsyncMock(return_value=[])):
        resp = await auth_client.get("/api/v1/models/")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_get_model_roles(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/models/roles")
    assert resp.status_code == 200
    data = resp.json()
    assert "chat" in data
    assert "embedding" in data


@pytest.mark.asyncio
async def test_set_model_role_admin_only(auth_client: AsyncClient):
    with patch("services.model_service._save_roles"):
        resp = await auth_client.put("/api/v1/models/roles", json={
            "role": "chat",
            "model_name": "llama3.2:3b"
        })
    assert resp.status_code == 200
    assert resp.json()["chat"] == "llama3.2:3b"


@pytest.mark.asyncio
async def test_set_invalid_role_rejected(auth_client: AsyncClient):
    resp = await auth_client.put("/api/v1/models/roles", json={
        "role": "invalid_role",
        "model_name": "some-model"
    })
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_model_health_check(auth_client: AsyncClient):
    with patch("services.llm_client.OllamaClient.health_check",
               new=AsyncMock(return_value=(True, 15))):
        resp = await auth_client.get("/api/v1/models/health/llama3.2:3b")
    assert resp.status_code == 200
    assert "status" in resp.json()


# ------------------------------------------------------------------
# Audit log API
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audit_logs_admin_only(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/audit/logs")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


@pytest.mark.asyncio
async def test_audit_verify_chain(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/audit/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert "verified" in data
    assert "entries_checked" in data
    assert "message" in data


@pytest.mark.asyncio
async def test_audit_export_csv(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/audit/export?format=csv")
    assert resp.status_code == 200
    assert "text/csv" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_audit_export_json(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/audit/export?format=json")
    assert resp.status_code == 200
    assert "application/json" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_audit_filter_by_event_type(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/audit/logs?event_type=auth")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_audit_filter_by_outcome(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/audit/logs?outcome=success")
    assert resp.status_code == 200


# ------------------------------------------------------------------
# First-run / Setup
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_setup_required_true_with_no_users(client: AsyncClient):
    resp = await client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["setup_required"] is True


@pytest.mark.asyncio
async def test_setup_required_false_after_registration(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "email": "firstadmin@x.com", "username": "firstadmin", "password": "StrongPass123!"
    })
    resp = await client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["setup_required"] is False


@pytest.mark.asyncio
async def test_first_user_always_gets_admin_role(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "onlyadmin@x.com", "username": "onlyadmin", "password": "StrongPass123!"
    })
    assert resp.status_code == 201
    assert resp.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_password_validation_minimum_length(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json={
        "email": "weak@x.com", "username": "weakuser", "password": "short"
    })
    assert resp.status_code == 422


# ------------------------------------------------------------------
# Approvals badge
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_approval_count_endpoint(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/approvals/count")
    assert resp.status_code == 200
    data = resp.json()
    assert "count" in data
    assert isinstance(data["count"], int)
    assert data["count"] >= 0


@pytest.mark.asyncio
async def test_approval_count_requires_admin(client: AsyncClient):
    await client.post("/api/v1/auth/register", json={
        "email": "adm@badge.com", "username": "admbadge", "password": "StrongPass123!"
    })
    await client.post("/api/v1/auth/register", json={
        "email": "v@badge.com", "username": "vbadge", "password": "StrongPass123!"
    })
    resp = await client.post("/api/v1/auth/login", json={
        "email": "v@badge.com", "password": "StrongPass123!"
    })
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    resp = await client.get("/api/v1/approvals/count")
    assert resp.status_code == 403


# ------------------------------------------------------------------
# User management
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_users_admin_only(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/settings/users")
    assert resp.status_code == 200
    users = resp.json()
    assert isinstance(users, list)
    assert len(users) >= 1
    # Security: passwords must never be exposed
    for u in users:
        assert "password" not in u
        assert "password_hash" not in u


@pytest.mark.asyncio
async def test_update_user_role(auth_client: AsyncClient):
    # Create a second user
    await auth_client.post("/api/v1/auth/register", json={
        "email": "toupdate@x.com", "username": "toupdate", "password": "StrongPass123!"
    })
    users = (await auth_client.get("/api/v1/settings/users")).json()
    target = next(u for u in users if u["username"] == "toupdate")

    resp = await auth_client.put(f"/api/v1/auth/users/{target['id']}", json={
        "role": "analyst"
    })
    assert resp.status_code == 200
    assert resp.json()["role"] == "analyst"
