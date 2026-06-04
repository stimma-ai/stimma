"""add_generator_instance_and_backend_fields

Revision ID: 74838ff202c3
Revises: 5fb0ce052e5a
Create Date: 2025-11-23 21:03:40.654215

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '74838ff202c3'
down_revision: Union[str, Sequence[str], None] = '5fb0ce052e5a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add new columns for generator instance tracking and backend management
    with op.batch_alter_table('generation_jobs') as batch_op:
        batch_op.add_column(sa.Column('generator_instance_id', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('backend_name', sa.String(), nullable=True))
        batch_op.add_column(sa.Column('worker_id', sa.String(), nullable=True))
        batch_op.create_index('ix_generation_jobs_generator_instance_id', ['generator_instance_id'])
        batch_op.create_index('ix_generation_jobs_backend_name', ['backend_name'])

    # Migrate existing jobs to use 'legacy-generate-tab' as generator_instance_id
    # and copy generator_name to backend_name for backward compatibility
    op.execute("""
        UPDATE generation_jobs
        SET generator_instance_id = 'legacy-generate-tab',
            backend_name = generator_name
        WHERE generator_instance_id IS NULL
    """)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('generation_jobs') as batch_op:
        batch_op.drop_index('ix_generation_jobs_backend_name')
        batch_op.drop_index('ix_generation_jobs_generator_instance_id')
        batch_op.drop_column('worker_id')
        batch_op.drop_column('backend_name')
        batch_op.drop_column('generator_instance_id')
