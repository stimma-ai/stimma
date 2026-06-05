"""add profile_id to generation_jobs

Revision ID: a1b2c3d4e5f6
Revises: c334cf9d4497
Create Date: 2025-11-27 06:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'c334cf9d4497'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add profile_id column to generation_jobs for multi-profile support."""
    # Add profile_id column with default value
    op.add_column('generation_jobs', sa.Column('profile_id', sa.String(), nullable=True))

    # Set default value for existing rows
    op.execute("UPDATE generation_jobs SET profile_id = 'default' WHERE profile_id IS NULL")

    # Create index on profile_id
    op.create_index('ix_generation_jobs_profile_id', 'generation_jobs', ['profile_id'])


def downgrade() -> None:
    """Remove profile_id column from generation_jobs."""
    op.drop_index('ix_generation_jobs_profile_id', table_name='generation_jobs')
    op.drop_column('generation_jobs', 'profile_id')
