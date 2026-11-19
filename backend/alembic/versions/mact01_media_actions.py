"""Media actions: what the user did to media between chat messages.

Revision ID: mact01
Revises: retirevlm01

Marks, collection changes, trash, exports, edits and shares the user made
through the app, so the chat agent's next message can say what happened.
"""
from alembic import op
import sqlalchemy as sa

revision = "mact01"
down_revision = "retirevlm01"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "media_actions" in inspector.get_table_names():
        return
    op.create_table(
        "media_actions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("media_id", sa.Integer(), nullable=True),
        sa.Column("asset_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_media_actions_media_id", "media_actions", ["media_id"])
    op.create_index("ix_media_actions_asset_id", "media_actions", ["asset_id"])
    op.create_index("ix_media_actions_created_at", "media_actions", ["created_at"])
    op.create_index("ix_media_actions_deleted_at", "media_actions", ["deleted_at"])


def downgrade():
    op.drop_table("media_actions")
