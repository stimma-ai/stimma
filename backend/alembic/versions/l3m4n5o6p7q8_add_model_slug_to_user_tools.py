"""add model_slug column to user_tools

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-07-21 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, Sequence[str], None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Capture the flow's LLM at freeze time.

    A frozen flow (UserTool) runs behind the tool abstraction with no live
    chat, so its `agent` LLM steps have no per-chat model to inherit. Snapshot
    the model the source flow's chat was using at freeze time; NULL means fall
    back to the global default at run time.
    """
    op.add_column("user_tools", sa.Column("model_slug", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_tools", "model_slug")
