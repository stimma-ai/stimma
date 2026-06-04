"""replace collections with boards

Revision ID: a9b8c7d6e5f4
Revises: z9a0b1c2d3e4
Create Date: 2026-04-03
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a9b8c7d6e5f4'
down_revision: Union[str, Sequence[str], None] = 'z9a0b1c2d3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'boards',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_boards_id', 'boards', ['id'])
    op.create_index('ix_boards_name', 'boards', ['name'])
    op.create_index('ix_boards_deleted_at', 'boards', ['deleted_at'])

    op.create_table(
        'board_sections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('board_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('is_default', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('is_collapsed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['board_id'], ['boards.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_board_sections_id', 'board_sections', ['id'])
    op.create_index('ix_board_sections_deleted_at', 'board_sections', ['deleted_at'])
    op.create_index('ix_board_sections_board_id', 'board_sections', ['board_id'])
    op.create_index('ix_board_sections_is_default', 'board_sections', ['is_default'])
    op.create_index('idx_board_sections_board_order', 'board_sections', ['board_id', 'display_order'])

    op.create_table(
        'board_items',
        sa.Column('board_section_id', sa.Integer(), nullable=False),
        sa.Column('media_id', sa.Integer(), nullable=False),
        sa.Column('display_order', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['board_section_id'], ['board_sections.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('board_section_id', 'media_id'),
    )
    op.create_index('idx_board_items_section_order', 'board_items', ['board_section_id', 'display_order'])
    op.create_index('idx_board_items_media', 'board_items', ['media_id'])

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if 'media_collections' in tables:
        op.drop_index('idx_media_collection', table_name='media_collections')
        op.drop_index('idx_collection_media', table_name='media_collections')
        op.drop_table('media_collections')

    if 'collections' in tables:
        for index_name in ('ix_collections_deleted_at', 'ix_collections_name', 'ix_collections_id'):
            existing_indexes = {idx['name'] for idx in inspector.get_indexes('collections')}
            if index_name in existing_indexes:
                op.drop_index(index_name, table_name='collections')
        op.drop_table('collections')


def downgrade() -> None:
    op.drop_index('idx_board_items_media', table_name='board_items')
    op.drop_index('idx_board_items_section_order', table_name='board_items')
    op.drop_table('board_items')

    op.drop_index('idx_board_sections_board_order', table_name='board_sections')
    op.drop_index('ix_board_sections_is_default', table_name='board_sections')
    op.drop_index('ix_board_sections_board_id', table_name='board_sections')
    op.drop_index('ix_board_sections_deleted_at', table_name='board_sections')
    op.drop_index('ix_board_sections_id', table_name='board_sections')
    op.drop_table('board_sections')

    op.drop_index('ix_boards_deleted_at', table_name='boards')
    op.drop_index('ix_boards_name', table_name='boards')
    op.drop_index('ix_boards_id', table_name='boards')
    op.drop_table('boards')
