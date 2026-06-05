"""clear_clip_embeddings_for_onnx

Revision ID: v5w6x7y8z9a0
Revises: u4v5w6x7y8z9
Create Date: 2026-01-12

Clear all CLIP embeddings and reset clip_status to 'pending' for re-encoding.

The CLIP model has been migrated from PyTorch (ViT-g-14, 1024 dimensions) to
ONNX (ViT-B/32, 512 dimensions). Existing embeddings are incompatible and
must be regenerated.

Users should re-run CLIP indexing via the UI after this migration.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'v5w6x7y8z9a0'
down_revision: Union[str, Sequence[str], None] = 'u4v5w6x7y8z9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Clear all CLIP embeddings and reset status to pending."""
    # Clear all existing CLIP embeddings (they're incompatible with new model dimensions)
    op.execute("UPDATE media_items SET clip_embedding = NULL")

    # Reset clip_status to 'pending' so items get re-indexed
    # Only reset available files (file_unavailable = 0 or NULL)
    op.execute("""
        UPDATE media_items
        SET clip_status = 'pending'
        WHERE clip_status = 'completed'
        AND (file_unavailable = 0 OR file_unavailable IS NULL)
    """)


def downgrade() -> None:
    """No downgrade possible - embeddings cannot be restored."""
    # Note: This is a one-way migration. The old embeddings cannot be
    # automatically restored. To regenerate 1024-dim embeddings, users
    # would need to reinstall the old PyTorch model and re-run indexing.
    pass
