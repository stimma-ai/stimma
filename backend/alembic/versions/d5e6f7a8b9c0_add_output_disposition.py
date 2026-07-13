"""add invocation-specific output disposition

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'asset_migration_state',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('migration_key', sa.String(), nullable=False),
        sa.Column('phase', sa.String(), nullable=False, server_default='expanded'),
        sa.Column('migration_version', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('report_digest', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(), nullable=True),
        sa.Column('completed_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "phase IN ('expanded', 'shadow', 'dual_write', 'asset_reads', 'object_store', 'contracted')",
            name='ck_asset_migration_state_phase',
        ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('migration_key'),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_asset_migration_state_id', 'asset_migration_state', ['id'])
    op.create_index('ix_asset_migration_state_phase', 'asset_migration_state', ['phase'])
    op.create_index('ix_asset_migration_state_deleted_at', 'asset_migration_state', ['deleted_at'])

    with op.batch_alter_table('media_items') as batch_op:
        batch_op.add_column(sa.Column('original_filename', sa.String(), nullable=True))

    with op.batch_alter_table('generation_jobs') as batch_op:
        batch_op.add_column(sa.Column('output_disposition', sa.String(), nullable=False, server_default='asset'))
        batch_op.add_column(sa.Column('output_context_kind', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('output_context_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('result_asset_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_generation_jobs_result_asset_id', 'assets', ['result_asset_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.create_index('ix_generation_jobs_output_disposition', ['output_disposition'])
        batch_op.create_index('ix_generation_jobs_output_context_kind', ['output_context_kind'])
        batch_op.create_index('ix_generation_jobs_output_context_id', ['output_context_id'])
        batch_op.create_index('ix_generation_jobs_result_asset_id', ['result_asset_id'])

    with op.batch_alter_table('chat_items') as batch_op:
        batch_op.add_column(sa.Column('asset_id', sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column('asset_ids', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('show_role', sa.String(), nullable=True))
        batch_op.create_foreign_key(
            'fk_chat_items_asset_id', 'assets', ['asset_id'], ['id'], ondelete='SET NULL'
        )
        batch_op.create_index('ix_chat_items_asset_id', ['asset_id'])
        batch_op.create_index('ix_chat_items_show_role', ['show_role'])


def downgrade() -> None:
    with op.batch_alter_table('chat_items') as batch_op:
        batch_op.drop_index('ix_chat_items_show_role')
        batch_op.drop_index('ix_chat_items_asset_id')
        batch_op.drop_constraint('fk_chat_items_asset_id', type_='foreignkey')
        batch_op.drop_column('show_role')
        batch_op.drop_column('asset_ids')
        batch_op.drop_column('asset_id')

    with op.batch_alter_table('generation_jobs') as batch_op:
        batch_op.drop_index('ix_generation_jobs_result_asset_id')
        batch_op.drop_index('ix_generation_jobs_output_context_id')
        batch_op.drop_index('ix_generation_jobs_output_context_kind')
        batch_op.drop_index('ix_generation_jobs_output_disposition')
        batch_op.drop_constraint('fk_generation_jobs_result_asset_id', type_='foreignkey')
        batch_op.drop_column('result_asset_id')
        batch_op.drop_column('output_context_id')
        batch_op.drop_column('output_context_kind')
        batch_op.drop_column('output_disposition')
    with op.batch_alter_table('media_items') as batch_op:
        batch_op.drop_column('original_filename')
    op.drop_table('asset_migration_state')
