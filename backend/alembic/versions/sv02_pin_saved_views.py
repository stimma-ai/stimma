"""Let saved views be pinned to the sidebar.

Revision ID: sv02
Revises: collections01

A pinned view stays in the sidebar outside Assets. Existing views start unpinned.
"""
from alembic import op
import sqlalchemy as sa

revision = "sv02"
down_revision = "collections01"
branch_labels = None
depends_on = None


def upgrade():
    # A database built from the current models already has the column.
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("saved_views")}
    if "pinned" in columns:
        return
    with op.batch_alter_table("saved_views", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("pinned", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    with op.batch_alter_table("saved_views", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_column("pinned")
