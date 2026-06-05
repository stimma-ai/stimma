"""drop input_schema from cached_provider_tools

Eliminates the tool "input vs parameters" duality: tool descriptors now carry
a single ``parameter_schema`` holding all parameters (prompt, input_images,
mask, width, height, seed, steps, cfg, loras, ...). The separate
``input_schema`` column on the cached tool table is no longer used.

NOTE: This is the tool-descriptor input_schema, NOT the recipes table's
input_schema (the recipe input-form schema), which is untouched.

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-01

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'j0k1l2m3n4o5'
down_revision: Union[str, Sequence[str], None] = 'i9j0k1l2m3n4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Drop the input_schema column from cached_provider_tools (SQLite-safe batch mode)."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if 'cached_provider_tools' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('cached_provider_tools')}
    if 'input_schema' not in columns:
        return

    with op.batch_alter_table('cached_provider_tools') as batch_op:
        batch_op.drop_column('input_schema')


def downgrade() -> None:
    """Re-add the input_schema column (nullable, no data restored)."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    if 'cached_provider_tools' not in inspector.get_table_names():
        return

    columns = {col['name'] for col in inspector.get_columns('cached_provider_tools')}
    if 'input_schema' in columns:
        return

    with op.batch_alter_table('cached_provider_tools') as batch_op:
        batch_op.add_column(sa.Column('input_schema', sa.String(), nullable=True))
