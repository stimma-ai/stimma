"""add_chat_system

Revision ID: ef7002cbcc17
Revises: 74838ff202c3
Create Date: 2025-11-23 22:04:42.770845

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ef7002cbcc17'
down_revision: Union[str, Sequence[str], None] = '74838ff202c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add chat system."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # 1. Create chats table if it doesn't exist
    if 'chats' not in existing_tables:
        op.create_table(
            'chats',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),

            # Forking support
            sa.Column('original_chatitem_id', sa.Integer(), nullable=True),

            # Per-chat settings
            sa.Column('throttle', sa.String(), nullable=True, server_default='off'),

            # Locked generation parameters
            sa.Column('locked_width', sa.Integer(), nullable=True),
            sa.Column('locked_height', sa.Integer(), nullable=True),
            sa.Column('locked_cfg', sa.Float(), nullable=True),
            sa.Column('locked_sampler', sa.String(), nullable=True),
            sa.Column('locked_scheduler', sa.String(), nullable=True),
            sa.Column('locked_shift', sa.Float(), nullable=True),
            sa.Column('locked_denoise', sa.Float(), nullable=True),
            sa.Column('locked_steps', sa.Integer(), nullable=True),
            sa.Column('locked_negative_prompt', sa.String(), nullable=True),
            sa.Column('locked_output_folder', sa.String(), nullable=True),
            sa.Column('locked_loras', sa.String(), nullable=True),  # JSON
            sa.Column('available_loras', sa.String(), nullable=True),  # JSON

            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_chats_id', 'chats', ['id'])
        op.create_index('ix_chats_created_at', 'chats', ['created_at'], postgresql_ops={'created_at': 'DESC'})
        op.create_index('ix_chats_updated_at', 'chats', ['updated_at'], postgresql_ops={'updated_at': 'DESC'})
        op.create_index('ix_chats_deleted_at', 'chats', ['deleted_at'])

    # 2. Create chat_items table if it doesn't exist
    if 'chat_items' not in existing_tables:
        op.create_table(
            'chat_items',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('chat_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),

            # Item type and content
            sa.Column('item_type', sa.String(), nullable=False),
            sa.Column('message_text', sa.String(), nullable=True),

            # Tool call fields
            sa.Column('tool_name', sa.String(), nullable=True),
            sa.Column('tool_call_id', sa.String(), nullable=True),
            sa.Column('tool_args', sa.String(), nullable=True),  # JSON

            # Tool result fields
            sa.Column('tool_result', sa.String(), nullable=True),  # JSON
            sa.Column('tool_error', sa.String(), nullable=True),

            # Media fields
            sa.Column('media_id', sa.Integer(), nullable=True),
            sa.Column('media_ids', sa.String(), nullable=True),  # JSON
            sa.Column('grid_layout', sa.String(), nullable=True),  # JSON

            # Settings change
            sa.Column('settings_changed', sa.String(), nullable=True),  # JSON

            # Threading
            sa.Column('parent_item_id', sa.Integer(), nullable=True),

            # Extensibility
            sa.Column('item_metadata', sa.String(), nullable=True),  # JSON

            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['chat_id'], ['chats.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['parent_item_id'], ['chat_items.id'], ondelete='SET NULL')
        )
        op.create_index('ix_chat_items_id', 'chat_items', ['id'])
        op.create_index('ix_chat_items_chat_id_created_at', 'chat_items', ['chat_id', 'created_at'])
        op.create_index('ix_chat_items_item_type', 'chat_items', ['item_type'])
        op.create_index('ix_chat_items_media_id', 'chat_items', ['media_id'])
        op.create_index('ix_chat_items_tool_call_id', 'chat_items', ['tool_call_id'])

    # 3. Add chat_item_id column to media_items (if it doesn't exist)
    existing_columns = [col['name'] for col in inspector.get_columns('media_items')]
    if 'chat_item_id' not in existing_columns:
        op.add_column('media_items', sa.Column('chat_item_id', sa.Integer(), nullable=True))
        op.create_index('ix_media_items_chat_item_id', 'media_items', ['chat_item_id'])

    # Add foreign key constraint for chats.original_chatitem_id
    # Note: SQLite doesn't support adding FK constraints after table creation,
    # but we document the relationship for clarity

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))

    print("Successfully added chat system tables and columns")


def downgrade() -> None:
    """Downgrade schema - remove chat system."""

    # Remove in reverse order
    op.drop_index('ix_media_items_chat_item_id', 'media_items')
    op.drop_column('media_items', 'chat_item_id')

    op.drop_index('ix_chat_items_tool_call_id', 'chat_items')
    op.drop_index('ix_chat_items_media_id', 'chat_items')
    op.drop_index('ix_chat_items_item_type', 'chat_items')
    op.drop_index('ix_chat_items_chat_id_created_at', 'chat_items')
    op.drop_index('ix_chat_items_id', 'chat_items')
    op.drop_table('chat_items')

    op.drop_index('ix_chats_deleted_at', 'chats')
    op.drop_index('ix_chats_updated_at', 'chats')
    op.drop_index('ix_chats_created_at', 'chats')
    op.drop_index('ix_chats_id', 'chats')
    op.drop_table('chats')
