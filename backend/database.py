"""
Async SQLAlchemy engine and session factory.

SQLite concurrency strategy for the MVP:
- StaticPool: reuses a single underlying connection — serialises all writes
  and eliminates "database is locked" entirely at the application layer.
- WAL mode still improves read performance and is set at startup.
- For a prototype with ≤10 concurrent users on a single node, StaticPool is
  the correct and simplest solution. PostgreSQL can replace this for production.
"""
from datetime import datetime, timezone

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool
from sqlalchemy.types import DateTime, TypeDecorator

from config import get_settings


class UTCDateTime(TypeDecorator):
    """
    DateTime that ALWAYS returns timezone-aware UTC values on retrieval.

    SQLite stores datetimes as naive strings. This decorator attaches
    tzinfo=UTC on read so Pydantic serializes them with '+00:00' suffix,
    making the API contract explicitly timezone-aware.

    Existing data (already stored as UTC) requires no migration.
    """
    impl = DateTime
    cache_ok = True

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value

settings = get_settings()

engine = create_async_engine(
    settings.database_url,
    echo=False,
    connect_args={"check_same_thread": False},
    # StaticPool reuses a single underlying sqlite3 connection, which
    # completely eliminates write-lock contention at the SQLAlchemy level.
    poolclass=StaticPool,
)


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=True,
)


class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass


async def init_db() -> None:
    """Create all tables on startup and enable SQLite pragmas."""
    async with engine.begin() as conn:
        await conn.execute(text("PRAGMA journal_mode=WAL"))
        await conn.execute(text("PRAGMA foreign_keys=ON"))
        await conn.execute(text("PRAGMA synchronous=NORMAL"))
        import models  # noqa: F401
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:  # type: ignore[return]
    """FastAPI dependency — yields an async database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
