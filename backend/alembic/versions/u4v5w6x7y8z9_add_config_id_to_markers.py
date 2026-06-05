"""add_config_id_to_markers

Revision ID: u4v5w6x7y8z9
Revises: t3u4v5w6x7y8
Create Date: 2026-01-11

Adds config_id column to markers table for stable matching between
config file markers and database markers. This allows marker names
to be safely renamed without losing the association.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'u4v5w6x7y8z9'
down_revision: Union[str, Sequence[str], None] = 't3u4v5w6x7y8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add config_id column to markers table."""
    # Add config_id column (nullable, will be populated by sync logic)
    op.add_column('markers', sa.Column('config_id', sa.String(), nullable=True))

    # Create index for fast lookups
    op.create_index('ix_markers_config_id', 'markers', ['config_id'])


def downgrade() -> None:
    """Remove config_id column from markers table."""
    op.drop_index('ix_markers_config_id', table_name='markers')
    op.drop_column('markers', 'config_id')
