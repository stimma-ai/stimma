"""add_source_to_media_markers

Revision ID: f1a2b3c4d5e6
Revises: 28ea0ec298dd
Create Date: 2025-11-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = '28ea0ec298dd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add source column to media_markers for auto/manual/suppressed tracking."""
    # Add source column with default 'manual' for existing records
    op.add_column('media_markers', sa.Column('source', sa.String(), nullable=True))
    op.execute("UPDATE media_markers SET source = 'manual' WHERE source IS NULL")
    # SQLite doesn't support ALTER COLUMN, so we leave it nullable but with default


def downgrade() -> None:
    """Remove source column from media_markers."""
    op.drop_column('media_markers', 'source')
