"""remove delete operation trigger groups

Revision ID: j1k2l3m4n5o6
Revises: i0j1k2l3m4n5
Create Date: 2026-07-20

Permanent Asset deletion now reports one profile-wide queue in Asset units.
Retire historical completed rows outside any still-active legacy group so they
cannot enter the first queue summary after upgrade, then remove the obsolete
per-trigger correlation column.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "i0j1k2l3m4n5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE delete_operations AS completed "
        "SET status = 'superseded' "
        "WHERE completed.kind = 'asset' "
        "AND completed.status = 'completed' "
        "AND NOT EXISTS ("
        "  SELECT 1 FROM delete_operations AS active "
        "  WHERE active.profile_id = completed.profile_id "
        "  AND active.kind = 'asset' "
        "  AND active.status IN ('queued', 'running', 'failed') "
        "  AND ("
        "    active.group_id = completed.group_id "
        "    OR (active.group_id IS NULL AND completed.group_id IS NULL)"
        "  )"
        ")"
    )
    op.drop_index("idx_delete_operations_group", table_name="delete_operations")
    op.drop_column("delete_operations", "group_id")


def downgrade() -> None:
    op.add_column(
        "delete_operations",
        sa.Column("group_id", sa.String(), nullable=True),
    )
    op.create_index(
        "idx_delete_operations_group",
        "delete_operations",
        ["group_id"],
    )
