"""rename recipes to flows

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-06-16

Rename the `recipes` table to `flows` (and its indexes), and rename the
`chats.recipe_id` FK column to `chats.flow_id`. Part of the product-wide
"Recipe" -> "Flow" rename. SQLite (>= 3.25) rewrites the self-referential
`parent_id` foreign key to point at `flows` automatically on table rename.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l2m3n4o5p6q7'
down_revision: Union[str, Sequence[str], None] = 'k1l2m3n4o5p6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    if not inspector.has_table(table_name):
        return False
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    if not inspector.has_table(table_name):
        return False
    return any(column.get('name') == column_name for column in inspector.get_columns(table_name))


# (old_index_name, new_index_name, column) for the recipes/flows table.
_INDEX_RENAMES = [
    ('ix_recipes_id', 'ix_flows_id', 'id'),
    ('ix_recipes_name', 'ix_flows_name', 'name'),
    ('ix_recipes_parent_id', 'ix_flows_parent_id', 'parent_id'),
    ('ix_recipes_project_id', 'ix_flows_project_id', 'project_id'),
    ('ix_recipes_execution_state', 'ix_flows_execution_state', 'execution_state'),
    ('ix_recipes_deleted_at', 'ix_flows_deleted_at', 'deleted_at'),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # 1) Rename the table. SQLite carries indexes over (keeping their old
    #    names) and rewrites the self-referential parent_id FK to flows.
    if _has_table(inspector, 'recipes') and not _has_table(inspector, 'flows'):
        op.rename_table('recipes', 'flows')
        inspector = sa.inspect(bind)

    # 2) Re-name the carried-over indexes from ix_recipes_* to ix_flows_*.
    for old_name, new_name, column in _INDEX_RENAMES:
        if _has_index(inspector, 'flows', old_name):
            op.drop_index(old_name, table_name='flows')
        if not _has_index(inspector, 'flows', new_name):
            op.create_index(new_name, 'flows', [column])
    inspector = sa.inspect(bind)

    # 3) Rename chats.recipe_id -> chats.flow_id and its index.
    if _has_index(inspector, 'chats', 'ix_chats_recipe_id'):
        op.drop_index('ix_chats_recipe_id', table_name='chats')
    if _has_column(inspector, 'chats', 'recipe_id') and not _has_column(inspector, 'chats', 'flow_id'):
        op.execute('ALTER TABLE chats RENAME COLUMN recipe_id TO flow_id')
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'chats', 'ix_chats_flow_id'):
        op.create_index('ix_chats_flow_id', 'chats', ['flow_id'])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_index(inspector, 'chats', 'ix_chats_flow_id'):
        op.drop_index('ix_chats_flow_id', table_name='chats')
    if _has_column(inspector, 'chats', 'flow_id') and not _has_column(inspector, 'chats', 'recipe_id'):
        op.execute('ALTER TABLE chats RENAME COLUMN flow_id TO recipe_id')
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'chats', 'ix_chats_recipe_id'):
        op.create_index('ix_chats_recipe_id', 'chats', ['recipe_id'])

    inspector = sa.inspect(bind)
    for old_name, new_name, column in _INDEX_RENAMES:
        if _has_index(inspector, 'flows', new_name):
            op.drop_index(new_name, table_name='flows')
        if not _has_index(inspector, 'flows', old_name):
            op.create_index(old_name, 'flows', [column])
    inspector = sa.inspect(bind)

    if _has_table(inspector, 'flows') and not _has_table(inspector, 'recipes'):
        op.rename_table('flows', 'recipes')
