"""add task_type and task_defaults

Revision ID: c334cf9d4497
Revises: 7aa5bdad5e79
Create Date: 2025-11-25 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c334cf9d4497'
down_revision: Union[str, Sequence[str], None] = '7aa5bdad5e79'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add task_type column to generation_jobs
    op.add_column('generation_jobs', sa.Column('task_type', sa.String(), nullable=True))

    # Set default value for existing rows
    op.execute("UPDATE generation_jobs SET task_type = 'text-to-image' WHERE task_type IS NULL")

    # Create index on task_type
    op.create_index('ix_generation_jobs_task_type', 'generation_jobs', ['task_type'])

    # Create task_defaults table
    op.create_table(
        'task_defaults',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('task_type', sa.String(), nullable=False, index=True),
        sa.Column('scope', sa.String(), nullable=False, server_default='global'),
        sa.Column('parameters', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
    )

    # Create unique index on task_type + scope
    op.create_index(
        'idx_task_defaults_task_scope',
        'task_defaults',
        ['task_type', 'scope'],
        unique=True
    )


def downgrade() -> None:
    """Downgrade schema."""
    # Drop task_defaults table
    op.drop_index('idx_task_defaults_task_scope', table_name='task_defaults')
    op.drop_table('task_defaults')

    # Remove task_type from generation_jobs
    op.drop_index('ix_generation_jobs_task_type', table_name='generation_jobs')
    op.drop_column('generation_jobs', 'task_type')
