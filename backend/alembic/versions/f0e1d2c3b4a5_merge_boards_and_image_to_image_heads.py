"""merge boards and image-to-image heads

Revision ID: f0e1d2c3b4a5
Revises: a9b8c7d6e5f4, dd4ee5ff6gg7
Create Date: 2026-04-03
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "f0e1d2c3b4a5"
down_revision: Union[str, Sequence[str], None] = ("a9b8c7d6e5f4", "dd4ee5ff6gg7")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
