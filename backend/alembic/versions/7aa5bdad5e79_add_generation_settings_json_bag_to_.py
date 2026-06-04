"""add generation_settings json bag to chats

Revision ID: 7aa5bdad5e79
Revises: ef7002cbcc17
Create Date: 2025-11-24 15:03:58.519088

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '7aa5bdad5e79'
down_revision: Union[str, Sequence[str], None] = 'ef7002cbcc17'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('chats', sa.Column('generation_settings', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('chats', 'generation_settings')
