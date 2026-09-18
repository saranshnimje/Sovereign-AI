"""Startup migration helper for Sovereign AI Workbench."""
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

logger = structlog.get_logger()

_AGENT_RUNS_COLUMNS = [
    ("goal_json", "TEXT"),
    ("current_step_id", "INTEGER"),
    ("cancel_requested", "BOOLEAN NOT NULL DEFAULT FALSE"),
    ("parent_run_id", "VARCHAR(36)"),
    ("context_summary", "TEXT"),
    ("final_verification_json", "TEXT"),
    ("failure_reason", "TEXT"),
    ("todo_json", "TEXT"),
    ("conversation_id", "VARCHAR(36)"),
    ("message_id", "VARCHAR(36)"),
    ("pending_question", "TEXT"),
    ("pending_options_json", "TEXT"),
    ("user_answer", "TEXT"),
]

_DOCUMENT_COLUMNS = [
    ("storage_provider", "VARCHAR(20)"),
    ("storage_key", "VARCHAR(500)"),
]


async def run_startup_migrations(engine: AsyncEngine, is_postgres: bool) -> None:
    try:
        async with engine.begin() as conn:
            for col_name, col_ddl in _AGENT_RUNS_COLUMNS:
                if not await _column_exists(conn, "agent_runs", col_name, is_postgres):
                    await conn.execute(text(f"ALTER TABLE agent_runs ADD COLUMN {col_name} {col_ddl}"))

            for col_name, col_ddl in _DOCUMENT_COLUMNS:
                if not await _column_exists(conn, "documents", col_name, is_postgres):
                    await conn.execute(text(f"ALTER TABLE documents ADD COLUMN {col_name} {col_ddl}"))

            if is_postgres and await _table_exists(conn, "documents", True):
                await conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS ix_documents_storage_provider "
                    "ON documents (storage_provider)"
                ))

            if is_postgres and not await _table_exists(conn, "agent_events", True):
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
                    'CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_events_run_seq '
                    'ON agent_events (run_id, "sequence")'
                ))
                try:
                    await conn.execute(text(
                        "ALTER TABLE agent_events ADD CONSTRAINT fk_agent_events_run_id "
                        "FOREIGN KEY (run_id) REFERENCES agent_runs(id) ON DELETE CASCADE"
                    ))
                except Exception:
                    pass
            elif is_postgres:
                try:
                    await conn.execute(text("DROP INDEX IF EXISTS idx_agent_events_run_seq"))
                    await conn.execute(text(
                        'CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_events_run_seq '
                        'ON agent_events (run_id, "sequence")'
                    ))
                except Exception:
                    pass

            if is_postgres and not await _table_exists(conn, "artifacts", True):
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
                for idx_col in ("user_id", "conversation_id", "run_id"):
                    await conn.execute(text(
                        f"CREATE INDEX IF NOT EXISTS ix_artifacts_{idx_col} ON artifacts ({idx_col})"
                    ))

            if is_postgres and await _table_exists(conn, "audit_logs", True):
                fk = await conn.execute(text("""
                    SELECT pg_get_constraintdef(c.oid)
                    FROM pg_constraint c
                    JOIN pg_class t ON t.oid = c.conrelid
                    WHERE t.relname = 'audit_logs'
                      AND c.conname = 'audit_logs_user_id_fkey'
                """))
                fk_row = fk.fetchone()
                definition = str(fk_row[0] or "") if fk_row else ""
                if "ON DELETE SET NULL" not in definition.upper():
                    await conn.execute(text(
                        "ALTER TABLE audit_logs DROP CONSTRAINT IF EXISTS audit_logs_user_id_fkey"
                    ))
                    await conn.execute(text(
                        "ALTER TABLE audit_logs ALTER COLUMN user_id DROP NOT NULL"
                    ))
                    await conn.execute(text(
                        "ALTER TABLE audit_logs ADD CONSTRAINT audit_logs_user_id_fkey "
                        "FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL"
                    ))
                    logger.info("Updated audit_logs.user_id FK to ON DELETE SET NULL")

            await _stamp_alembic_head(conn)
    except Exception as exc:
        logger.warning("Startup migration fixup failed", error=str(exc))


async def _column_exists(conn, table: str, column: str, is_postgres: bool) -> bool:
    if is_postgres:
        result = await conn.execute(text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :col)"
        ), {"table": table, "col": column})
        return bool(result.scalar())
    result = await conn.execute(text(f"PRAGMA table_info({table})"))
    return any(row[1] == column for row in result)


async def _table_exists(conn, table: str, is_postgres: bool) -> bool:
    if is_postgres:
        result = await conn.execute(text(
            "SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
        ), {"t": table})
        return bool(result.scalar())
    result = await conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=:t"
    ), {"t": table})
    return result.fetchone() is not None


async def _stamp_alembic_head(conn) -> None:
    await conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL PRIMARY KEY
        )
    """))
    current = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
    target = "a1b2c3d4e5f8"
    if current != target:
        await conn.execute(text("DELETE FROM alembic_version"))
        await conn.execute(text(
            "INSERT INTO alembic_version (version_num) VALUES (:v)"
        ), {"v": target})
        logger.info("Stamped alembic_version", revision=target)
