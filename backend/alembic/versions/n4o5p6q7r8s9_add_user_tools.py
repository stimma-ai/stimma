"""add user_tools table (flows frozen into tools)

A frozen flow registered as a first-class tool: ``program_text`` is the runnable
body, ``flow_id`` the editing handle, plus the canonical STP interface
(parameter_schema / output_schema / task_types) and freeze settings
(hitl_policies / output_map). See plans/FLOW_TO_TOOL.md.

Revision ID: n4o5p6q7r8s9
Revises: m3n4o5p6q7r8
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'n4o5p6q7r8s9'
down_revision: Union[str, Sequence[str], None] = 'm3n4o5p6q7r8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'user_tools' in inspector.get_table_names():
        return

    op.create_table(
        'user_tools',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('flow_id', sa.Integer(), sa.ForeignKey('flows.id', ondelete='SET NULL'), nullable=True),
        sa.Column('program_text', sa.Text(), nullable=False),
        sa.Column('task_types', sa.Text(), nullable=True),
        sa.Column('parameter_schema', sa.Text(), nullable=True),
        sa.Column('output_schema', sa.Text(), nullable=True),
        sa.Column('hitl_policies', sa.Text(), nullable=True),
        sa.Column('output_map', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index('ix_user_tools_id', 'user_tools', ['id'])
    op.create_index('ix_user_tools_name', 'user_tools', ['name'])
    op.create_index('ix_user_tools_flow_id', 'user_tools', ['flow_id'])
    op.create_index('ix_user_tools_deleted_at', 'user_tools', ['deleted_at'])


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'user_tools' not in inspector.get_table_names():
        return
    op.drop_table('user_tools')
