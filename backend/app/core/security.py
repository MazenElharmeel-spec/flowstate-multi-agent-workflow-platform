"""Security, authentication, and Role-Based Access Control (RBAC)."""

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

import jwt
from passlib.context import CryptContext
from pydantic import BaseModel

from backend.app.core.config import get_settings

settings = get_settings()

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    APPROVER = "approver"
    VIEWER = "viewer"


# Role permissions hierarchy: higher roles inherit capabilities
ROLE_HIERARCHY: dict[Role, set[str]] = {
    Role.ADMIN: {"read", "execute", "cancel", "replay", "approve", "admin"},
    Role.OPERATOR: {"read", "execute", "cancel", "replay"},
    Role.APPROVER: {"read", "approve"},
    Role.VIEWER: {"read"},
}


class TokenPayload(BaseModel):
    sub: str  # User ID or Email
    role: Role
    exp: datetime


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def has_permission(user_role: Role, required_permission: str) -> bool:
    """Check if the user role grants the specified permission."""
    allowed = ROLE_HIERARCHY.get(user_role, set())
    return required_permission in allowed
