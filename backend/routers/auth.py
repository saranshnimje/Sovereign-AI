"""
Authentication router — register, login, refresh, logout, me.
"""
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from dependencies import get_current_user, require_role
from models.user import User
from schemas.auth import DemoUserResponse, LoginRequest, RegisterRequest, TokenResponse, UserResponse, UserUpdate
from services.audit_service import AuditService
from services.auth_service import AuthService
from utils.rate_limit import auth_rate_limit

router = APIRouter(tags=["auth"])
_REFRESH_COOKIE = "sovereign_refresh"
_COOKIE_OPTS = dict(httponly=True, samesite="none", secure=True)

@router.post("/register", response_model=UserResponse, status_code=201)
async def register(data: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db), _rl: None = Depends(auth_rate_limit)):
    service = AuthService(db)
    user = await service.register(data, first_admin=await service.count_users() == 0)
    await AuditService(db).log("auth", "user.register", "success", user_id=user.id, request=request)
    return UserResponse.model_validate(user)

@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, request: Request, response: Response, db: AsyncSession = Depends(get_db), _rl: None = Depends(auth_rate_limit)):
    service = AuthService(db)
    try:
        token_resp, refresh_plain = await service.login(data, request=request)
    except HTTPException:
        await AuditService(db).log("auth", "auth.login.failure", "failure", metadata={"email": data.email}, request=request)
        raise
    user = await service.verify_token(token_resp.access_token)
    await AuditService(db).log("auth", "auth.login.success", "success", user_id=user.id, request=request)
    response.set_cookie(_REFRESH_COOKIE, refresh_plain, max_age=7 * 24 * 3600, **_COOKIE_OPTS)
    return token_resp

@router.post("/refresh", response_model=TokenResponse)
async def refresh(response: Response, db: AsyncSession = Depends(get_db), refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE), _rl: None = Depends(auth_rate_limit)):
    if not refresh_token:
        raise HTTPException(401, "No refresh token provided")
    token_resp, new_plain = await AuthService(db).refresh(refresh_token)
    response.set_cookie(_REFRESH_COOKIE, new_plain, max_age=7 * 24 * 3600, **_COOKIE_OPTS)
    return token_resp

@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user), refresh_token: str | None = Cookie(default=None, alias=_REFRESH_COOKIE)):
    await AuthService(db).logout(refresh_token)
    await AuditService(db).log("auth", "auth.logout", "success", user_id=current_user.id, request=request)
    response.delete_cookie(_REFRESH_COOKIE)
    return {"message": "Logged out"}

@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return UserResponse.model_validate(current_user)

# ------------------------------------------------------------------
# Admin user management — all endpoints are server-side admin protected.
# ------------------------------------------------------------------
@router.get("/users", response_model=list[UserResponse])
async def list_users(_admin=Depends(require_role("admin")), db: AsyncSession = Depends(get_db)):
    return [UserResponse.model_validate(u) for u in await AuthService(db).get_all_users()]

@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(user_id: str, data: UserUpdate, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_role("admin"))):
    service = AuthService(db)
    user = await service.update_user(user_id, role=data.role, is_active=data.is_active, must_change_password=data.must_change_password)
    await AuditService(db).log("auth", "user.updated", "success", user_id=admin.id, resource_type="user", resource_id=user_id, request=request)
    return UserResponse.model_validate(user)

@router.delete("/users/{user_id}", status_code=200)
async def delete_user(user_id: str, request: Request, db: AsyncSession = Depends(get_db), admin: User = Depends(require_role("admin"))):
    await AuthService(db).delete_user(user_id, admin.id)
    await AuditService(db).log("auth", "user.deleted", "success", user_id=admin.id, resource_type="user", resource_id=user_id, request=request)
    return {"message": "User deleted", "id": user_id}

@router.get("/setup-status")
async def setup_status(db: AsyncSession = Depends(get_db)):
    return {"setup_required": await AuthService(db).count_users() == 0}

@router.get("/demo-users", response_model=list[DemoUserResponse])
async def demo_users(db: AsyncSession = Depends(get_db)):
    return await AuthService(db).get_demo_users()
