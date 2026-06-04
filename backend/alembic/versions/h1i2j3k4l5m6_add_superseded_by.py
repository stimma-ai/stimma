"""add_superseded_by

Revision ID: h1i2j3k4l5m6
Revises: g1h2i3j4k5l6
Create Date: 2025-12-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h1i2j3k4l5m6'
down_revision: Union[str, Sequence[str], None] = 'g1h2i3j4k5l6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add superseded_by column to media_items for tracking upscale replacements."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if column already exists
    columns = [col['name'] for col in inspector.get_columns('media_items')]

    if 'superseded_by' not in columns:
        with op.batch_alter_table('media_items') as batch_op:
            batch_op.add_column(sa.Column('superseded_by', sa.Integer(), nullable=True))
            batch_op.create_index('ix_media_items_superseded_by', ['superseded_by'])
            batch_op.create_foreign_key(
                'fk_media_items_superseded_by',
                'media_items',
                ['superseded_by'],
                ['id']
            )
        print("Successfully added superseded_by column to media_items")
    else:
        print("superseded_by column already exists, skipping")

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))


def downgrade() -> None:
    """Remove superseded_by column from media_items."""
    with op.batch_alter_table('media_items') as batch_op:
        batch_op.drop_constraint('fk_media_items_superseded_by', type_='foreignkey')
        batch_op.drop_index('ix_media_items_superseded_by')
        batch_op.drop_column('superseded_by')
