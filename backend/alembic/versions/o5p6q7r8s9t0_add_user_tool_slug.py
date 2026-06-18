"""add user_tools.slug (stable URL slug, frozen at creation)

The tool id is ``{slug}-{id}`` and is used for routing / pins / presets, so it
must stay stable when a tool is renamed. We therefore freeze a slug at creation
instead of recomputing it from the (mutable) name. See plans/FLOW_TO_TOOL.md §10.8.

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-06-18

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o5p6q7r8s9t0'
down_revision: Union[str, Sequence[str], None] = 'n4o5p6q7r8s9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").strip().lower()).strip("-") or "tool"


def upgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'user_tools' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('user_tools')}
    if 'slug' not in cols:
        op.add_column('user_tools', sa.Column('slug', sa.String(), nullable=True))

    # Backfill existing rows: freeze a slug from each tool's current name.
    rows = connection.execute(
        sa.text("SELECT id, name FROM user_tools WHERE slug IS NULL")
    ).fetchall()
    for row in rows:
        connection.execute(
            sa.text("UPDATE user_tools SET slug = :slug WHERE id = :id"),
            {"slug": _slug(row[1]), "id": row[0]},
        )


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    if 'user_tools' not in inspector.get_table_names():
        return
    cols = {c['name'] for c in inspector.get_columns('user_tools')}
    if 'slug' in cols:
        op.drop_column('user_tools', 'slug')
