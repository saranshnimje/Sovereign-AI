"""
Startup migration helper for Sovereign AI Workbench.

Handles the case where the database was bootstrapped via init_db()
(create_all) rather than Alembic, so some ALTER TABLE migrations were
never applied — specifically columns added to agent_runs in migrations
6 and 7.

Strategy: run targeted, idempotent DDL before init_db() to add any
missing columns/tables, then stamp Alembic to HEAD so future migrations
work correctly.
"""
import structlog
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger()

# Columns that must exist on agent_runs (added by migrations 6 & 7)
_AGENT_RUNS_COLUMNS = [
    ("goal_json", "TEXT"),
    ("current_step_id", "INTEGER"),
    ("cancel_requested", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("parent_run_id", "VARCHAR(36)"),
    ("context_summary", "TEXT"),
    ("final_verification_json", "TEXT"),
    ("failure_reason", "TEXT"),
    ("todo_json", "TEXT"),
]


async def run_startup_migrations(engine: AsyncEngine, is_postgres: bool) -> None:
    """
    Idempotent migration fixup. Safe to run on every startup.

    1. Add any missing columns to agent_runs
    2. Create agent_events table if missing
    3. Stamp alembic_version to HEAD so future migrations work
    """
    try:
        async with engine.begin() as conn:
            # --- 1. Add missing agent_runs columns ---
            for col_name, col_ddl in _AGENT_RUNS_COLUMNS:
                if not await _column_exists(conn, "agent_runs", col_name, is_postgres):
                    ddl = f"ALTER TABLE agent_runs ADD COLUMN {col_name} {col_ddl}"
                    await conn.execute(text(ddl))
                    logger.info(f"Added column agent_runs.{col_name}")

            # --- 2. Create agent_events table if missing ---
            if not await _table_exists(conn, "agent_events", is_postgres):
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS agent_events (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        run_id VARCHAR(36) NOT NULL,
                        "sequence" INTEGER NOT NULL,
                        event_type VARCHAR(50) NOT NULL,
                        payload_json TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT NOW()
                    )
                """))
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_agent_events_run_seq "
                    "ON agent_events (run_id, \"sequence\")"
                ))
                # Add FK constraint if missing
                try:
                    await conn.execute(text(
                        "ALTER TABLE agent_events ADD CONSTRAINT "
                        "fk_agent_events_run_id FOREIGN KEY (run_id) "
                        "REFERENCES agent_runs(id) ON DELETE CASCADE"
                    ))
                except Exception:
                    pass  # FK constraint may already exist
                logger.info("Created agent_events table")

            # --- 3. Stamp alembic_version to HEAD ---
            await _stamp_alembic_head(conn, is_postgres)

    except Exception as exc:
        logger.warning("Startup migration fixup failed", error=str(exc))


async def _column_exists(conn, table: str, column: str, is_postgres: bool) -> bool:
    if is_postgres:
        result = await conn.execute(text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col)"
        ), {"table": table, "col": column})
        return result.scalar()
    else:
        result = await conn.execute(text(f"PRAGMA table_info({table})"))
        return any(row[1] == column for row in result)


async def _table_exists(conn, table: str, is_postgres: bool) -> bool:
    if is_postgres:
        result = await conn.execute(text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables "
            "WHERE table_name = :table)"
        ), {"table": table})
        return result.scalar()
    else:
        result = await conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
        ), {"t": table})
        return result.fetchone() is not None


async def _stamp_alembic_head(conn, is_postgres: bool) -> None:
    """Create alembic_version table if needed and stamp to HEAD revision."""
    if is_postgres:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            )
        """))
        # Check if already stamped
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        current = result.scalar()
        if current != "a1b2c3d4e5f7":
            await conn.execute(text("DELETE FROM alembic_version"))
            await conn.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES (:v)"
            ), {"v": "a1b2c3d4e5f7"})
            logger.info("Stamped alembic_version to HEAD (a1b2c3d4e5f7)")
        else:
            logger.info("Alembic already at HEAD")
    else:
        await conn.execute(text("""
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL PRIMARY KEY
            )
        """))
        result = await conn.execute(text("SELECT version_num FROM alembic_version"))
        current = result.scalar()
        if current != "a1b2c3d4e5f7":
            await conn.execute(text("DELETE FROM alembic_version"))
            await conn.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES (:v)"
            ), {"v": "a1b2c3d4e5f7"})
            logger.info("Stamped alembic_version to HEAD (a1b2c3d4e5f7)")
