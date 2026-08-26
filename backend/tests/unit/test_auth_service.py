"""Unit tests for AuthService."""
import pytest
import pytest_asyncio
from fastapi import HTTPException

from schemas.auth import LoginRequest, RegisterRequest
from services.auth_service import AuthService


@pytest.mark.asyncio
async def test_register_creates_first_admin(db):
    service = AuthService(db)
    user = await service.register(
        RegisterRequest(email="a@test.com", username="admin1", password="StrongPass123!"),
        first_admin=True,
    )
    assert user.id is not None
    assert user.email == "a@test.com"
    assert user.role == "admin"
    assert user.is_active is True
    # Password must be hashed
    assert user.password_hash != "StrongPass123!"
    assert user.password_hash.startswith("$2b$")


@pytest.mark.asyncio
async def test_register_default_viewer_role(db):
    service = AuthService(db)
    user = await service.register(
        RegisterRequest(email="v@test.com", username="viewer1", password="StrongPass123!"),
        first_admin=False,
    )
    assert user.role == "viewer"


@pytest.mark.asyncio
async def test_register_duplicate_email_raises(db):
    service = AuthService(db)
    data = RegisterRequest(email="dup@test.com", username="dup1", password="StrongPass123!")
    await service.register(data)
    await db.flush()

    with pytest.raises(HTTPException) as exc:
        await service.register(
            RegisterRequest(email="dup@test.com", username="dup2", password="StrongPass123!")
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_register_duplicate_username_raises(db):
    service = AuthService(db)
    await service.register(
        RegisterRequest(email="a@test.com", username="samename", password="StrongPass123!")
    )
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await service.register(
            RegisterRequest(email="b@test.com", username="samename", password="StrongPass123!")
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_login_success(db):
    service = AuthService(db)
    await service.register(
        RegisterRequest(email="login@test.com", username="loginuser", password="StrongPass123!")
    )
    await db.flush()

    token_resp, refresh = await service.login(
        LoginRequest(email="login@test.com", password="StrongPass123!")
    )
    assert token_resp.access_token
    assert token_resp.token_type == "bearer"
    assert token_resp.expires_in > 0
    assert refresh  # refresh token plain text returned


@pytest.mark.asyncio
async def test_login_wrong_password_raises(db):
    service = AuthService(db)
    await service.register(
        RegisterRequest(email="wp@test.com", username="wpuser", password="StrongPass123!")
    )
    await db.flush()
    with pytest.raises(HTTPException) as exc:
        await service.login(LoginRequest(email="wp@test.com", password="WrongPass!!!"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_login_nonexistent_email_raises(db):
    service = AuthService(db)
    with pytest.raises(HTTPException) as exc:
        await service.login(LoginRequest(email="ghost@test.com", password="StrongPass123!"))
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_verify_valid_token(db):
    service = AuthService(db)
    user = await service.register(
        RegisterRequest(email="vt@test.com", username="vtuser", password="StrongPass123!")
    )
    await db.flush()
    token_resp, _ = await service.login(
        LoginRequest(email="vt@test.com", password="StrongPass123!")
    )
    verified = await service.verify_token(token_resp.access_token)
    assert verified.id == user.id


@pytest.mark.asyncio
async def test_verify_invalid_token_raises(db):
    service = AuthService(db)
    with pytest.raises(HTTPException) as exc:
        await service.verify_token("this.is.not.a.valid.token")
    assert exc.value.status_code == 401


@pytest.mark.asyncio
async def test_count_users(db):
    service = AuthService(db)
    assert await service.count_users() == 0
    await service.register(
        RegisterRequest(email="c@test.com", username="countuser", password="StrongPass123!")
    )
    await db.flush()
    assert await service.count_users() == 1
