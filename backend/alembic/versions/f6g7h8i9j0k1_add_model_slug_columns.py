"""add_model_slug_columns

Revision ID: f6g7h8i9j0k1
Revises: d4e5f6g7h8i9
Create Date: 2026-04-06

Add model_slug to chats and default_model_slug to projects
for per-chat/per-project LLM model selection.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f6g7h8i9j0k1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6g7h8i9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chats', sa.Column('model_slug', sa.String(), nullable=True))
    op.add_column('projects', sa.Column('default_model_slug', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'default_model_slug')
    op.drop_column('chats', 'model_slug')
