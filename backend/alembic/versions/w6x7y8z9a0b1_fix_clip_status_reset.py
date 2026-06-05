"""fix_clip_status_reset

Revision ID: w6x7y8z9a0b1
Revises: v5w6x7y8z9a0
Create Date: 2026-01-12

Fix for previous migration that used wrong status value ('complete' instead of 'completed').
This ensures CLIP embeddings get regenerated with the new ONNX model.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'w6x7y8z9a0b1'
down_revision: Union[str, Sequence[str], None] = 'v5w6x7y8z9a0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Reset clip_status to pending for items that still have completed status."""
    # The previous migration used 'complete' but the status is 'completed'
    # This fixes any items that weren't reset properly
    # Only reset available files (file_unavailable = 0 or NULL)
    op.execute("""
        UPDATE media_items
        SET clip_status = 'pending'
        WHERE clip_status = 'completed'
        AND (file_unavailable = 0 OR file_unavailable IS NULL)
    """)


def downgrade() -> None:
    """No downgrade possible - status was already incorrect."""
    pass
