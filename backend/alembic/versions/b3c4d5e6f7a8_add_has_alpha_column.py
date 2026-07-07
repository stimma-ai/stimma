"""add_has_alpha_column

Revision ID: b3c4d5e6f7a8
Revises: r8s9t0u1v2w3
Create Date: 2026-07-06

Add has_alpha column to media_items — whether the file's format declares an
alpha channel (header-only check, no pixel decode). NULL for existing rows;
backfilled by the metadata phase after config_version.py bumps 'metadata' to
v4, which resets every completed row to pending for reprocessing.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'r8s9t0u1v2w3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add has_alpha column to media_items."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    if 'has_alpha' not in columns:
        op.add_column(
            'media_items',
            sa.Column('has_alpha', sa.Boolean(), nullable=True)
        )
        op.create_index(
            'ix_media_items_has_alpha', 'media_items', ['has_alpha']
        )


def downgrade() -> None:
    """Remove has_alpha column from media_items."""
    op.drop_index('ix_media_items_has_alpha', table_name='media_items')
    op.drop_column('media_items', 'has_alpha')
