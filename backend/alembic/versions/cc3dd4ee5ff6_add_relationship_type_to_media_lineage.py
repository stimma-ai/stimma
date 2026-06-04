"""add_relationship_type_to_media_lineage

Revision ID: cc3dd4ee5ff6
Revises: bb2cc3dd4ee5
Create Date: 2026-02-17

Adds relationship_type column to media_lineage table to distinguish
'derived' (standard generation lineage) from 'inspired' (inspire feature).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'cc3dd4ee5ff6'
down_revision: Union[str, Sequence[str], None] = 'bb2cc3dd4ee5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'media_lineage',
        sa.Column('relationship_type', sa.String(), nullable=False, server_default='derived'),
    )


def downgrade() -> None:
    op.drop_column('media_lineage', 'relationship_type')
