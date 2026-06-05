"""add delete operations and thumbnail cache

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector, table_name: str) -> bool:
    return inspector.has_table(table_name)


def _has_index(inspector, table_name: str, index_name: str) -> bool:
    return any(index.get('name') == index_name for index in inspector.get_indexes(table_name))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, 'delete_operations'):
        op.create_table(
            'delete_operations',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('kind', sa.String(), nullable=False),
            sa.Column('profile_id', sa.String(), nullable=False),
            sa.Column('status', sa.String(), nullable=False, server_default='queued'),
            sa.Column('current_phase', sa.String(), nullable=True),
            sa.Column('total_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('claimed_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('processed_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('deleted_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('failed_items', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('started_at', sa.DateTime(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('completed_at', sa.DateTime(), nullable=True),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sqlite_autoincrement=True,
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'delete_operations', 'ix_delete_operations_id'):
        op.create_index('ix_delete_operations_id', 'delete_operations', ['id'])
    if not _has_index(inspector, 'delete_operations', 'ix_delete_operations_profile_id'):
        op.create_index('ix_delete_operations_profile_id', 'delete_operations', ['profile_id'])
    if not _has_index(inspector, 'delete_operations', 'ix_delete_operations_status'):
        op.create_index('ix_delete_operations_status', 'delete_operations', ['status'])

    inspector = sa.inspect(bind)
    if not _has_table(inspector, 'delete_operation_items'):
        op.create_table(
            'delete_operation_items',
            sa.Column('operation_id', sa.Integer(), nullable=False),
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('file_path', sa.String(), nullable=True),
            sa.Column('file_hash', sa.String(), nullable=True),
            sa.Column('state', sa.String(), nullable=False, server_default='pending'),
            sa.Column('lease_expires_at', sa.DateTime(), nullable=True),
            sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
            sa.Column('last_error', sa.Text(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['operation_id'], ['delete_operations.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('operation_id', 'media_id'),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'delete_operation_items', 'ix_delete_operation_items_media_id'):
        op.create_index('ix_delete_operation_items_media_id', 'delete_operation_items', ['media_id'])
    if not _has_index(inspector, 'delete_operation_items', 'ix_delete_operation_items_state'):
        op.create_index('ix_delete_operation_items_state', 'delete_operation_items', ['state'])
    if not _has_index(inspector, 'delete_operation_items', 'ix_delete_operation_items_lease_expires_at'):
        op.create_index('ix_delete_operation_items_lease_expires_at', 'delete_operation_items', ['lease_expires_at'])
    if not _has_index(inspector, 'delete_operation_items', 'idx_delete_operation_items_state'):
        op.create_index(
            'idx_delete_operation_items_state',
            'delete_operation_items',
            ['operation_id', 'state', 'lease_expires_at'],
        )

    inspector = sa.inspect(bind)
    if not _has_table(inspector, 'media_thumbnail_cache'):
        op.create_table(
            'media_thumbnail_cache',
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('cache_path', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE'),
            sa.PrimaryKeyConstraint('media_id', 'cache_path'),
        )
        inspector = sa.inspect(bind)
    if not _has_index(inspector, 'media_thumbnail_cache', 'idx_media_thumbnail_cache_media'):
        op.create_index('idx_media_thumbnail_cache_media', 'media_thumbnail_cache', ['media_id'])


def downgrade() -> None:
    op.drop_index('idx_media_thumbnail_cache_media', table_name='media_thumbnail_cache')
    op.drop_table('media_thumbnail_cache')

    op.drop_index('idx_delete_operation_items_state', table_name='delete_operation_items')
    op.drop_index('ix_delete_operation_items_lease_expires_at', table_name='delete_operation_items')
    op.drop_index('ix_delete_operation_items_state', table_name='delete_operation_items')
    op.drop_index('ix_delete_operation_items_media_id', table_name='delete_operation_items')
    op.drop_table('delete_operation_items')

    op.drop_index('ix_delete_operations_status', table_name='delete_operations')
    op.drop_index('ix_delete_operations_profile_id', table_name='delete_operations')
    op.drop_index('ix_delete_operations_id', table_name='delete_operations')
    op.drop_table('delete_operations')
