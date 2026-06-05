"""add_tool_id_to_generation_jobs

Revision ID: m6n7o8p9q0r1
Revises: l5m6n7o8p9q0
Create Date: 2025-12-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'm6n7o8p9q0r1'
down_revision: Union[str, Sequence[str], None] = 'l5m6n7o8p9q0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add tool_id column to generation_jobs table."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table exists first (for fresh databases)
    if 'generation_jobs' not in inspector.get_table_names():
        print("generation_jobs table does not exist yet, skipping migration")
        return

    # Check if column already exists
    existing_columns = [col['name'] for col in inspector.get_columns('generation_jobs')]

    if 'tool_id' not in existing_columns:
        op.add_column('generation_jobs', sa.Column('tool_id', sa.Integer(), nullable=True))
        op.create_index('ix_generation_jobs_tool_id', 'generation_jobs', ['tool_id'], unique=False)
        print("Successfully added tool_id column to generation_jobs")
    else:
        print("tool_id column already exists, skipping")


def downgrade() -> None:
    """Remove tool_id column from generation_jobs table."""
    op.drop_index('ix_generation_jobs_tool_id', table_name='generation_jobs')
    op.drop_column('generation_jobs', 'tool_id')
