"""add_cached_provider_tools_table

Revision ID: s2t3u4v5w6x7
Revises: r1s2t3u4v5w6
Create Date: 2026-01-04

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 's2t3u4v5w6x7'
down_revision: Union[str, Sequence[str], None] = 'r1s2t3u4v5w6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create cached_provider_tools table for offline tool display."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if 'cached_provider_tools' not in inspector.get_table_names():
        op.create_table(
            'cached_provider_tools',
            sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column('full_tool_id', sa.String(), nullable=False, unique=True, index=True),
            sa.Column('provider_id', sa.String(), nullable=False, index=True),
            sa.Column('provider_name', sa.String(), nullable=True),
            sa.Column('tool_id', sa.String(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('task_type', sa.String(), nullable=True, index=True),
            sa.Column('parameter_schema', sa.String(), nullable=True),
            sa.Column('input_schema', sa.String(), nullable=True),
            sa.Column('output_schema', sa.String(), nullable=True),
            sa.Column('tool_metadata', sa.String(), nullable=True),
            sa.Column('last_registered_at', sa.DateTime(), nullable=False),
            sa.Column('deleted_at', sa.DateTime(), nullable=True, index=True),
            sqlite_autoincrement=True,
        )
        op.create_index('idx_cached_tools_provider', 'cached_provider_tools', ['provider_id'])


def downgrade() -> None:
    """Drop cached_provider_tools table."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if 'cached_provider_tools' in inspector.get_table_names():
        op.drop_table('cached_provider_tools')
