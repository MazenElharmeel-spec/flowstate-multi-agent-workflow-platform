"""Tests for health endpoints, authentication, and RBAC."""

import pytest
from httpx import AsyncClient

from backend.app.core.security import Role, has_permission


@pytest.mark.asyncio
async def test_healthz(client: AsyncClient) -> None:
    response = await client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "X-Trace-Id" in response.headers
    assert "X-Response-Time-Ms" in response.headers


@pytest.mark.asyncio
async def test_readyz(client: AsyncClient) -> None:
    response = await client.get("/readyz")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["checks"]["database"] == "ok"


@pytest.mark.asyncio
async def test_user_registration_and_login(client: AsyncClient) -> None:
    # Register an admin user
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "SecretPassword123!", "role": "admin"},
    )
    assert reg_res.status_code == 201
    user_data = reg_res.json()
    assert user_data["email"] == "admin@example.com"
    assert user_data["role"] == "admin"
    assert "hashed_password" not in user_data

    # Attempt duplicate registration
    dup_res = await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@example.com", "password": "AnotherPassword", "role": "viewer"},
    )
    assert dup_res.status_code == 400

    # Login with wrong credentials
    bad_login = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "WrongPassword"},
    )
    assert bad_login.status_code == 401

    # Login with valid credentials
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "SecretPassword123!"},
    )
    assert login_res.status_code == 200
    token_data = login_res.json()
    assert "access_token" in token_data
    assert token_data["role"] == "admin"

    # Access /auth/me with Bearer token
    token = token_data["access_token"]
    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == "admin@example.com"
    assert me_data["role"] == "admin"


def test_rbac_permissions() -> None:
    # Admin has all permissions
    assert has_permission(Role.ADMIN, "read")
    assert has_permission(Role.ADMIN, "execute")
    assert has_permission(Role.ADMIN, "approve")
    assert has_permission(Role.ADMIN, "admin")

    # Operator has read, execute, cancel, replay
    assert has_permission(Role.OPERATOR, "read")
    assert has_permission(Role.OPERATOR, "execute")
    assert not has_permission(Role.OPERATOR, "approve")
    assert not has_permission(Role.OPERATOR, "admin")

    # Approver has read, approve
    assert has_permission(Role.APPROVER, "read")
    assert has_permission(Role.APPROVER, "approve")
    assert not has_permission(Role.APPROVER, "execute")

    # Viewer has only read
    assert has_permission(Role.VIEWER, "read")
    assert not has_permission(Role.VIEWER, "execute")
    assert not has_permission(Role.VIEWER, "approve")
