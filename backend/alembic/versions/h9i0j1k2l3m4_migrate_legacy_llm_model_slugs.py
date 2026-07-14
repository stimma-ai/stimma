"""migrate retired LLM model aliases

Revision ID: h9i0j1k2l3m4
Revises: g8h9i0j1k2l3
Create Date: 2026-07-14
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h9i0j1k2l3m4"
down_revision: Union[str, Sequence[str], None] = "g8h9i0j1k2l3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    params = {
        "replacement": "stimma:minimax-m3",
        "agent_max": "agent-max",
        "legacy_default": "default",
    }
    bind = op.get_bind()
    bind.execute(
        sa.text(
            "UPDATE chats SET model_slug = :replacement "
            "WHERE model_slug IN (:agent_max, :legacy_default)"
        ),
        params,
    )
    bind.execute(
        sa.text(
            "UPDATE projects SET default_model_slug = :replacement "
            "WHERE default_model_slug IN (:agent_max, :legacy_default)"
        ),
        params,
    )


def downgrade() -> None:
    # Both historical aliases collapse to one current model, so their original
    # identity cannot be reconstructed safely.
    pass
