"""add_editor_project_column

Revision ID: z9a0b1c2d3e4
Revises: y8z9a0b1c2d3
Create Date: 2026-01-29

Add editor_project column to media_items table for non-destructive
image editing. This stores the serialized editor project state (JSON)
so users can re-edit saved images without losing their work.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'z9a0b1c2d3e4'
down_revision: Union[str, Sequence[str], None] = 'y8z9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add editor_project column to media_items."""
    # Check if column exists (for idempotency)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    if 'editor_project' not in columns:
        op.add_column(
            'media_items',
            sa.Column('editor_project', sa.Text(), nullable=True)
        )


def downgrade() -> None:
    """Remove editor_project column from media_items."""
    op.drop_column('media_items', 'editor_project')
