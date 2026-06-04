"""add_display_order_to_saved_views

Revision ID: j3k4l5m6n7o8
Revises: i2j3k4l5m6n7
Create Date: 2025-12-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j3k4l5m6n7o8'
down_revision: Union[str, Sequence[str], None] = 'i2j3k4l5m6n7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add display_order column to saved_views table."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table exists first (for fresh databases)
    if 'saved_views' not in inspector.get_table_names():
        print("saved_views table does not exist yet, skipping migration")
        return

    # Check if column already exists
    existing_columns = [col['name'] for col in inspector.get_columns('saved_views')]

    if 'display_order' not in existing_columns:
        op.add_column('saved_views', sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'))
        print("Successfully added display_order column to saved_views")
    else:
        print("display_order column already exists, skipping")

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))


def downgrade() -> None:
    """Remove display_order column from saved_views table."""
    op.drop_column('saved_views', 'display_order')
