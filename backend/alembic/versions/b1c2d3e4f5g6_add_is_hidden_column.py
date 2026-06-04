"""add_is_hidden_column

Revision ID: b1c2d3e4f5g6
Revises: a0b1c2d3e4f5
Create Date: 2026-01-31

Add is_hidden column to media_items for manual visibility control.
Works with superseded_by to determine effective hidden state:
effective_hidden = is_hidden if is_hidden is not None else (superseded_by is not None)
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b1c2d3e4f5g6'
down_revision: Union[str, Sequence[str], None] = 'a0b1c2d3e4f5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add is_hidden column to media_items."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    if 'is_hidden' not in columns:
        op.add_column(
            'media_items',
            sa.Column('is_hidden', sa.Boolean(), nullable=True, index=True)
        )


def downgrade() -> None:
    """Remove is_hidden column from media_items."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    if 'is_hidden' in columns:
        op.drop_column('media_items', 'is_hidden')
