"""allow user deletion while preserving audit logs

Revision ID: b7c8d9e0f1a2
Revises: d4e5f6a7b8c9
Create Date: 2026-09-17
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.alter_column(
        "audit_logs",
        "user_id",
        existing_type=sa.String(length=36),
        nullable=True,
    )
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Downgrade is intentionally conservative: existing NULL actor references
    # cannot be restored to a valid user ID without inventing audit history.
    op.drop_constraint("audit_logs_user_id_fkey", "audit_logs", type_="foreignkey")
    op.create_foreign_key(
        "audit_logs_user_id_fkey",
        "audit_logs",
        "users",
        ["user_id"],
        ["id"],
    )
    op.alter_column(
        "audit_logs",
        "user_id",
        existing_type=sa.String(length=36),
        nullable=False,
    )
