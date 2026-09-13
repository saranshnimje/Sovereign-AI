"""Pydantic schemas for auth endpoints."""
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def validate_username(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", v):
            raise ValueError(
                "Username must be 3–50 characters: letters, numbers, underscores only"
            )
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        if len(v) < 12:
            raise ValueError("Password must be at least 12 characters")
        return v


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int  # seconds


class UserResponse(BaseModel):
    id: str
    email: str
    username: str
    role: str
    is_active: bool
    must_change_password: bool
    last_login: datetime | None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class UserUpdate(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    must_change_password: bool | None = None

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str | None) -> str | None:
        if v is not None and v not in ("viewer", "analyst", "admin"):
            raise ValueError("Role must be viewer, analyst, or admin")
        return v


class DemoUserResponse(BaseModel):
    """A user entry shown on the login page's Demo Credentials section.

    Only verified, working demo passwords are included. Users whose
    password is not a configured demo credential will have
    ``has_demo_password=False`` and ``demo_password=None``.
    """

    email: str
    role: str
    has_demo_password: bool = False
    demo_password: str | None = None
