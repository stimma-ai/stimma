"""add recipes

Revision ID: g7h8i9j0k1l2
Revises: f6g7h8i9j0k1
Create Date: 2026-04-17

Create `recipes` table (Phase 1 of the Recipes feature) and add a nullable
`recipe_id` FK to `chats` so recipe-agent conversations can be scoped to a
recipe, following the existing `project_id` pattern.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'g7h8i9j0k1l2'
down_revision: Union[str, Sequence[str], None] = 'f6g7h8i9j0k1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column.get('name') == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('recipes'):
        op.create_table(
            'recipes',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('parent_id', sa.Integer(), nullable=True),
            sa.Column('project_id', sa.Integer(), nullable=True),
            sa.Column('input_schema', sa.Text(), nullable=True),
            sa.Column('output_schema', sa.Text(), nullable=True),
            sa.Column('inputs', sa.Text(), nullable=True),
            sa.Column('program_hash', sa.String(), nullable=True),
            sa.Column('execution_state', sa.String(), nullable=False, server_default='idle'),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.ForeignKeyConstraint(['parent_id'], ['recipes.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
            sqlite_autoincrement=True,
        )
        inspector = sa.inspect(bind)

    if not _has_index(inspector, 'recipes', 'ix_recipes_id'):
        op.create_index('ix_recipes_id', 'recipes', ['id'])
    if not _has_index(inspector, 'recipes', 'ix_recipes_name'):
        op.create_index('ix_recipes_name', 'recipes', ['name'])
    if not _has_index(inspector, 'recipes', 'ix_recipes_parent_id'):
        op.create_index('ix_recipes_parent_id', 'recipes', ['parent_id'])
    if not _has_index(inspector, 'recipes', 'ix_recipes_project_id'):
        op.create_index('ix_recipes_project_id', 'recipes', ['project_id'])
    if not _has_index(inspector, 'recipes', 'ix_recipes_execution_state'):
        op.create_index('ix_recipes_execution_state', 'recipes', ['execution_state'])
    if not _has_index(inspector, 'recipes', 'ix_recipes_deleted_at'):
        op.create_index('ix_recipes_deleted_at', 'recipes', ['deleted_at'])

    inspector = sa.inspect(bind)
    if not _has_column(inspector, 'chats', 'recipe_id'):
        op.add_column('chats', sa.Column('recipe_id', sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'chats', 'ix_chats_recipe_id'):
        op.create_index('ix_chats_recipe_id', 'chats', ['recipe_id'])


def downgrade() -> None:
    op.drop_index('ix_chats_recipe_id', table_name='chats')
    op.drop_column('chats', 'recipe_id')

    op.drop_index('ix_recipes_deleted_at', table_name='recipes')
    op.drop_index('ix_recipes_execution_state', table_name='recipes')
    op.drop_index('ix_recipes_project_id', table_name='recipes')
    op.drop_index('ix_recipes_parent_id', table_name='recipes')
    op.drop_index('ix_recipes_name', table_name='recipes')
    op.drop_index('ix_recipes_id', table_name='recipes')
    op.drop_table('recipes')
