"""Integration tests for authentication endpoints."""
import pytest


@pytest.mark.asyncio
async def test_login_success(client, tenant_a, owner_user_a):
    response = await client.post("/api/v1/auth/login", json={
        "email": "owner@tenant-a.com",
        "password": "Password123!",
        "tenant_slug": "tenant-a",
    })
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert "user" in data
    assert data["user"]["email"] == "owner@tenant-a.com"


@pytest.mark.asyncio
async def test_login_wrong_password(client, tenant_a, owner_user_a):
    response = await client.post("/api/v1/auth/login", json={
        "email": "owner@tenant-a.com",
        "password": "WrongPassword!",
        "tenant_slug": "tenant-a",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_tenant(client, tenant_a, owner_user_a):
    response = await client.post("/api/v1/auth/login", json={
        "email": "owner@tenant-a.com",
        "password": "Password123!",
        "tenant_slug": "nonexistent-tenant",
    })
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me(client, owner_user_a, auth_headers_owner_a):
    response = await client.get("/api/v1/auth/me", headers=auth_headers_owner_a)
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "owner@tenant-a.com"
    assert data["role"] == "owner"


@pytest.mark.asyncio
async def test_get_me_no_token(client):
    response = await client.get("/api/v1/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_me_invalid_token(client):
    response = await client.get("/api/v1/auth/me", headers={"Authorization": "Bearer invalid.token.here"})
    assert response.status_code == 401
