"""Rename image-edit task type to image-to-image.

Revision ID: dd4ee5ff6gg7
Revises: cc3dd4ee5ff6
Create Date: 2026-02-22
"""
from alembic import op

revision = 'dd4ee5ff6gg7'
down_revision = 'cc3dd4ee5ff6'
branch_labels = None
depends_on = None


def upgrade():
    # Rename task_type in all tables that store it as a plain string
    for table in ['generation_jobs', 'tools', 'cached_provider_tools', 'pinned_tools', 'task_defaults', 'media_lineage']:
        op.execute(f"UPDATE {table} SET task_type = 'image-to-image' WHERE task_type = 'image-edit'")

    # JSON columns: cached_provider_tools.task_types and pinned_tools.task_types
    # These store JSON arrays like '["text-to-image", "image-edit"]'
    for table in ['cached_provider_tools', 'pinned_tools']:
        op.execute(
            f"UPDATE {table} SET task_types = REPLACE(task_types, '\"image-edit\"', '\"image-to-image\"') "
            f"WHERE task_types LIKE '%image-edit%'"
        )

    # generation_metadata JSON in media_items (contains task_type field)
    # Replace only the exact task_type field pattern to avoid colliding with "image-editor" tool IDs
    op.execute(
        "UPDATE media_items SET generation_metadata = REPLACE(generation_metadata, '\"task_type\": \"image-edit\"', '\"task_type\": \"image-to-image\"') "
        "WHERE generation_metadata LIKE '%\"task_type\": \"image-edit\"%'"
    )


def downgrade():
    for table in ['generation_jobs', 'tools', 'cached_provider_tools', 'pinned_tools', 'task_defaults', 'media_lineage']:
        op.execute(f"UPDATE {table} SET task_type = 'image-edit' WHERE task_type = 'image-to-image'")

    for table in ['cached_provider_tools', 'pinned_tools']:
        op.execute(
            f"UPDATE {table} SET task_types = REPLACE(task_types, '\"image-to-image\"', '\"image-edit\"') "
            f"WHERE task_types LIKE '%image-to-image%'"
        )

    op.execute(
        "UPDATE media_items SET generation_metadata = REPLACE(generation_metadata, '\"task_type\": \"image-to-image\"', '\"task_type\": \"image-edit\"') "
        "WHERE generation_metadata LIKE '%\"task_type\": \"image-to-image\"%'"
    )
