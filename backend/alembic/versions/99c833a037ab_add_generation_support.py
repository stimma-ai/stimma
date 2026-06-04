"""add_generation_support

Revision ID: 99c833a037ab
Revises: 48927e5141c4
Create Date: 2025-11-19 16:39:09.829745

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '99c833a037ab'
down_revision: Union[str, Sequence[str], None] = '48927e5141c4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add generation_metadata column to media_items
    op.add_column('media_items', sa.Column('generation_metadata', sa.String(), nullable=True))

    # Create generation_jobs table
    op.create_table(
        'generation_jobs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),  # queued, assigned, processing, completed, failed
        sa.Column('generator_type', sa.String(), nullable=False),
        sa.Column('generator_name', sa.String(), nullable=False),
        sa.Column('model_name', sa.String(), nullable=False),
        sa.Column('parameters', sa.String(), nullable=False),  # JSON string
        sa.Column('folder_path', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('result_media_id', sa.Integer(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['result_media_id'], ['media_items.id'], ondelete='SET NULL')
    )

    # Create indexes for common queries
    op.create_index('ix_generation_jobs_status', 'generation_jobs', ['status'])
    op.create_index('ix_generation_jobs_created_at', 'generation_jobs', ['created_at'])
    op.create_index('ix_media_items_generation_metadata', 'media_items', ['generation_metadata'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop indexes
    op.drop_index('ix_media_items_generation_metadata', 'media_items')
    op.drop_index('ix_generation_jobs_created_at', 'generation_jobs')
    op.drop_index('ix_generation_jobs_status', 'generation_jobs')

    # Drop generation_jobs table
    op.drop_table('generation_jobs')

    # Remove generation_metadata column from media_items
    op.drop_column('media_items', 'generation_metadata')
