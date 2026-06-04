"""toolsv3_presets_and_full_tool_id

Add Preset table and full_tool_id column to tools for toolsv3 provider system.

Revision ID: n7o8p9q0r1s2
Revises: m6n7o8p9q0r1
Create Date: 2025-12-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n7o8p9q0r1s2'
down_revision: Union[str, Sequence[str], None] = 'm6n7o8p9q0r1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add presets table and full_tool_id column to tools."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # 1. Add full_tool_id column to tools table
    if 'tools' in inspector.get_table_names():
        existing_columns = [col['name'] for col in inspector.get_columns('tools')]

        if 'full_tool_id' not in existing_columns:
            op.add_column('tools', sa.Column('full_tool_id', sa.String(), nullable=True))
            op.create_index('ix_tools_full_tool_id', 'tools', ['full_tool_id'], unique=False)
            print("Successfully added full_tool_id column to tools")
        else:
            print("full_tool_id column already exists, skipping")
    else:
        print("tools table does not exist yet, skipping full_tool_id")

    # 2. Create presets table if it doesn't exist
    if 'presets' not in inspector.get_table_names():
        op.create_table(
            'presets',
            sa.Column('id', sa.Integer(), primary_key=True),
            sa.Column('profile_id', sa.String(), nullable=False, index=True),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('tool_id', sa.String(), nullable=False, index=True),
            sa.Column('state', sa.String(), nullable=True),
            sa.Column('pinned', sa.Boolean(), default=False, index=True),
            sa.Column('pin_order', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.Column('last_used_at', sa.DateTime(), nullable=True, index=True),
            sa.Column('usage_count', sa.Integer(), default=0),
            sa.Column('deleted_at', sa.DateTime(), nullable=True, index=True),
        )

        # Create composite indexes
        op.create_index('idx_presets_profile_tool', 'presets', ['profile_id', 'tool_id'])
        op.create_index('idx_presets_profile_pinned', 'presets', ['profile_id', 'pinned'])

        print("Successfully created presets table")
    else:
        print("presets table already exists, skipping")

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))


def downgrade() -> None:
    """Remove presets table and full_tool_id column from tools."""
    # Drop presets table
    op.drop_index('idx_presets_profile_pinned', table_name='presets')
    op.drop_index('idx_presets_profile_tool', table_name='presets')
    op.drop_table('presets')

    # Drop full_tool_id column from tools
    op.drop_index('ix_tools_full_tool_id', table_name='tools')
    op.drop_column('tools', 'full_tool_id')
