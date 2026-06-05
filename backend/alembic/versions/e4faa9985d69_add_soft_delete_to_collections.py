"""add_soft_delete_to_collections

Revision ID: e4faa9985d69
Revises: d5ff85f1130d
Create Date: 2025-11-20 21:54:45.408731

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4faa9985d69'
down_revision: Union[str, Sequence[str], None] = 'd5ff85f1130d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add soft delete column to collections
    op.add_column('collections', sa.Column('deleted_at', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_collections_deleted_at'), 'collections', ['deleted_at'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    # Remove soft delete column from collections
    op.drop_index(op.f('ix_collections_deleted_at'), table_name='collections')
    op.drop_column('collections', 'deleted_at')
