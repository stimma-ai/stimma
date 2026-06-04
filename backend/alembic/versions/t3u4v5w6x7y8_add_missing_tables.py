"""add_missing_tables

Revision ID: t3u4v5w6x7y8
Revises: s2t3u4v5w6x7
Create Date: 2026-01-09

This migration adds tables that were previously only created via
Base.metadata.create_all(). Moving them to alembic ensures it's the
sole source of truth for schema.

Tables added:
- _meta: database-level configuration (db_guid)
- tools: saved generation tool configurations
- pinned_tools: provider tools pinned to sidebar
- tool_state: working state per tool (survives page refresh)
- llm_traces: LLM conversation traces for sub-agents
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 't3u4v5w6x7y8'
down_revision: Union[str, Sequence[str], None] = 's2t3u4v5w6x7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create tables that were missing from alembic migrations."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # _meta: database-level configuration
    if '_meta' not in existing_tables:
        op.create_table(
            '_meta',
            sa.Column('key', sa.String(), nullable=False),
            sa.Column('value', sa.String(), nullable=False),
            sa.PrimaryKeyConstraint('key')
        )

    # tools: saved generation tool configurations
    if 'tools' not in existing_tables:
        op.create_table(
            'tools',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('profile_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('task_type', sa.String(), nullable=False),
            sa.Column('full_tool_id', sa.String(), nullable=True),
            sa.Column('generator', sa.String(), nullable=False),
            sa.Column('model', sa.String(), nullable=False),
            sa.Column('state', sa.String(), nullable=True),
            sa.Column('parameters', sa.String(), nullable=True),
            sa.Column('loras', sa.String(), nullable=True),
            sa.Column('output_folder', sa.String(), nullable=True),
            sa.Column('pinned', sa.Boolean(), nullable=True, default=False),
            sa.Column('pin_order', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True),
            sa.Column('usage_count', sa.Integer(), nullable=True, default=0),
            sa.Column('deleted_at', sa.DateTime(), nullable=True),
            sa.Column('source_media_id', sa.Integer(), nullable=True),
            sa.Column('is_draft', sa.Boolean(), nullable=True, default=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['source_media_id'], ['media_items.id'], ondelete='SET NULL')
        )
        op.create_index('ix_tools_id', 'tools', ['id'])
        op.create_index('ix_tools_profile_id', 'tools', ['profile_id'])
        op.create_index('ix_tools_task_type', 'tools', ['task_type'])
        op.create_index('ix_tools_full_tool_id', 'tools', ['full_tool_id'])
        op.create_index('ix_tools_pinned', 'tools', ['pinned'])
        op.create_index('ix_tools_last_used_at', 'tools', ['last_used_at'])
        op.create_index('ix_tools_deleted_at', 'tools', ['deleted_at'])
        op.create_index('idx_tools_profile_pinned', 'tools', ['profile_id', 'pinned'])

    # pinned_tools: provider tools pinned to sidebar
    if 'pinned_tools' not in existing_tables:
        op.create_table(
            'pinned_tools',
            sa.Column('full_tool_id', sa.String(), nullable=False),
            sa.Column('pin_order', sa.Integer(), nullable=False, default=0),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('name', sa.String(), nullable=True),
            sa.Column('task_type', sa.String(), nullable=True),
            sa.Column('provider_id', sa.String(), nullable=True),
            sa.PrimaryKeyConstraint('full_tool_id')
        )

    # tool_state: working state per tool
    if 'tool_state' not in existing_tables:
        op.create_table(
            'tool_state',
            sa.Column('full_tool_id', sa.String(), nullable=False),
            sa.Column('state', sa.String(), nullable=True),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('full_tool_id')
        )

    # llm_traces: LLM conversation traces
    if 'llm_traces' not in existing_tables:
        op.create_table(
            'llm_traces',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('chat_id', sa.Integer(), nullable=False),
            sa.Column('plan_id', sa.String(), nullable=True),
            sa.Column('trace_type', sa.String(), nullable=False),
            sa.Column('node_id', sa.String(), nullable=True),
            sa.Column('tool_call_id', sa.String(), nullable=True),
            sa.Column('messages', sa.Text(), nullable=False),
            sa.Column('response', sa.Text(), nullable=True),
            sa.Column('model', sa.String(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=True),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['chat_id'], ['chats.id'])
        )
        op.create_index('ix_llm_traces_id', 'llm_traces', ['id'])
        op.create_index('ix_llm_traces_chat_id', 'llm_traces', ['chat_id'])
        op.create_index('ix_llm_traces_plan_id', 'llm_traces', ['plan_id'])
        op.create_index('ix_llm_traces_trace_type', 'llm_traces', ['trace_type'])
        op.create_index('ix_llm_traces_created_at', 'llm_traces', ['created_at'])
        op.create_index('idx_llm_traces_chat_created', 'llm_traces', [sa.text('chat_id'), sa.text('created_at DESC')])


def downgrade() -> None:
    """Drop added tables."""
    op.drop_table('llm_traces')
    op.drop_table('tool_state')
    op.drop_table('pinned_tools')
    op.drop_table('tools')
    op.drop_table('_meta')
