"""add durable Media deletion barrier

Revision ID: f7g8h9i0j1k2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7g8h9i0j1k2"
down_revision: Union[str, Sequence[str], None] = "e6f7a8b9c0d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("flows"):
        parent_fk = next(
            (
                foreign_key
                for foreign_key in sa.inspect(bind).get_foreign_keys("flows")
                if foreign_key.get("constrained_columns") == ["parent_id"]
            ),
            None,
        )
        if parent_fk and parent_fk.get("referred_table") == "recipes":
            op.execute(
                sa.text(
                    """
                    UPDATE flows
                    SET parent_id = NULL
                    WHERE parent_id IS NOT NULL
                      AND parent_id NOT IN (SELECT id FROM flows)
                    """
                )
            )
            op.execute(
                sa.text(
                    """
                    UPDATE flows
                    SET project_id = NULL
                    WHERE project_id IS NOT NULL
                      AND project_id NOT IN (SELECT id FROM projects)
                    """
                )
            )
            # SQLAlchemy cannot reflect a dangling FK target. Supply the
            # minimal historical table only for the batch rebuild, then remove
            # it once the self-reference points at flows.
            op.execute(sa.text("CREATE TABLE recipes (id INTEGER PRIMARY KEY)"))
            naming_convention = {
                "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
            }
            with op.batch_alter_table(
                "flows", naming_convention=naming_convention
            ) as batch_op:
                batch_op.drop_constraint(
                    "fk_flows_parent_id_recipes", type_="foreignkey"
                )
                batch_op.create_foreign_key(
                    "fk_flows_parent_id_flows",
                    "flows",
                    ["parent_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            op.execute(sa.text("DROP TABLE recipes"))

    with op.batch_alter_table("media_items") as batch_op:
        batch_op.add_column(
            sa.Column("deletion_pending_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_index(
            "ix_media_items_deletion_pending_at", ["deletion_pending_at"]
        )

    with op.batch_alter_table("delete_operation_items") as batch_op:
        batch_op.add_column(sa.Column("storage_object_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("storage_object_key", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("storage_kind", sa.String(), nullable=True))
        batch_op.add_column(sa.Column("thumbnail_paths", sa.Text(), nullable=True))

    # Existing unfinished operations predate the service-level barrier. Keep
    # their still-present Media unavailable rather than reopening an ownership
    # race after upgrade or restart.
    op.execute(
        sa.text(
            """
            UPDATE media_items
            SET deletion_pending_at = CURRENT_TIMESTAMP
            WHERE id IN (
                SELECT doi.media_id
                FROM delete_operation_items AS doi
                JOIN delete_operations AS operation
                  ON operation.id = doi.operation_id
                WHERE operation.status IN ('queued', 'running')
                  AND doi.state NOT IN ('done', 'failed')
            )
            """
        )
    )

    op.execute(
        sa.text(
            """
            DELETE FROM generation_jobs
            WHERE result_media_id IS NOT NULL
              AND result_media_id NOT IN (SELECT id FROM media_items)
            """
        )
    )
    op.execute(
        sa.text(
            """
            UPDATE generation_jobs
            SET batch_output_set_id = NULL
            WHERE batch_output_set_id IS NOT NULL
              AND batch_output_set_id NOT IN (SELECT id FROM media_items)
            """
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("delete_operation_items") as batch_op:
        batch_op.drop_column("thumbnail_paths")
        batch_op.drop_column("storage_kind")
        batch_op.drop_column("storage_object_key")
        batch_op.drop_column("storage_object_id")

    with op.batch_alter_table("media_items") as batch_op:
        batch_op.drop_index("ix_media_items_deletion_pending_at")
        batch_op.drop_column("deletion_pending_at")
