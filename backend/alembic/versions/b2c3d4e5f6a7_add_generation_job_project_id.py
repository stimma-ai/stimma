"""add_generation_job_project_id

Revision ID: b2c3d4e5f6a7
Revises: a1f2e3d4c5b6
Create Date: 2026-04-05

Add project_id column to generation_jobs table so generated media
can be automatically associated with a project.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1f2e3d4c5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add project_id column to generation_jobs."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('generation_jobs')]

    if 'project_id' not in columns:
        op.add_column('generation_jobs', sa.Column('project_id', sa.Integer(), nullable=True))
        op.create_index('ix_generation_jobs_project_id', 'generation_jobs', ['project_id'])


def downgrade() -> None:
    """Remove project_id column from generation_jobs."""
    op.drop_index('ix_generation_jobs_project_id', table_name='generation_jobs')
    op.drop_column('generation_jobs', 'project_id')
