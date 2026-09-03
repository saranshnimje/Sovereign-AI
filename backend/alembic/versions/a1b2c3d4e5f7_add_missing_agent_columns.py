"""add todo_json and other agent columns

Revision ID: a1b2c3d4e5f7
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _col_exists(table: str, column: str) -> bool:
    conn = op.get_bind()
    cols = [r[1] for r in conn.execute(sa.text(f"PRAGMA table_info({table})"))]
    return column in cols


def upgrade() -> None:
    for col, typ in [
        ("todo_json", sa.Text),
        ("goal_json", sa.Text),
        ("current_step_id", sa.Integer),
        ("cancel_requested", sa.Boolean),
        ("parent_run_id", sa.String(36)),
        ("context_summary", sa.Text),
        ("final_verification_json", sa.Text),
        ("failure_reason", sa.Text),
    ]:
        if not _col_exists("agent_runs", col):
            op.add_column("agent_runs", sa.Column(col, typ, nullable=True))


def downgrade() -> None:
    for col in [
        "todo_json", "goal_json", "current_step_id", "cancel_requested",
        "parent_run_id", "context_summary", "final_verification_json",
        "failure_reason",
    ]:
        if _col_exists("agent_runs", col):
            op.drop_column("agent_runs", col)
