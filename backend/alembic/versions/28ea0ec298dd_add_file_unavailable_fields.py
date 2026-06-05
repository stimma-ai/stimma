"""add_file_unavailable_fields

Revision ID: 28ea0ec298dd
Revises: a1b2c3d4e5f6
Create Date: 2025-11-27 07:20:49.145628

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '28ea0ec298dd'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add file_unavailable tracking fields to media_items."""
    # Add file_unavailable boolean (default False)
    op.add_column('media_items', sa.Column('file_unavailable', sa.Boolean(), nullable=True))
    op.execute("UPDATE media_items SET file_unavailable = 0 WHERE file_unavailable IS NULL")

    # Add file_unavailable_since timestamp
    op.add_column('media_items', sa.Column('file_unavailable_since', sa.DateTime(), nullable=True))

    # Add index for efficient queries
    op.create_index(op.f('ix_media_items_file_unavailable'), 'media_items', ['file_unavailable'], unique=False)


def downgrade() -> None:
    """Remove file_unavailable tracking fields."""
    op.drop_index(op.f('ix_media_items_file_unavailable'), table_name='media_items')
    op.drop_column('media_items', 'file_unavailable_since')
    op.drop_column('media_items', 'file_unavailable')
