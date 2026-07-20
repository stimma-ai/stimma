"""add durable Asset identity targets to delete operations

Revision ID: k2l3m4n5o6p7
Revises: j1k2l3m4n5o6
Create Date: 2026-07-20

Asset IDs let Empty Trash commit its complete queue immediately, then perform
identity cleanup in short worker transactions without monopolizing SQLite.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k2l3m4n5o6p7"
down_revision: Union[str, Sequence[str], None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "delete_operations",
        sa.Column("asset_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        "ix_delete_operations_asset_id",
        "delete_operations",
        ["asset_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_delete_operations_asset_id",
        table_name="delete_operations",
    )
    op.drop_column("delete_operations", "asset_id")
