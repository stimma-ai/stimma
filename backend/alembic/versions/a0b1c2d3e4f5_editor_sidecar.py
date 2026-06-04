"""editor_sidecar

Revision ID: a0b1c2d3e4f5
Revises: z9a0b1c2d3e4
Create Date: 2026-01-30

Replace editor_project Text column with has_editor_sidecar Boolean column.
Editor project state is now stored in sidecar files ({image_path}.stimmaedit.json)
instead of in the database to avoid storing large base64 image data.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a0b1c2d3e4f5'
down_revision: Union[str, Sequence[str], None] = 'z9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Replace editor_project with has_editor_sidecar."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    # Add the new column if it doesn't exist
    if 'has_editor_sidecar' not in columns:
        op.add_column(
            'media_items',
            sa.Column('has_editor_sidecar', sa.Boolean(), nullable=True)
        )
        # Set default value for existing rows
        op.execute("UPDATE media_items SET has_editor_sidecar = 0 WHERE has_editor_sidecar IS NULL")

    # Drop the old column if it exists (from previous migration or legacy)
    if 'editor_project' in columns:
        op.drop_column('media_items', 'editor_project')


def downgrade() -> None:
    """Restore editor_project column and drop has_editor_sidecar."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    # Re-add editor_project
    if 'editor_project' not in columns:
        op.add_column(
            'media_items',
            sa.Column('editor_project', sa.Text(), nullable=True)
        )

    # Drop has_editor_sidecar
    if 'has_editor_sidecar' in columns:
        op.drop_column('media_items', 'has_editor_sidecar')
