"""purge_orphan_generation_jobs

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-05-28

Permanent delete used to set GenerationJob.result_media_id = NULL instead of
deleting the row. Those orphans show up as ghost placeholder tiles in the
generation queue and leak the original prompt/params indefinitely. The scrub
in delete_operations.py now deletes the row outright; this one-shot purge
clears anything that was orphaned by the old code path.

Status filter avoids touching live work: queued / assigned / processing /
failed jobs legitimately have no result_media_id and must stay.
"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'i9j0k1l2m3n4'
down_revision: Union[str, Sequence[str], None] = 'h8i9j0k1l2m3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "DELETE FROM generation_jobs "
        "WHERE result_media_id IS NULL AND status = 'completed'"
    )


def downgrade() -> None:
    # Data deletion can't be reversed.
    pass
