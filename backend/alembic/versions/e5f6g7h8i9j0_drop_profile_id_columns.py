"""drop_profile_id_columns

Revision ID: e5f6g7h8i9j0
Revises: c451a6ace286
Create Date: 2026-02-12

Drop profile_id column from generation_jobs, saved_views, tools, presets,
and agent_presets tables. Replace composite indexes that included profile_id
with simpler indexes.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f6g7h8i9j0'
down_revision: Union[str, Sequence[str], None] = 'c451a6ace286'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _index_exists(connection, table_name, index_name):
    inspector = sa.inspect(connection)
    return index_name in [idx['name'] for idx in inspector.get_indexes(table_name)]


def _column_exists(connection, table_name, column_name):
    inspector = sa.inspect(connection)
    return column_name in [col['name'] for col in inspector.get_columns(table_name)]


def upgrade() -> None:
    """Drop profile_id columns and replace composite indexes."""

    connection = op.get_bind()

    # Clean up any leftover temp tables from a previous failed batch_alter_table
    inspector = sa.inspect(connection)
    for table in inspector.get_table_names():
        if table.startswith('_alembic_tmp_'):
            op.execute(sa.text(f'DROP TABLE "{table}"'))

    # generation_jobs: drop profile_id column and its index
    with op.batch_alter_table('generation_jobs') as batch_op:
        if _index_exists(connection, 'generation_jobs', 'ix_generation_jobs_profile_id'):
            batch_op.drop_index('ix_generation_jobs_profile_id')
        if _column_exists(connection, 'generation_jobs', 'profile_id'):
            batch_op.drop_column('profile_id')

    # saved_views: drop profile_id column and its index
    with op.batch_alter_table('saved_views') as batch_op:
        if _index_exists(connection, 'saved_views', 'ix_saved_views_profile_id'):
            batch_op.drop_index('ix_saved_views_profile_id')
        if _column_exists(connection, 'saved_views', 'profile_id'):
            batch_op.drop_column('profile_id')

    # tools: drop profile_id column, replace composite index
    with op.batch_alter_table('tools') as batch_op:
        if _index_exists(connection, 'tools', 'idx_tools_profile_pinned'):
            batch_op.drop_index('idx_tools_profile_pinned')
        if _index_exists(connection, 'tools', 'ix_tools_profile_id'):
            batch_op.drop_index('ix_tools_profile_id')
        if _column_exists(connection, 'tools', 'profile_id'):
            batch_op.drop_column('profile_id')
        if not _index_exists(connection, 'tools', 'idx_tools_pinned'):
            batch_op.create_index('idx_tools_pinned', ['pinned'])

    # presets: drop profile_id column, replace composite indexes
    with op.batch_alter_table('presets') as batch_op:
        if _index_exists(connection, 'presets', 'idx_presets_profile_tool'):
            batch_op.drop_index('idx_presets_profile_tool')
        if _index_exists(connection, 'presets', 'idx_presets_profile_pinned'):
            batch_op.drop_index('idx_presets_profile_pinned')
        if _index_exists(connection, 'presets', 'ix_presets_profile_id'):
            batch_op.drop_index('ix_presets_profile_id')
        if _column_exists(connection, 'presets', 'profile_id'):
            batch_op.drop_column('profile_id')
        if not _index_exists(connection, 'presets', 'idx_presets_tool'):
            batch_op.create_index('idx_presets_tool', ['tool_id'])
        if not _index_exists(connection, 'presets', 'idx_presets_pinned'):
            batch_op.create_index('idx_presets_pinned', ['pinned'])

    # agent_presets: drop profile_id column, replace composite index
    with op.batch_alter_table('agent_presets') as batch_op:
        if _index_exists(connection, 'agent_presets', 'idx_agent_presets_profile_default'):
            batch_op.drop_index('idx_agent_presets_profile_default')
        if _index_exists(connection, 'agent_presets', 'ix_agent_presets_profile_id'):
            batch_op.drop_index('ix_agent_presets_profile_id')
        if _column_exists(connection, 'agent_presets', 'profile_id'):
            batch_op.drop_column('profile_id')
        if not _index_exists(connection, 'agent_presets', 'idx_agent_presets_default'):
            batch_op.create_index('idx_agent_presets_default', ['is_default'])


def downgrade() -> None:
    """Re-add profile_id columns and restore composite indexes."""

    with op.batch_alter_table('agent_presets') as batch_op:
        batch_op.drop_index('idx_agent_presets_default')
        batch_op.add_column(sa.Column('profile_id', sa.String(), nullable=False, server_default='default'))
        batch_op.create_index('ix_agent_presets_profile_id', ['profile_id'])
        batch_op.create_index('idx_agent_presets_profile_default', ['profile_id', 'is_default'])

    with op.batch_alter_table('presets') as batch_op:
        batch_op.drop_index('idx_presets_pinned')
        batch_op.drop_index('idx_presets_tool')
        batch_op.add_column(sa.Column('profile_id', sa.String(), nullable=False, server_default='default'))
        batch_op.create_index('ix_presets_profile_id', ['profile_id'])
        batch_op.create_index('idx_presets_profile_tool', ['profile_id', 'tool_id'])
        batch_op.create_index('idx_presets_profile_pinned', ['profile_id', 'pinned'])

    with op.batch_alter_table('tools') as batch_op:
        batch_op.drop_index('idx_tools_pinned')
        batch_op.add_column(sa.Column('profile_id', sa.String(), nullable=False, server_default='default'))
        batch_op.create_index('ix_tools_profile_id', ['profile_id'])
        batch_op.create_index('idx_tools_profile_pinned', ['profile_id', 'pinned'])

    with op.batch_alter_table('saved_views') as batch_op:
        batch_op.add_column(sa.Column('profile_id', sa.String(), nullable=False, server_default='default'))
        batch_op.create_index('ix_saved_views_profile_id', ['profile_id'])

    with op.batch_alter_table('generation_jobs') as batch_op:
        batch_op.add_column(sa.Column('profile_id', sa.String(), nullable=False, server_default='default'))
        batch_op.create_index('ix_generation_jobs_profile_id', ['profile_id'])
