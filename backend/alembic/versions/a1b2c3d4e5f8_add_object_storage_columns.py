"""add object storage columns to documents

Revision ID: a1b2c3d4e5f8
"""
from alembic import op
import sqlalchemy as sa

revision = "a1b2c3d4e5f8"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("storage_provider", sa.String(20), nullable=True, server_default=None),
    )
    op.add_column(
        "documents",
        sa.Column("storage_key", sa.String(500), nullable=True, server_default=None),
    )
    op.create_index("ix_documents_storage_provider", "documents", ["storage_provider"])


def downgrade() -> None:
    op.drop_index("ix_documents_storage_provider", "documents")
    op.drop_column("documents", "storage_key")
    op.drop_column("documents", "storage_provider")
