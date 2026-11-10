"""Drop the asset browser group tables (grouping was reverted).

Revision ID: assetgroups02
Revises: assetgroups01

assetgroups01 stays so databases that already ran it still have a known head.
"""
from alembic import op
import sqlalchemy as sa

revision = "assetgroups02"
down_revision = "assetgroups01"
branch_labels = None
depends_on = None


def upgrade():
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in ("asset_group_refs", "asset_group_members", "asset_groups"):
        if name in tables:
            op.drop_table(name)


def downgrade():
    pass
