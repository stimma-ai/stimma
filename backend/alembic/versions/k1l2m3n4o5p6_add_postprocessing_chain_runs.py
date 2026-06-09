"""add_postprocessing_chain_runs

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-06-09

Post-processing chain runs: one row per chain execution after a base
generation. Persists per-step progress for the UI and the pause-on-failure
state (last good media + failed step index) that Retry resumes from.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k1l2m3n4o5p6'
down_revision: Union[str, Sequence[str], None] = 'j0k1l2m3n4o5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create postprocessing_chain_runs table."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'postprocessing_chain_runs' in inspector.get_table_names():
        return

    op.create_table(
        'postprocessing_chain_runs',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('job_id', sa.Integer(), nullable=False),
        sa.Column('base_media_id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('chain', sa.Text(), nullable=False),
        sa.Column('step_index', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('step_count', sa.Integer(), nullable=False),
        sa.Column('step_results', sa.Text(), nullable=True),
        sa.Column('status', sa.String(), nullable=False, server_default='running'),
        sa.Column('last_good_media_id', sa.Integer(), nullable=True),
        sa.Column('final_media_id', sa.Integer(), nullable=True),
        sa.Column('error', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_postprocessing_chain_runs_job_id', 'postprocessing_chain_runs', ['job_id'])
    op.create_index('ix_postprocessing_chain_runs_status', 'postprocessing_chain_runs', ['status'])
    op.create_index('ix_postprocessing_chain_runs_created_at', 'postprocessing_chain_runs', ['created_at'])


def downgrade() -> None:
    """Drop postprocessing_chain_runs table."""
    op.drop_table('postprocessing_chain_runs')
