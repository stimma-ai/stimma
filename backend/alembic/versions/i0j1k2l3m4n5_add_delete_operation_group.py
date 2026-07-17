"""add group_id to delete_operations

Revision ID: i0j1k2l3m4n5
Revises: h9i0j1k2l3m4
Create Date: 2026-07-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i0j1k2l3m4n5"
down_revision: Union[str, Sequence[str], None] = "h9i0j1k2l3m4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "delete_operations",
        sa.Column("group_id", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_delete_operations_group",
        "delete_operations",
        ["group_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_delete_operations_group", table_name="delete_operations")
    op.drop_column("delete_operations", "group_id")
