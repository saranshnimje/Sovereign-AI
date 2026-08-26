"""
Shared pytest fixtures for unit and integration tests.
All tests use an in-memory SQLite database — no persistent state between runs.
"""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database import Base, get_db
from main import app


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
    async with session_factory() as session:
        yield session

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
