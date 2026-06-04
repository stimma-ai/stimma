"""add_media_lineage

Revision ID: g1h2i3j4k5l6
Revises: f1a2b3c4d5e6
Create Date: 2025-12-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add media_lineage table for tracking generation parent/child relationships."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'media_lineage' not in existing_tables:
        op.create_table(
            'media_lineage',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('source_media_id', sa.Integer(), nullable=True),
            sa.Column('source_file_path', sa.String(), nullable=True),
            sa.Column('source_order', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('task_type', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['source_media_id'], ['media_items.id'], ondelete='SET NULL'),
        )
        op.create_index('ix_media_lineage_id', 'media_lineage', ['id'])
        op.create_index('ix_media_lineage_media_id', 'media_lineage', ['media_id'])
        op.create_index('ix_media_lineage_source_media_id', 'media_lineage', ['source_media_id'])
        op.create_index('idx_lineage_media_source', 'media_lineage', ['media_id', 'source_order'], unique=True)

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))

    print("Successfully added media_lineage table")


def downgrade() -> None:
    """Remove media_lineage table."""
    op.drop_index('idx_lineage_media_source', 'media_lineage')
    op.drop_index('ix_media_lineage_source_media_id', 'media_lineage')
    op.drop_index('ix_media_lineage_media_id', 'media_lineage')
    op.drop_index('ix_media_lineage_id', 'media_lineage')
    op.drop_table('media_lineage')
