"""
Test configuration and fixtures.

These tests are designed to run without a real database.
Integration tests that need DB use an in-memory SQLite database (via aiosqlite).
"""
import asyncio
import uuid
from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import hash_password, create_access_token
from app.main import app
from app.models.tenant import Tenant, TenantConfig, ChannelConfig
from app.models.user import User, UserRole
from app.models.customer import Customer
from app.models.conversation import Conversation
from app.models.ticket import Ticket

# Use in-memory SQLite for tests (no real DB needed)
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop_policy():
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    TestSessionLocal = async_sessionmaker(db_engine, class_=AsyncSession, expire_on_commit=False)
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


# ── Helper fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def tenant_a(db_session: AsyncSession) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), name="Tenant A", slug="tenant-a", is_active=True, plan="starter")
    db_session.add(tenant)
    db_session.add(TenantConfig(tenant_id=tenant.id))
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def tenant_b(db_session: AsyncSession) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), name="Tenant B", slug="tenant-b", is_active=True, plan="starter")
    db_session.add(tenant)
    db_session.add(TenantConfig(tenant_id=tenant.id))
    await db_session.commit()
    await db_session.refresh(tenant)
    return tenant


@pytest_asyncio.fixture
async def owner_user_a(db_session: AsyncSession, tenant_a: Tenant) -> User:
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="owner@tenant-a.com",
        full_name="Owner A",
        role=UserRole.owner,
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def agent_user_a(db_session: AsyncSession, tenant_a: Tenant) -> User:
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_a.id,
        email="agent@tenant-a.com",
        full_name="Agent A",
        role=UserRole.agent,
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def owner_user_b(db_session: AsyncSession, tenant_b: Tenant) -> User:
    user = User(
        id=uuid.uuid4(),
        tenant_id=tenant_b.id,
        email="owner@tenant-b.com",
        full_name="Owner B",
        role=UserRole.owner,
        hashed_password=hash_password("Password123!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


def make_token(user: User) -> str:
    return create_access_token(
        {"sub": str(user.id), "tenant_id": str(user.tenant_id), "role": user.role.value}
    )


@pytest.fixture
def auth_headers_owner_a(owner_user_a: User) -> dict:
    return {"Authorization": f"Bearer {make_token(owner_user_a)}"}


@pytest.fixture
def auth_headers_agent_a(agent_user_a: User) -> dict:
    return {"Authorization": f"Bearer {make_token(agent_user_a)}"}


@pytest.fixture
def auth_headers_owner_b(owner_user_b: User) -> dict:
    return {"Authorization": f"Bearer {make_token(owner_user_b)}"}
