"""add user preferences table

Revision ID: 9e53026276a4
Revises: 99c833a037ab
Create Date: 2025-11-19 21:49:01.253677

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9e53026276a4'
down_revision: Union[str, Sequence[str], None] = '99c833a037ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'user_preferences',
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('value', sa.String(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('user_preferences')
