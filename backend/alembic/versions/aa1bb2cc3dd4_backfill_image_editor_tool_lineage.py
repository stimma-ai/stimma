"""backfill_image_editor_tool_lineage

Revision ID: aa1bb2cc3dd4
Revises: z9a0b1c2d3e4
Create Date: 2026-02-15

Backfill tool_id and media_tool_lineage for images saved from the
Stimma Image Editor, so they appear in the tool filter list.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'aa1bb2cc3dd4'
down_revision: Union[str, Sequence[str], None] = 'e5f6g7h8i9j0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TOOL_ID = "builtin:stimma:image-editor"


def upgrade() -> None:
    """Set tool_id and add tool lineage entries for existing editor-saved images."""
    connection = op.get_bind()

    # Set tool_id on media_items that have editor sidecars but no tool_id
    connection.execute(
        sa.text(
            "UPDATE media_items SET tool_id = :tool_id "
            "WHERE has_editor_sidecar = 1 AND (tool_id IS NULL OR tool_id = '')"
        ),
        {"tool_id": TOOL_ID},
    )

    # Insert tool lineage entries for those items (skip if already exists)
    connection.execute(
        sa.text(
            "INSERT OR IGNORE INTO media_tool_lineage (media_id, full_tool_id) "
            "SELECT id, :tool_id FROM media_items "
            "WHERE has_editor_sidecar = 1"
        ),
        {"tool_id": TOOL_ID},
    )


def downgrade() -> None:
    """Remove image editor tool lineage and tool_id."""
    connection = op.get_bind()

    connection.execute(
        sa.text(
            "DELETE FROM media_tool_lineage WHERE full_tool_id = :tool_id"
        ),
        {"tool_id": TOOL_ID},
    )

    connection.execute(
        sa.text(
            "UPDATE media_items SET tool_id = NULL "
            "WHERE tool_id = :tool_id"
        ),
        {"tool_id": TOOL_ID},
    )
