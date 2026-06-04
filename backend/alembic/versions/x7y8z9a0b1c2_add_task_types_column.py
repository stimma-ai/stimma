"""add task_types column to cached_provider_tools and pinned_tools

Revision ID: x7y8z9a0b1c2
Revises: w6x7y8z9a0b1
Create Date: 2026-01-27 01:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'x7y8z9a0b1c2'
down_revision: Union[str, Sequence[str], None] = 'w6x7y8z9a0b1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add task_types column to cached_provider_tools and pinned_tools.

    This column stores a JSON array of task types that a tool supports,
    enabling tools to appear in multiple UI categories.
    """
    # Add task_types to cached_provider_tools (stores JSON array like '["text-to-image", "image-edit"]')
    op.add_column('cached_provider_tools', sa.Column('task_types', sa.String(), nullable=True))

    # Add task_types to pinned_tools
    op.add_column('pinned_tools', sa.Column('task_types', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove task_types columns."""
    op.drop_column('pinned_tools', 'task_types')
    op.drop_column('cached_provider_tools', 'task_types')
