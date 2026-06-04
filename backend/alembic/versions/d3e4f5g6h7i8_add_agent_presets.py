"""Add agent presets table and chat agent settings columns

Revision ID: d3e4f5g6h7i8
Revises: c2d3e4f5g6h7
Create Date: 2025-02-01

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd3e4f5g6h7i8'
down_revision = 'c2d3e4f5g6h7'
branch_labels = None
depends_on = None


def upgrade():
    # Create agent_presets table
    op.create_table(
        'agent_presets',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('profile_id', sa.String(), nullable=False, index=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('additional_instructions', sa.Text(), nullable=True),
        sa.Column('tool_config', sa.String(), nullable=True),  # JSON
        sa.Column('is_default', sa.Boolean(), default=False, index=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True, index=True),
        sqlite_autoincrement=True,
    )

    # Create composite index for profile + default lookup
    op.create_index(
        'idx_agent_presets_profile_default',
        'agent_presets',
        ['profile_id', 'is_default']
    )

    # Add agent settings columns to chats table
    op.add_column('chats', sa.Column('additional_instructions', sa.Text(), nullable=True))
    op.add_column('chats', sa.Column('agent_tool_config', sa.String(), nullable=True))
    op.add_column('chats', sa.Column('agent_preset_id', sa.Integer(), nullable=True))
    op.add_column('chats', sa.Column('agent_preset_modified', sa.Boolean(), default=False))

    # Create index on agent_preset_id
    op.create_index('idx_chats_agent_preset_id', 'chats', ['agent_preset_id'])


def downgrade():
    # Remove index and columns from chats
    op.drop_index('idx_chats_agent_preset_id', table_name='chats')
    op.drop_column('chats', 'agent_preset_modified')
    op.drop_column('chats', 'agent_preset_id')
    op.drop_column('chats', 'agent_tool_config')
    op.drop_column('chats', 'additional_instructions')

    # Drop agent_presets table
    op.drop_index('idx_agent_presets_profile_default', table_name='agent_presets')
    op.drop_table('agent_presets')
