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

# Columns that must exist on agent_runs (added by migrations 6, 7, and 8)
_AGENT_RUNS_COLUMNS = [
    ("goal_json", "TEXT"),
    ("current_step_id", "INTEGER"),
    ("cancel_requested", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("parent_run_id", "VARCHAR(36)"),
    ("context_summary", "TEXT"),
    ("final_verification_json", "TEXT"),
    ("failure_reason", "TEXT"),
    ("todo_json", "TEXT"),
    # Migration 8: conversation/message links + ASK_USER fields
    ("conversation_id", "VARCHAR(36)"),
    ("message_id", "VARCHAR(36)"),
    ("pending_question", "TEXT"),
    ("pending_options_json", "TEXT"),
    ("user_answer", "TEXT"),
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

            # --- 2. Create agent_events table if missing (PostgreSQL only) ---
            if is_postgres and not await _table_exists(conn, "agent_events", is_postgres):
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS agent_events (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        run_id VARCHAR(36) NOT NULL,
                        "sequence" INTEGER NOT NULL,
                        event_type VARCHAR(50) NOT NULL,
                        payload_json TEXT,
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                await conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_events_run_seq "
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
            elif is_postgres:
                # Ensure unique constraint exists (upgrade from non-unique index)
                try:
                    await conn.execute(text(
                        "DROP INDEX IF EXISTS idx_agent_events_run_seq"
                    ))
                    await conn.execute(text(
                        "CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_events_run_seq "
                        "ON agent_events (run_id, \"sequence\")"
                    ))
                except Exception:
                    pass  # Index may already be unique

            # --- 2b. Create artifacts table if missing (PostgreSQL only) ---
            if is_postgres and not await _table_exists(conn, "artifacts", is_postgres):
                await conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS artifacts (
                        id VARCHAR(36) NOT NULL PRIMARY KEY,
                        user_id VARCHAR(36) NOT NULL,
                        conversation_id VARCHAR(36),
                        run_id VARCHAR(36),
                        filename VARCHAR(255) NOT NULL,
                        relative_path VARCHAR(500) NOT NULL,
                        mime_type VARCHAR(100),
                        size_bytes INTEGER NOT NULL DEFAULT 0,
                        storage_key VARCHAR(500) NOT NULL,
                        checksum VARCHAR(64),
                        created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                        FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
                        FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE SET NULL
                    )
                """))
                for idx_col in ["user_id", "conversation_id", "run_id"]:
                    await conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_artifacts_{idx_col} "
                        f"ON artifacts ({idx_col})"
                    ))
                logger.info("Created artifacts table")

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
        if current != "d4e5f6a7b8c9":
            await conn.execute(text("DELETE FROM alembic_version"))
            await conn.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES (:v)"
            ), {"v": "d4e5f6a7b8c9"})
            logger.info("Stamped alembic_version to HEAD (d4e5f6a7b8c9)")
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
        if current != "d4e5f6a7b8c9":
            await conn.execute(text("DELETE FROM alembic_version"))
            await conn.execute(text(
                "INSERT INTO alembic_version (version_num) VALUES (:v)"
            ), {"v": "d4e5f6a7b8c9"})
            logger.info("Stamped alembic_version to HEAD (d4e5f6a7b8c9)")
