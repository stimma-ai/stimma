"""contract legacy Media visibility and containment fields

Revision ID: g8h9i0j1k2l3
Revises: f7g8h9i0j1k2
Create Date: 2026-07-13

Asset identity and normalized container membership now determine ordinary
visibility. Historical backfill classifies manifest members directly, so the
old replacement/visibility columns no longer carry authoritative evidence.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8h9i0j1k2l3"
down_revision: Union[str, Sequence[str], None] = "f7g8h9i0j1k2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    index_names = {
        index["name"]
        for index in sa.inspect(bind).get_indexes("media_items")
    }
    with op.batch_alter_table("media_items") as batch_op:
        if "ix_media_items_superseded_by" in index_names:
            batch_op.drop_index("ix_media_items_superseded_by")
        if "ix_media_items_is_hidden" in index_names:
            batch_op.drop_index("ix_media_items_is_hidden")
        batch_op.drop_column("superseded_by")
        batch_op.drop_column("is_hidden")


def downgrade() -> None:
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.add_column(sa.Column("superseded_by", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("is_hidden", sa.Boolean(), nullable=True))
        batch_op.create_foreign_key(
            "fk_media_items_superseded_by",
            "media_items",
            ["superseded_by"],
            ["id"],
        )
        batch_op.create_index(
            "ix_media_items_superseded_by", ["superseded_by"]
        )
        batch_op.create_index("ix_media_items_is_hidden", ["is_hidden"])
