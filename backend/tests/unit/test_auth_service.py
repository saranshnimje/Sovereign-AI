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


# ------------------------------------------------------------------
# get_demo_users
# ------------------------------------------------------------------

async def _add_user(db, email: str, username: str, role: str, is_active: bool = True):
    from models.user import User
    user = User(
        email=email,
        username=username,
        password_hash="$2b$12$fakehash",
        role=role,
        is_active=is_active,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.mark.asyncio
async def test_get_demo_users_empty(db):
    """No users → empty list."""
    service = AuthService(db)
    result = await service.get_demo_users()
    assert result == []


@pytest.mark.asyncio
async def test_get_demo_users_returns_only_admin(db):
    """Only admin-role users are returned; viewers/analysts are excluded."""
    service = AuthService(db)
    await _add_user(db, "admin@test.com", "admin1", "admin")
    await _add_user(db, "viewer@test.com", "viewer1", "viewer")
    await _add_user(db, "analyst@test.com", "analyst1", "analyst")
    result = await service.get_demo_users()

    assert len(result) == 1
    assert result[0].email == "admin@test.com"
    assert result[0].role == "admin"


@pytest.mark.asyncio
async def test_get_demo_users_inactive_admin_excluded(db):
    """Inactive admin users are not returned."""
    service = AuthService(db)
    await _add_user(db, "admin@test.com", "admin1", "admin", is_active=False)
    result = await service.get_demo_users()
    assert result == []


@pytest.mark.asyncio
async def test_get_demo_users_admin_not_in_demo_credentials(db):
    """Admin NOT in DEMO_CREDENTIALS has has_demo_password=False."""
    service = AuthService(db)
    await _add_user(db, "other-admin@test.com", "otheradmin", "admin")
    result = await service.get_demo_users()
    assert len(result) == 1
    assert result[0].has_demo_password is False
    assert result[0].demo_password is None


@pytest.mark.asyncio
async def test_get_demo_users_admin_demo_password(db):
    """admin@admin.com is the configured demo credential → password shown."""
    service = AuthService(db)
    await _add_user(db, "admin@admin.com", "admin", "admin")
    result = await service.get_demo_users()

    assert len(result) == 1
    assert result[0].email == "admin@admin.com"
    assert result[0].role == "admin"
    assert result[0].has_demo_password is True
    assert result[0].demo_password == "admin12345678"


@pytest.mark.asyncio
async def test_get_demo_users_e2e_analyst_not_returned(db):
    """e2e_analyst@test.com must never be returned."""
    service = AuthService(db)
    await _add_user(db, "admin@admin.com", "admin", "admin")
    # The old analyst demo user still exists in an unclean DB
    await _add_user(db, "e2e_analyst@test.com", "e2e_analyst", "analyst")
    result = await service.get_demo_users()

    assert len(result) == 1
    assert result[0].email == "admin@admin.com"
    assert all(u.email != "e2e_analyst@test.com" for u in result)


@pytest.mark.asyncio
async def test_get_demo_users_schema_fields(db):
    """Each entry contains exactly email, role, has_demo_password, demo_password."""
    service = AuthService(db)
    await _add_user(db, "admin@test.com", "admin1", "admin")
    result = await service.get_demo_users()
    entry = result[0]
    assert set(entry.model_dump().keys()) == {"email", "role", "has_demo_password", "demo_password"}
