"""Add metadata columns to pinned_tools

Revision ID: p9q0r1s2t3u4
Revises: o8p9q0r1s2t3
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'p9q0r1s2t3u4'
down_revision = 'o8p9q0r1s2t3'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add metadata columns to pinned_tools
    # These store tool info so we can display it even when providers aren't ready
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Skip if table doesn't exist (will be created by later migration with columns included)
    if 'pinned_tools' not in inspector.get_table_names():
        return

    existing_columns = [col['name'] for col in inspector.get_columns('pinned_tools')]

    if 'name' not in existing_columns:
        op.add_column('pinned_tools', sa.Column('name', sa.String(), nullable=True))
    if 'task_type' not in existing_columns:
        op.add_column('pinned_tools', sa.Column('task_type', sa.String(), nullable=True))
    if 'provider_id' not in existing_columns:
        op.add_column('pinned_tools', sa.Column('provider_id', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('pinned_tools', 'provider_id')
    op.drop_column('pinned_tools', 'task_type')
    op.drop_column('pinned_tools', 'name')
