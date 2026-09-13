"""Integration tests for auth API endpoints."""
import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient):
    resp = await client.get("/api/v1/system/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_register_and_login(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "user@example.com", "username": "testuser", "password": "StrongPassword123!"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["email"] == "user@example.com"
    assert data["role"] == "admin"  # first user gets admin

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "StrongPassword123!"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    await client.post(
        "/api/v1/auth/register",
        json={"email": "u2@e.com", "username": "u2", "password": "StrongPassword123!"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "u2@e.com", "password": "WrongPassword999!"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_protected_endpoint_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/chat/conversations")
    assert resp.status_code == 401 or resp.status_code == 403


@pytest.mark.asyncio
async def test_get_current_user(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "admin@test.com"
    assert data["username"] == "testadmin"


@pytest.mark.asyncio
async def test_second_user_gets_viewer_role(auth_client: AsyncClient):
    resp = await auth_client.post(
        "/api/v1/auth/register",
        json={"email": "viewer@e.com", "username": "viewer1", "password": "StrongPassword123!"},
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "viewer"


@pytest.mark.asyncio
async def test_setup_status_no_users(client: AsyncClient):
    resp = await client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["setup_required"] is True


@pytest.mark.asyncio
async def test_setup_status_with_users(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/auth/setup-status")
    assert resp.status_code == 200
    assert resp.json()["setup_required"] is False


@pytest.mark.asyncio
async def test_duplicate_registration_fails(client: AsyncClient):
    payload = {"email": "dup@e.com", "username": "dupuser", "password": "StrongPassword123!"}
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_weak_password_rejected(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "w@e.com", "username": "weakpw", "password": "short"},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_conversations_accessible_after_auth(auth_client: AsyncClient):
    resp = await auth_client.get("/api/v1/chat/conversations")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ------------------------------------------------------------------
# GET /auth/demo-users
# ------------------------------------------------------------------

@pytest.mark.asyncio
async def test_demo_users_empty_db(client: AsyncClient):
    """demo-users returns an empty list when no users exist."""
    resp = await client.get("/api/v1/auth/demo-users")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_demo_users_unauthenticated(client: AsyncClient):
    """demo-users requires no auth token (rendered on login page)."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "u@e.com", "username": "ulist", "password": "StrongPassword123!"},
    )
    resp = await client.get("/api/v1/auth/demo-users")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_demo_users_returns_only_admin(client: AsyncClient):
    """demo-users returns ONLY the admin user, never viewers/analysts."""
    # First user is promoted to admin
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@admin.com", "username": "admin", "password": "admin12345678"},
    )
    # Second user is a viewer
    await client.post(
        "/api/v1/auth/register",
        json={"email": "viewer@e.com", "username": "viewer1", "password": "StrongPassword123!"},
    )
    resp = await client.get("/api/v1/auth/demo-users")
    assert resp.status_code == 200
    data = resp.json()

    assert len(data) == 1
    entry = data[0]
    assert entry["email"] == "admin@admin.com"
    assert entry["role"] == "admin"
    assert entry["has_demo_password"] is True
    assert entry["demo_password"] == "admin12345678"


@pytest.mark.asyncio
async def test_demo_users_no_analyst_returned(client: AsyncClient):
    """e2e_analyst@test.com must not appear even if present in the DB."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@admin.com", "username": "admin", "password": "admin12345678"},
    )
    await client.post(
        "/api/v1/auth/register",
        json={"email": "e2e_analyst@test.com", "username": "e2e_analyst", "password": "StrongPassword123!"},
    )
    resp = await client.get("/api/v1/auth/demo-users")
    data = resp.json()

    assert all(u["email"] != "e2e_analyst@test.com" for u in data)
    assert len(data) == 1
    assert data[0]["email"] == "admin@admin.com"


@pytest.mark.asyncio
async def test_demo_users_admin_schema(client: AsyncClient):
    """Admin demo entry contains exactly the expected fields with password."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@admin.com", "username": "admin", "password": "admin12345678"},
    )
    resp = await client.get("/api/v1/auth/demo-users")
    data = resp.json()
    assert len(data) == 1
    keys = set(data[0].keys())
    assert keys == {"email", "role", "has_demo_password", "demo_password"}
    assert data[0]["role"] == "admin"
    assert data[0]["has_demo_password"] is True
    assert data[0]["demo_password"] == "admin12345678"
