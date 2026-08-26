"""
Authentication service — registration, login, JWT issuance, token refresh/revocation.
All passwords hashed with bcrypt (cost=12). JWTs signed with HS256.
"""
import hashlib
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import HTTPException, Request
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from models.user import RefreshToken, User
from schemas.auth import LoginRequest, RegisterRequest, TokenResponse, UserResponse

# Common passwords blocklist (top subset — expand for production)
COMMON_PASSWORDS = {
    "password123456",
    "qwerty123456789",
    "123456789012",
    "password1234",
    "iloveyou1234",
    "sunshine12345",
    "princess12345",
    "welcome123456",
    "dragon123456!!",
    "master123456!!",
}


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.settings = get_settings()
        self.pwd_ctx = CryptContext(schemes=["bcrypt"], bcrypt__rounds=12, deprecated="auto")

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def register(self, data: RegisterRequest, first_admin: bool = False) -> User:
        """Create a new user. first_admin=True promotes role to 'admin'."""
        # Duplicate check
        result = await self.db.execute(
            select(User).where(
                (User.email == data.email) | (User.username == data.username)
            )
        )
        if result.scalar_one_or_none():
            raise HTTPException(400, "Email or username already registered")

        # Common password check
        if data.password.lower() in COMMON_PASSWORDS:
            raise HTTPException(400, "Password is too common — choose a stronger one")

        user = User(
            email=data.email,
            username=data.username,
            password_hash=self.pwd_ctx.hash(data.password),
            role="admin" if first_admin else "viewer",
            is_active=True,
        )
        self.db.add(user)
        await self.db.flush()  # get ID without committing
        return user

    # ------------------------------------------------------------------
    # Login
    # ------------------------------------------------------------------
    async def login(
        self, data: LoginRequest, request: Request | None = None
    ) -> tuple[TokenResponse, str]:
        """
        Authenticate user. Returns (TokenResponse, refresh_token_plain_text).
        The refresh token plain text must be set as an httpOnly cookie by the router.
        """
        user = await self._get_by_email(data.email)
        if not user or not self.pwd_ctx.verify(data.password, user.password_hash):
            raise HTTPException(401, "Invalid email or password")
        if not user.is_active:
            raise HTTPException(403, "Account is disabled — contact your administrator")

        user.last_login = datetime.now(timezone.utc)
        await self.db.flush()

        access_token = self._create_access_token(user.id)
        refresh_plain, refresh_hash = self._create_refresh_pair()

        expires = datetime.now(timezone.utc) + timedelta(
            days=self.settings.jwt_refresh_ttl_days
        )
        rt = RefreshToken(
            user_id=user.id,
            token_hash=refresh_hash,
            expires_at=expires,
        )
        self.db.add(rt)
        await self.db.flush()

        token_resp = TokenResponse(
            access_token=access_token,
            expires_in=self.settings.jwt_access_ttl_min * 60,
        )
        return token_resp, refresh_plain

    # ------------------------------------------------------------------
    # Token verification
    # ------------------------------------------------------------------
    async def verify_token(self, token: str) -> User:
        """Decode and validate a JWT access token. Returns the User."""
        try:
            payload = jwt.decode(
                token,
                self.settings.secret_key,
                algorithms=[self.settings.jwt_algorithm],
            )
        except jwt.ExpiredSignatureError:
            raise HTTPException(401, "Token has expired")
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Invalid token")

        if payload.get("type") != "access":
            raise HTTPException(401, "Wrong token type")

        user = await self._get_by_id(payload["sub"])
        if not user or not user.is_active:
            raise HTTPException(401, "User not found or inactive")
        return user

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------
    async def refresh(self, refresh_plain: str) -> tuple[TokenResponse, str]:
        """Rotate refresh token. Returns new (TokenResponse, new_refresh_plain)."""
        token_hash = self._hash_token(refresh_plain)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked == False,  # noqa: E712
            )
        )
        rt = result.scalar_one_or_none()
        if not rt:
            raise HTTPException(401, "Invalid or revoked refresh token")

        now = datetime.now(timezone.utc)
        # Ensure the expires_at is timezone-aware for comparison
        expires_at = rt.expires_at
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)

        if expires_at < now:
            raise HTTPException(401, "Refresh token has expired")

        # Revoke old token
        rt.revoked = True
        await self.db.flush()

        user = await self._get_by_id(rt.user_id)
        if not user or not user.is_active:
            raise HTTPException(401, "User not found or inactive")

        access_token = self._create_access_token(user.id)
        new_plain, new_hash = self._create_refresh_pair()
        new_expires = now + timedelta(days=self.settings.jwt_refresh_ttl_days)
        new_rt = RefreshToken(
            user_id=user.id,
            token_hash=new_hash,
            expires_at=new_expires,
        )
        self.db.add(new_rt)
        await self.db.flush()

        token_resp = TokenResponse(
            access_token=access_token,
            expires_in=self.settings.jwt_access_ttl_min * 60,
        )
        return token_resp, new_plain

    # ------------------------------------------------------------------
    # Logout
    # ------------------------------------------------------------------
    async def logout(self, refresh_plain: str | None) -> None:
        """Revoke refresh token if provided."""
        if not refresh_plain:
            return
        token_hash = self._hash_token(refresh_plain)
        result = await self.db.execute(
            select(RefreshToken).where(RefreshToken.token_hash == token_hash)
        )
        rt = result.scalar_one_or_none()
        if rt:
            rt.revoked = True
            await self.db.flush()

    # ------------------------------------------------------------------
    # Admin helpers
    # ------------------------------------------------------------------
    async def count_users(self) -> int:
        """Return total number of users — used for first-run detection."""
        from sqlalchemy import func
        result = await self.db.execute(select(func.count()).select_from(User))
        return result.scalar_one()

    async def get_all_users(self) -> list[User]:
        result = await self.db.execute(select(User).order_by(User.created_at))
        return list(result.scalars().all())

    async def get_user_by_id(self, user_id: str) -> User | None:
        return await self._get_by_id(user_id)

    async def update_user(self, user_id: str, **kwargs) -> User:
        user = await self._get_by_id(user_id)
        if not user:
            raise HTTPException(404, "User not found")
        for key, val in kwargs.items():
            if val is not None and hasattr(user, key):
                setattr(user, key, val)
        await self.db.flush()
        return user

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------
    def _create_access_token(self, user_id: str) -> str:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=self.settings.jwt_access_ttl_min
        )
        payload = {"sub": user_id, "exp": expire, "type": "access"}
        return jwt.encode(payload, self.settings.secret_key, algorithm=self.settings.jwt_algorithm)

    def _create_refresh_pair(self) -> tuple[str, str]:
        """Return (plain_text_token, sha256_hash_of_token)."""
        import secrets
        plain = secrets.token_urlsafe(64)
        return plain, self._hash_token(plain)

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def _get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def _get_by_id(self, user_id: str) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
