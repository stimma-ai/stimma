"""add_batch_fields_to_generation_jobs

Revision ID: c2d3e4f5g6h7
Revises: b1c2d3e4f5g6
Create Date: 2026-01-31

Add batch processing fields to generation_jobs table.
These enable processing sets of images through tools in batch,
with jobs sharing a batch_id and results collected into an output set.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c2d3e4f5g6h7'
down_revision: Union[str, Sequence[str], None] = 'b1c2d3e4f5g6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add batch_id, batch_total, batch_output_set_id to generation_jobs."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('generation_jobs')]

    if 'batch_id' not in columns:
        op.add_column(
            'generation_jobs',
            sa.Column('batch_id', sa.String(), nullable=True)
        )
        op.create_index('ix_generation_jobs_batch_id', 'generation_jobs', ['batch_id'])

    if 'batch_total' not in columns:
        op.add_column(
            'generation_jobs',
            sa.Column('batch_total', sa.Integer(), nullable=True)
        )

    if 'batch_output_set_id' not in columns:
        op.add_column(
            'generation_jobs',
            sa.Column('batch_output_set_id', sa.Integer(), nullable=True)
        )


def downgrade() -> None:
    """Remove batch fields from generation_jobs."""
    op.drop_index('ix_generation_jobs_batch_id', 'generation_jobs')
    op.drop_column('generation_jobs', 'batch_output_set_id')
    op.drop_column('generation_jobs', 'batch_total')
    op.drop_column('generation_jobs', 'batch_id')
