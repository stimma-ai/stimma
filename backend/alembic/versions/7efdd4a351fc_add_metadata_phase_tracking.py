"""add_metadata_phase_tracking

Revision ID: 7efdd4a351fc
Revises: 241859bff6da
Create Date: 2025-11-16 15:26:44.966191

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7efdd4a351fc'
down_revision: Union[str, Sequence[str], None] = '241859bff6da'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add metadata phase tracking columns
    op.add_column('media_items', sa.Column('metadata_status', sa.String(), nullable=True))
    op.add_column('media_items', sa.Column('metadata_error', sa.String(), nullable=True))
    op.add_column('media_items', sa.Column('metadata_retry_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('media_items', sa.Column('metadata_processed_at', sa.DateTime(), nullable=True))
    op.add_column('media_items', sa.Column('metadata_config_version', sa.String(), nullable=True))

    # Create index for metadata status queries
    op.create_index('idx_metadata_status', 'media_items', ['metadata_status'])

    # Set existing files to 'pending' so they get processed
    op.execute("UPDATE media_items SET metadata_status = 'pending' WHERE metadata_status IS NULL")


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('idx_metadata_status', 'media_items')
    op.drop_column('media_items', 'metadata_config_version')
    op.drop_column('media_items', 'metadata_processed_at')
    op.drop_column('media_items', 'metadata_retry_count')
    op.drop_column('media_items', 'metadata_error')
    op.drop_column('media_items', 'metadata_status')
