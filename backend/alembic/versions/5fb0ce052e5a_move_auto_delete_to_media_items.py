"""move_auto_delete_to_media_items

Revision ID: 5fb0ce052e5a
Revises: e031f59ab103
Create Date: 2025-11-23 11:22:41.721846

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5fb0ce052e5a'
down_revision: Union[str, Sequence[str], None] = 'e031f59ab103'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add auto_delete_at column to media_items
    op.add_column('media_items', sa.Column('auto_delete_at', sa.DateTime(), nullable=True))
    op.create_index('ix_media_items_auto_delete_at', 'media_items', ['auto_delete_at'])

    # Clear all generation jobs (fresh start as requested)
    op.execute('DELETE FROM generation_jobs')


def downgrade() -> None:
    """Downgrade schema."""
    # Remove auto_delete_at from media_items
    op.drop_index('ix_media_items_auto_delete_at', table_name='media_items')
    op.drop_column('media_items', 'auto_delete_at')
