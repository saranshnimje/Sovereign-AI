"""add custom_headers to llm_providers

Revision ID: a1b2c3d4e5f6
Revises: 789b154435c5
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '789b154435c5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('llm_providers', sa.Column('custom_headers', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('llm_providers', 'custom_headers')
