"""add_marker_source_covering_index

Revision ID: bb2cc3dd4ee5
Revises: aa1bb2cc3dd4
Create Date: 2026-02-17

Adds a covering index on media_markers(marker_id, media_id, source) so that
marker filter queries with source != 'suppressed' can be satisfied from the
index alone, without table lookups.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'bb2cc3dd4ee5'
down_revision: Union[str, Sequence[str], None] = 'aa1bb2cc3dd4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'idx_marker_media_source',
        'media_markers',
        ['marker_id', 'media_id', 'source'],
    )


def downgrade() -> None:
    op.drop_index('idx_marker_media_source', table_name='media_markers')
