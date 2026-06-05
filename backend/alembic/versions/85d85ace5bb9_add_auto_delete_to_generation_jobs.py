"""add_auto_delete_to_generation_jobs

Revision ID: 85d85ace5bb9
Revises: e4faa9985d69
Create Date: 2025-11-21 20:56:03.932266

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '85d85ace5bb9'
down_revision: Union[str, Sequence[str], None] = 'e4faa9985d69'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add auto_delete_duration column to generation_jobs
    op.add_column('generation_jobs', sa.Column('auto_delete_duration', sa.String(), nullable=True))

    # Add auto_delete_at column to generation_jobs
    op.add_column('generation_jobs', sa.Column('auto_delete_at', sa.DateTime(), nullable=True))

    # Create index for auto_delete_at to optimize cleanup queries
    op.create_index('ix_generation_jobs_auto_delete_at', 'generation_jobs', ['auto_delete_at'])


def downgrade() -> None:
    """Downgrade schema."""
    # Drop index
    op.drop_index('ix_generation_jobs_auto_delete_at', 'generation_jobs')

    # Drop columns
    op.drop_column('generation_jobs', 'auto_delete_at')
    op.drop_column('generation_jobs', 'auto_delete_duration')
