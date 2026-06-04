"""add_random_sort_value

Revision ID: 486cee66a271
Revises: 7efdd4a351fc
Create Date: 2025-11-16 23:24:06.767221

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '486cee66a271'
down_revision: Union[str, Sequence[str], None] = '7efdd4a351fc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add random_sort_value column for stable random sorting."""
    # Add the column (nullable initially so we can populate it)
    op.add_column('media_items', sa.Column('random_sort_value', sa.Float(), nullable=True))

    # Populate existing rows with random values between 0 and 1
    # Using RANDOM() which works in SQLite to generate values
    op.execute("""
        UPDATE media_items
        SET random_sort_value = (ABS(RANDOM()) % 1000000) / 1000000.0
    """)

    # Now make it non-nullable since all rows have values
    # SQLite doesn't support ALTER COLUMN, so we need to recreate with constraint
    # But for simplicity, we'll leave it nullable and handle in app code


def downgrade() -> None:
    """Remove random_sort_value column."""
    op.drop_column('media_items', 'random_sort_value')
