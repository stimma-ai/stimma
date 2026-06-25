"""add model_vendor / model to cached_provider_tools

STP tools may declare an optional model identity (``model_vendor`` / ``model``).
Connected providers already pass these through to the UI; persist them on the
cached store so disconnected tools keep their vendor brand mark.

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-06-25

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p6q7r8s9t0u1'
down_revision: Union[str, Sequence[str], None] = 'o5p6q7r8s9t0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'cached_provider_tools' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('cached_provider_tools')}
    if 'model_vendor' not in cols:
        op.add_column('cached_provider_tools', sa.Column('model_vendor', sa.String(), nullable=True))
    if 'model' not in cols:
        op.add_column('cached_provider_tools', sa.Column('model', sa.String(), nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'cached_provider_tools' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('cached_provider_tools')}
    if 'model' in cols:
        op.drop_column('cached_provider_tools', 'model')
    if 'model_vendor' in cols:
        op.drop_column('cached_provider_tools', 'model_vendor')
