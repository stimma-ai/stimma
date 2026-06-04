"""add_project_memory

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-06

Add memory column to projects table for persistent agent memory.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add memory column to projects."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    columns = [col['name'] for col in inspector.get_columns('projects')]

    if 'memory' not in columns:
        op.add_column('projects', sa.Column('memory', sa.Text(), nullable=True))


def downgrade() -> None:
    """Remove memory column from projects."""
    op.drop_column('projects', 'memory')
