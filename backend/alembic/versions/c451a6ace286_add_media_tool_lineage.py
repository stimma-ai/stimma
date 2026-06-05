"""add_media_tool_lineage

Revision ID: c451a6ace286
Revises: d3e4f5g6h7i8
Create Date: 2026-02-08

Add media_tool_lineage junction table for efficient tool-based filtering.
This table denormalizes tool lineage: for each media item, it stores ALL
full_tool_ids from its entire ancestor chain (including itself).

The backfill uses a recursive CTE to walk the media_lineage table and
collect all ancestor tool_ids.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c451a6ace286'
down_revision: Union[str, Sequence[str], None] = 'd3e4f5g6h7i8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create media_tool_lineage table and backfill from existing lineage data."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'media_tool_lineage' not in existing_tables:
        op.create_table(
            'media_tool_lineage',
            sa.Column('media_id', sa.Integer(), sa.ForeignKey('media_items.id', ondelete='CASCADE'), primary_key=True),
            sa.Column('full_tool_id', sa.String(), primary_key=True),
        )
        op.create_index('idx_tool_lineage_tool', 'media_tool_lineage', ['full_tool_id'])

    # Backfill: walk media_lineage recursively to collect all ancestor tool_ids
    connection.execute(sa.text("""
        INSERT OR IGNORE INTO media_tool_lineage (media_id, full_tool_id)
        SELECT DISTINCT at.media_id, at.full_tool_id
        FROM (
            WITH RECURSIVE ancestor_tools AS (
                -- Base case: each media item's own tool_id
                SELECT id AS media_id, tool_id AS full_tool_id
                FROM media_items
                WHERE tool_id IS NOT NULL

                UNION

                -- Recursive case: inherit tool_ids from ancestors via media_lineage
                SELECT ml.media_id, at.full_tool_id
                FROM media_lineage ml
                JOIN ancestor_tools at ON at.media_id = ml.source_media_id
                WHERE ml.source_media_id IS NOT NULL
            )
            SELECT media_id, full_tool_id FROM ancestor_tools
        ) at
    """))


def downgrade() -> None:
    """Drop media_tool_lineage table."""
    op.drop_index('idx_tool_lineage_tool', table_name='media_tool_lineage')
    op.drop_table('media_tool_lineage')
