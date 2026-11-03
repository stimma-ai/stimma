"""Attach opaque companion objects to immutable media.

Revision ID: msidecars01
Revises: wsync01
"""
from alembic import op
import sqlalchemy as sa

revision = "msidecars01"
down_revision = "wsync01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_sidecars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("media_id", sa.Integer(), sa.ForeignKey("media_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("storage_object_id", sa.Integer(), sa.ForeignKey("storage_objects.id")),
        sa.Column("format", sa.String(), nullable=False),
        sa.Column("format_version", sa.Integer(), nullable=False),
        sa.Column("descriptor_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("mapping_json", sa.Text()),
        sa.Column("info_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("identity_key", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_media_sidecars_media_id", "media_sidecars", ["media_id"])
    op.create_index("ix_media_sidecars_storage_object_id", "media_sidecars", ["storage_object_id"])
    op.create_index("ix_media_sidecars_deleted_at", "media_sidecars", ["deleted_at"])
    op.create_index("idx_media_sidecars_identity", "media_sidecars", ["media_id", "identity_key"], unique=True)
    op.add_column("generation_jobs", sa.Column("result_media_ids", sa.Text()))
    op.add_column("delete_operation_items", sa.Column("sidecar_objects", sa.Text()))


def downgrade():
    op.drop_column("generation_jobs", "result_media_ids")
    op.drop_column("delete_operation_items", "sidecar_objects")
    op.drop_table("media_sidecars")
