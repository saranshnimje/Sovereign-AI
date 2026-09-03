"""
Authentication router — register, login, refresh, logout, me.
"""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.user import User
from schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse, UserUpdate
from services.audit_service import AuditService
from services.auth_service import AuthService
from utils.rate_limit import auth_rate_limit

router = APIRouter(tags=["auth"])

_REFRESH_COOKIE = "sovereign_refresh"
_COOKIE_OPTS = dict(httponly=True, samesite="none", secure=True)


# ------------------------------------------------------------------
# Register (first user gets admin role)
# ------------------------------------------------------------------
@router.post("/register", response_model=UserResponse, status_code=201)
async def register(
    data: RegisterRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit),
):
    service = AuthService(db)
    first_admin = await service.count_users() == 0
    user = await service.register(data, first_admin=first_admin)

    audit = AuditService(db)
    await audit.log("auth", "user.register", "success", user_id=user.id, request=request)

    return UserResponse.model_validate(user)


# ------------------------------------------------------------------
# Login
# ------------------------------------------------------------------
@router.post("/login", response_model=TokenResponse)
async def login(
    data: LoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(auth_rate_limit),
):
    service = AuthService(db)
    try:
        token_resp, refresh_plain = await service.login(data, request=request)
    except HTTPException as exc:
        audit = AuditService(db)
        await audit.log(
            "auth", "auth.login.failure", "failure",
            metadata={"email": data.email},
            request=request,
        )
        raise

    # Fetch user for audit log
    user = await service.verify_token(token_resp.access_token)

    audit = AuditService(db)
    await audit.log("auth", "auth.login.success", "success", user_id=user.id, request=request)

    response.set_cookie(
        _REFRESH_COOKIE, refresh_plain,
        max_age=7 * 24 * 3600,
        **_COOKIE_OPTS,
    )
    return token_resp


# ------------------------------------------------------------------
# Refresh
# ------------------------------------------------------------------
@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: AsyncSession = Depends(get_db),
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
    _rl: None = Depends(auth_rate_limit),
):
    if not refresh_token:
        raise HTTPException(401, "No refresh token provided")
    service = AuthService(db)
    token_resp, new_plain = await service.refresh(refresh_token)
    response.set_cookie(
        _REFRESH_COOKIE, new_plain,
        max_age=7 * 24 * 3600,
        **_COOKIE_OPTS,
    )
    return token_resp


# ------------------------------------------------------------------
# Logout
# ------------------------------------------------------------------
@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE),
):
    service = AuthService(db)
    await service.logout(refresh_token)

    audit = AuditService(db)
    await audit.log("auth", "auth.logout", "success", user_id=current_user.id, request=request)

    response.delete_cookie(_REFRESH_COOKIE)
    return {"message": "Logged out"}


# ------------------------------------------------------------------
# Current user
# ------------------------------------------------------------------
@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)


# ------------------------------------------------------------------
# Admin: list all users / update user
# ------------------------------------------------------------------
@router.get("/users", response_model=list[UserResponse])
async def list_users(
    _admin=Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    service = AuthService(db)
    users = await service.get_all_users()
    return [UserResponse.model_validate(u) for u in users]


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    data: UserUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    service = AuthService(db)
    user = await service.update_user(
        user_id,
        role=data.role,
        is_active=data.is_active,
        must_change_password=data.must_change_password,
    )
    audit = AuditService(db)
    await audit.log(
        "auth", "user.updated", "success",
        user_id=admin.id,
        resource_type="user",
        resource_id=user_id,
        request=request,
    )
    return UserResponse.model_validate(user)


# ------------------------------------------------------------------
# First-run detection
# ------------------------------------------------------------------
@router.get("/setup-status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    """Returns whether the system needs first-run setup (no users yet)."""
    service = AuthService(db)
    count = await service.count_users()
    return {"setup_required": count == 0}
