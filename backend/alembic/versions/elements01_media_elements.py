"""Elements: record which element revisions a generated Media was made with.

Revision ID: elements01
Revises: timers01
"""
from alembic import op
import sqlalchemy as sa

revision = "elements01"
down_revision = "timers01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "media_elements" in inspector.get_table_names():
        return
    op.create_table(
        "media_elements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("media_id", sa.Integer(), sa.ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("element_asset_id", sa.Integer(), sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("element_revision_id", sa.Integer(), sa.ForeignKey("asset_revisions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("element_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("carrier", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_media_elements_media_id", "media_elements", ["media_id"])
    op.create_index("idx_media_elements_asset", "media_elements", ["element_asset_id", "created_at"])


def downgrade():
    op.drop_table("media_elements")
