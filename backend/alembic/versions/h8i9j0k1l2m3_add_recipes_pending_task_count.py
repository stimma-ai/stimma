"""add pending_task_count to recipes

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-18

Phase 6: denormalized pending task count for recipes. The authoritative
source is the per-recipe state.db tasks table; this column mirrors it so
landing cards and sidebar tab badges can read a single counter without
opening N SQLite files.

Maintained by the WebSocket event path (recipe_task_created /
recipe_task_resolved) and reconciled from authoritative state on backend
startup to catch any drift.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'h8i9j0k1l2m3'
down_revision: Union[str, Sequence[str], None] = 'g7h8i9j0k1l2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column.get('name') == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table('recipes'):
        return
    if not _has_column(inspector, 'recipes', 'pending_task_count'):
        op.add_column(
            'recipes',
            sa.Column('pending_task_count', sa.Integer(), nullable=False, server_default='0'),
        )


def downgrade() -> None:
    op.drop_column('recipes', 'pending_task_count')
