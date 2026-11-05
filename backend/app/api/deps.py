"""Authentication and authorization dependencies for FastAPI endpoints."""

from collections.abc import Callable
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.security import Role, decode_access_token, has_permission
from backend.app.db.models import User
from backend.app.db.session import get_db

__all__ = ["get_current_user", "require_role", "get_db"]

security_scheme = HTTPBearer(auto_error=True)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(security_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    token = credentials.credentials
    try:
        payload = decode_access_token(token)
        user_id: str | None = payload.get("sub")
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload: missing sub",
                headers={"WWW-Authenticate": "Bearer"},
            )
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token validation failed: {str(exc)}",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    return user


def require_role(required_role: Role) -> Callable[..., Any]:
    """Dependency enforcing that the authenticated user possesses the required role privilege."""

    async def role_checker(
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        user_role = Role(current_user.role)
        # Check permissions via the role hierarchy
        needed_permission = {
            Role.ADMIN: "admin",
            Role.OPERATOR: "execute",
            Role.APPROVER: "approve",
            Role.VIEWER: "read",
        }.get(required_role, "read")

        if not has_permission(user_role, needed_permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Operation requires '{required_role.value}' role privileges",
            )
        return current_user

    return role_checker
