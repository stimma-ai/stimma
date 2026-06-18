"""add ephemeral_run_id to media_items

Ephemeral media created while running a flow behind the tool abstraction
(flow-as-tool). These are never part of the user's library: tagged with the
one-shot run id, excluded from every user-facing query / ingestion / lineage /
websocket path, and hard-deleted when the run ends (or swept on crash).
NULL = normal, permanent media. See plans/CUSTOM_TOOLS_BUILD.md.

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm3n4o5p6q7r8'
down_revision: Union[str, Sequence[str], None] = 'l2m3n4o5p6q7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_INDEX = 'ix_media_items_ephemeral_run_id'


def upgrade() -> None:
    """Add the nullable, indexed ``ephemeral_run_id`` column (SQLite-safe)."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if 'media_items' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('media_items')}
    if 'ephemeral_run_id' not in columns:
        with op.batch_alter_table('media_items') as batch_op:
            batch_op.add_column(sa.Column('ephemeral_run_id', sa.String(), nullable=True))

    indexes = {ix['name'] for ix in inspector.get_indexes('media_items')}
    if _INDEX not in indexes:
        op.create_index(_INDEX, 'media_items', ['ephemeral_run_id'])


def downgrade() -> None:
    """Drop the index and column (no data preserved)."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if 'media_items' not in inspector.get_table_names():
        return

    indexes = {ix['name'] for ix in inspector.get_indexes('media_items')}
    if _INDEX in indexes:
        op.drop_index(_INDEX, table_name='media_items')

    columns = {col['name'] for col in inspector.get_columns('media_items')}
    if 'ephemeral_run_id' in columns:
        with op.batch_alter_table('media_items') as batch_op:
            batch_op.drop_column('ephemeral_run_id')
