"""
Async SQLAlchemy engine and session factory.

Supports both SQLite (local dev / Docker) and PostgreSQL (cloud deployment).
- SQLite: StaticPool, WAL mode, check_same_thread disabled.
- PostgreSQL: bounded pool sized for the dashboard's concurrent API requests.
"""
from datetime import datetime, timezone

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import DateTime, TypeDecorator

from config import get_settings


class UTCDateTime(TypeDecorator):
    """
    DateTime that ALWAYS returns timezone-aware UTC values on retrieval.

    SQLite stores datetimes as naive strings. This decorator attaches
    tzinfo=UTC on read so Pydantic serializes them with '+00:00' suffix,
    making the API contract explicitly timezone-aware.

    On write: strips tzinfo so PostgreSQL TIMESTAMP WITHOUT TIME ZONE works.
    """
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is not None and value.tzinfo is not None:
            return value.replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


settings = get_settings()

# Normalize PostgreSQL URL to use asyncpg driver
_db_url = settings.database_url
if _db_url.startswith("postgresql://"):
    _db_url = _db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

_is_postgres = _db_url.startswith("postgresql")


if _is_postgres:
    # Render serves several dashboard endpoints concurrently. SQLAlchemy's
    # defaults (5 connections + 10 overflow, 30s wait) are too restrictive
    # for that burst and can make the frontend retry/reload while requests
    # are stuck waiting for a connection. Keep the pool bounded while giving
    # the app enough headroom and fail fast if the database is genuinely full.
    engine = create_async_engine(
        _db_url,
        echo=False,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
        pool_timeout=10,
        pool_recycle=1800,
        pool_use_lifo=True,
    )
else:
    from sqlalchemy.pool import StaticPool
    engine = create_async_engine(
        _db_url,
        echo=False,
        connect_args={"check_same_thread": False},
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
    """Create all tables on startup. SQLite pragmas applied only for SQLite."""
    async with engine.begin() as conn:
        if not _is_postgres:
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
