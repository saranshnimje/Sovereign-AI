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
