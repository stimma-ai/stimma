"""Asset browser groups: Auto work threads and Themes, with frozen inputs.

Revision ID: assetgroups01
Revises: csheets01
"""
from alembic import op
import sqlalchemy as sa

revision = "assetgroups01"
down_revision = "csheets01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "asset_groups" not in tables:
        op.create_table(
            "asset_groups",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("kind", sa.String(), nullable=False),
            sa.Column("title", sa.String()),
            sa.Column("title_source", sa.String(), nullable=False, server_default="none"),
            sa.Column("project_id", sa.Integer(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
            sa.Column("first_at", sa.DateTime()),
            sa.Column("last_at", sa.DateTime()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime()),
            sqlite_autoincrement=True,
        )
        op.create_index("idx_asset_groups_kind", "asset_groups", ["kind"])
        op.create_index("ix_asset_groups_deleted_at", "asset_groups", ["deleted_at"])
    if "asset_group_members" not in tables:
        op.create_table(
            "asset_group_members",
            sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("kind", sa.String(), primary_key=True),
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("asset_groups.id", ondelete="CASCADE"), nullable=False),
            sa.Column("reason", sa.String(), nullable=False),
            sa.Column("assigned_at", sa.DateTime(), nullable=False),
            sa.Column("media_id", sa.Integer()),
            sa.Column("arrived_at", sa.DateTime(), nullable=False),
            sa.Column("typed_prompt", sa.Text()),
            sa.Column("tool_id", sa.String()),
            sa.Column("chat_id", sa.Integer()),
            sa.Column("import_key", sa.String()),
            sa.Column("vector", sa.LargeBinary()),
        )
        op.create_index("idx_asset_group_members_group", "asset_group_members", ["kind", "group_id"])
        op.create_index("idx_asset_group_members_assigned", "asset_group_members", ["assigned_at"])
    if "asset_group_refs" not in tables:
        op.create_table(
            "asset_group_refs",
            sa.Column("group_id", sa.Integer(), sa.ForeignKey("asset_groups.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), primary_key=True),
        )
        op.create_index("idx_asset_group_refs_asset", "asset_group_refs", ["asset_id"])


def downgrade():
    op.drop_table("asset_group_refs")
    op.drop_table("asset_group_members")
    op.drop_table("asset_groups")
