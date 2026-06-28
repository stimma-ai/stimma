"""backfill random_sort_value for rows missing it

The original add_random_sort_value migration only populated rows that existed at
the time, and only the filesystem-scan ingestion path set the value on new rows.
Every other MediaItem insert path (generation, upload, sets/grids, layouts, agent
tools) left it NULL, so libraries built from generated/uploaded media had all-NULL
values. Random sort then collapsed every such item to an equal key (NULL * seed),
pinning them to id order and making the re-randomize button a no-op.

Backfill any remaining NULLs. New rows are now covered by the model-level default.

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-06-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'q7r8s9t0u1v2'
down_revision: Union[str, Sequence[str], None] = 'p6q7r8s9t0u1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Same value shape as the original migration: a fixed random in [0, 1).
    op.execute("""
        UPDATE media_items
        SET random_sort_value = (ABS(RANDOM()) % 1000000) / 1000000.0
        WHERE random_sort_value IS NULL
    """)


def downgrade() -> None:
    # Non-destructive backfill; nothing to undo.
    pass
