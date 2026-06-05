"""add_saved_views

Revision ID: i2j3k4l5m6n7
Revises: h1i2j3k4l5m6
Create Date: 2025-12-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'i2j3k4l5m6n7'
down_revision: Union[str, Sequence[str], None] = 'h1i2j3k4l5m6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create saved_views table for storing filter/sort presets."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table already exists
    existing_tables = inspector.get_table_names()

    if 'saved_views' not in existing_tables:
        op.create_table(
            'saved_views',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('profile_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('filters', sa.String(), nullable=False),
            sa.Column('sort_by', sa.String(), nullable=False, server_default='created_desc'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_saved_views_id', 'saved_views', ['id'])
        op.create_index('ix_saved_views_profile_id', 'saved_views', ['profile_id'])
        op.create_index('ix_saved_views_name', 'saved_views', ['name'])
        print("Successfully created saved_views table")
    else:
        print("saved_views table already exists, skipping")

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))


def downgrade() -> None:
    """Drop saved_views table."""
    op.drop_index('ix_saved_views_name', 'saved_views')
    op.drop_index('ix_saved_views_profile_id', 'saved_views')
    op.drop_index('ix_saved_views_id', 'saved_views')
    op.drop_table('saved_views')
