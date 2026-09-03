"""add agent_events table and AgentRun fields

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-09-04
"""
from alembic import op
import sqlalchemy as sa

revision = "f1a2b3c4d5e6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create agent_events table
    op.create_table(
        "agent_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("agent_runs.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_agent_events_run_seq", "agent_events", ["run_id", "sequence"])

    # Add new fields to agent_runs
    with op.batch_alter_table("agent_runs") as batch:
        batch.add_column(sa.Column("goal_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("current_step_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("parent_run_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("context_summary", sa.Text(), nullable=True))
        batch.add_column(sa.Column("final_verification_json", sa.Text(), nullable=True))
        batch.add_column(sa.Column("failure_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("agent_runs") as batch:
        batch.drop_column("failure_reason")
        batch.drop_column("final_verification_json")
        batch.drop_column("context_summary")
        batch.drop_column("parent_run_id")
        batch.drop_column("cancel_requested")
        batch.drop_column("current_step_id")
        batch.drop_column("goal_json")

    op.drop_index("idx_agent_events_run_seq", table_name="agent_events")
    op.drop_table("agent_events")
