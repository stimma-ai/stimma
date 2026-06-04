"""add projects

Revision ID: a1f2e3d4c5b6
Revises: f0e1d2c3b4a5
Create Date: 2026-04-04 12:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a1f2e3d4c5b6'
down_revision = 'f0e1d2c3b4a5'
branch_labels = None
depends_on = None


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def _has_column(inspector, table_name: str, column_name: str) -> bool:
    return any(column.get('name') == column_name for column in inspector.get_columns(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table('projects'):
        op.create_table(
            'projects',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.Text(), nullable=True),
            sa.Column('root_path', sa.String(), nullable=True),
            sa.Column('additional_instructions', sa.Text(), nullable=True),
            sa.Column('agent_tool_config', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sqlite_autoincrement=True,
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'projects', 'ix_projects_id'):
        op.create_index('ix_projects_id', 'projects', ['id'])
    if not _has_index(inspector, 'projects', 'ix_projects_name'):
        op.create_index('ix_projects_name', 'projects', ['name'])
    if not _has_index(inspector, 'projects', 'ix_projects_created_at'):
        op.create_index('ix_projects_created_at', 'projects', ['created_at'])
    if not _has_index(inspector, 'projects', 'ix_projects_updated_at'):
        op.create_index('ix_projects_updated_at', 'projects', ['updated_at'])
    if not _has_index(inspector, 'projects', 'ix_projects_deleted_at'):
        op.create_index('ix_projects_deleted_at', 'projects', ['deleted_at'])

    inspector = sa.inspect(bind)
    if not inspector.has_table('project_media'):
        op.create_table(
            'project_media',
            sa.Column('project_id', sa.Integer(), nullable=False),
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('added_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('project_id', 'media_id'),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'project_media', 'idx_project_media_media'):
        op.create_index('idx_project_media_media', 'project_media', ['media_id'])
    if not _has_index(inspector, 'project_media', 'idx_project_media_project_added'):
        op.create_index('idx_project_media_project_added', 'project_media', ['project_id', 'added_at'])

    inspector = sa.inspect(bind)
    if not _has_column(inspector, 'chats', 'project_id'):
        op.add_column('chats', sa.Column('project_id', sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'chats', 'ix_chats_project_id'):
        op.create_index('ix_chats_project_id', 'chats', ['project_id'])

    inspector = sa.inspect(bind)
    if not _has_column(inspector, 'boards', 'project_id'):
        op.add_column('boards', sa.Column('project_id', sa.Integer(), nullable=True))
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'boards', 'ix_boards_project_id'):
        op.create_index('ix_boards_project_id', 'boards', ['project_id'])


def downgrade() -> None:
    op.drop_index('ix_boards_project_id', table_name='boards')
    op.drop_column('boards', 'project_id')

    op.drop_index('ix_chats_project_id', table_name='chats')
    op.drop_column('chats', 'project_id')

    op.drop_index('idx_project_media_project_added', table_name='project_media')
    op.drop_index('idx_project_media_media', table_name='project_media')
    op.drop_table('project_media')

    op.drop_index('ix_projects_deleted_at', table_name='projects')
    op.drop_index('ix_projects_updated_at', table_name='projects')
    op.drop_index('ix_projects_created_at', table_name='projects')
    op.drop_index('ix_projects_name', table_name='projects')
    op.drop_index('ix_projects_id', table_name='projects')
    op.drop_table('projects')
