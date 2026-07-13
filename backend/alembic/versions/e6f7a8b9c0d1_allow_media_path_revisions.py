"""allow multiple Media revisions for one source path

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, Sequence[str], None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_media_items_file_path", table_name="media_items")
    op.create_index(
        "ix_media_items_file_path", "media_items", ["file_path"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_media_items_file_path", table_name="media_items")
    op.create_index(
        "ix_media_items_file_path", "media_items", ["file_path"], unique=True
    )
