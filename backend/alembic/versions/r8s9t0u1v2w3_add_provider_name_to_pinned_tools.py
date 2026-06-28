"""add provider_name to pinned_tools

Pins denormalize tool metadata so the sidebar can render them even when the
provider isn't ready. Persist the friendly provider name too, so an orphaned
pin (provider removed from config, cache row gone) still shows its provider
identity instead of falling back to a bare id/placeholder.

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-06-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'r8s9t0u1v2w3'
down_revision: Union[str, Sequence[str], None] = 'q7r8s9t0u1v2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'pinned_tools' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('pinned_tools')}
    if 'provider_name' not in cols:
        op.add_column('pinned_tools', sa.Column('provider_name', sa.String(), nullable=True))


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'pinned_tools' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('pinned_tools')}
    if 'provider_name' in cols:
        op.drop_column('pinned_tools', 'provider_name')
