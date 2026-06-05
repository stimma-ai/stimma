"""Add tool_id and preset_id columns for provenance tracking

Revision ID: q0r1s2t3u4v5
Revises: p9q0r1s2t3u4
Create Date: 2025-12-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q0r1s2t3u4v5'
down_revision: Union[str, Sequence[str], None] = 'p9q0r1s2t3u4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tool_id and preset_id columns for provenance tracking."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Add columns to media_items
    if 'media_items' in inspector.get_table_names():
        existing_columns = [col['name'] for col in inspector.get_columns('media_items')]

        if 'tool_id' not in existing_columns:
            op.add_column('media_items', sa.Column('tool_id', sa.String(), nullable=True))
            op.create_index('ix_media_items_tool_id', 'media_items', ['tool_id'], unique=False)
            print("Successfully added tool_id column to media_items")
        else:
            print("tool_id column already exists in media_items, skipping")

        if 'preset_id' not in existing_columns:
            op.add_column('media_items', sa.Column('preset_id', sa.Integer(), nullable=True))
            op.create_index('ix_media_items_preset_id', 'media_items', ['preset_id'], unique=False)
            # Note: We don't create FK constraint here to avoid issues with existing data
            # The FK is defined in the model but SQLite doesn't enforce FKs by default anyway
            print("Successfully added preset_id column to media_items")
        else:
            print("preset_id column already exists in media_items, skipping")

    # Add preset_id to generation_jobs
    if 'generation_jobs' in inspector.get_table_names():
        existing_columns = [col['name'] for col in inspector.get_columns('generation_jobs')]

        if 'preset_id' not in existing_columns:
            op.add_column('generation_jobs', sa.Column('preset_id', sa.Integer(), nullable=True))
            op.create_index('ix_generation_jobs_preset_id', 'generation_jobs', ['preset_id'], unique=False)
            print("Successfully added preset_id column to generation_jobs")
        else:
            print("preset_id column already exists in generation_jobs, skipping")


def downgrade() -> None:
    """Remove tool_id and preset_id columns."""
    # Remove from media_items
    op.drop_index('ix_media_items_tool_id', table_name='media_items')
    op.drop_column('media_items', 'tool_id')
    op.drop_index('ix_media_items_preset_id', table_name='media_items')
    op.drop_column('media_items', 'preset_id')

    # Remove from generation_jobs
    op.drop_index('ix_generation_jobs_preset_id', table_name='generation_jobs')
    op.drop_column('generation_jobs', 'preset_id')
