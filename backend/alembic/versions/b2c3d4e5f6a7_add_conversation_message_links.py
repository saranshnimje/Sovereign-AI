"""add conversation_id, message_id, pending_question, pending_options_json, user_answer to agent_runs

Revision ID: b2c3d4e5f6a7
"""
from alembic import op
import sqlalchemy as sa

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        result = conn.execute(
            sa.text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :table AND column_name = :col"
            ),
            {"table": table, "col": column},
        )
        return result.fetchone() is not None
    elif dialect == "sqlite":
        cols = [r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))]
        return column in cols
    else:
        return False


def upgrade() -> None:
    for col, typ, fk in [
        ("conversation_id", sa.String(36), sa.ForeignKey("conversations.id", ondelete="SET NULL")),
        ("message_id", sa.String(36), sa.ForeignKey("messages.id", ondelete="SET NULL")),
        ("pending_question", sa.Text, None),
        ("pending_options_json", sa.Text, None),
        ("user_answer", sa.Text, None),
    ]:
        if not _col_exists("agent_runs", col):
            op.add_column("agent_runs", sa.Column(col, typ, nullable=True, foreign_key=fk))

    # Add indexes for efficient conversation→runs lookup
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_conversation_id "
            "ON agent_runs (conversation_id)"
        ))
        conn.execute(sa.text(
            "CREATE INDEX IF NOT EXISTS ix_agent_runs_message_id "
            "ON agent_runs (message_id)"
        ))
    elif dialect == "sqlite":
        # SQLite: check if indexes exist before creating
        try:
            op.create_index("ix_agent_runs_conversation_id", "agent_runs", ["conversation_id"])
        except Exception:
            pass
        try:
            op.create_index("ix_agent_runs_message_id", "agent_runs", ["message_id"])
        except Exception:
            pass


def downgrade() -> None:
    for col in ["user_answer", "pending_options_json", "pending_question", "message_id", "conversation_id"]:
        if _col_exists("agent_runs", col):
            op.drop_column("agent_runs", col)
