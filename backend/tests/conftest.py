"""
Shared pytest fixtures for unit and integration tests.
All tests use an in-memory SQLite database — no persistent state between runs.
"""
import os

# Rate limiting is disabled for the general suite so integration tests can
# hammer endpoints freely; test_rate_limit.py re-enables it explicitly.
os.environ.setdefault("RATE_LIMIT_ENABLED", "false")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import database
from database import Base, get_db
from main import app


# ------------------------------------------------------------------
# Tool-registry state reset (the registry is a module-level singleton;
# integration tests that disable tools must not leak into other tests)
# ------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_tool_registry_state():
    from tools.registry import get_registry

    def _enable_all():
        reg = get_registry()
        for tool in reg.list_all():
            tool.enabled = True

    _enable_all()
    yield
    _enable_all()


# ------------------------------------------------------------------
# In-memory DB fixture
# ------------------------------------------------------------------
@pytest_asyncio.fixture
async def db():
    """Fresh in-memory SQLite session for each test."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        # Register all models
        import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Monkeypatch database.AsyncSessionLocal so that send_agent_message
    # (and any other endpoint that creates its own session) uses the
    # test's in-memory engine instead of the file-based one.
    original_factory = database.AsyncSessionLocal
    database.AsyncSessionLocal = session_factory

    async with session_factory() as session:
        yield session

    database.AsyncSessionLocal = original_factory
    await engine.dispose()


# ------------------------------------------------------------------
# Test HTTP client (overrides DB dependency)
# ------------------------------------------------------------------
@pytest_asyncio.fixture
async def client(db: AsyncSession):
    """HTTPX async client pointing at the FastAPI app with an in-memory DB."""

    async def _override_db():
        yield db

    app.dependency_overrides[get_db] = _override_db

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as c:
        yield c

    app.dependency_overrides.clear()


# ------------------------------------------------------------------
# Helper: register + login, return auth client
# ------------------------------------------------------------------
@pytest_asyncio.fixture
async def auth_client(client: AsyncClient):
    """Client pre-authenticated as a viewer (first user → promoted to admin)."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@test.com", "username": "testadmin", "password": "StrongPassword123!"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "StrongPassword123!"},
    )
    token = resp.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}"})
    return client
