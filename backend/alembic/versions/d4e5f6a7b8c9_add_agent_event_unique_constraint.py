"""Add unique constraint on agent_events (run_id, sequence).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-09-14
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing non-unique index
    op.drop_index("idx_agent_events_run_seq", table_name="agent_events")

    # Create a unique composite index on (run_id, sequence)
    op.create_index(
        "uq_agent_events_run_seq",
        "agent_events",
        ["run_id", "sequence"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_agent_events_run_seq", table_name="agent_events")

    # Recreate the original non-unique index
    op.create_index(
        "idx_agent_events_run_seq",
        "agent_events",
        ["run_id", "sequence"],
    )
