"""Index chat items by (chat_id, id) and (chat_id, item_type).

Revision ID: chat01
Revises: cache01

Transcript windows and pages walk a chat's items by id, newest first; the
(chat_id, created_at) index forced a temporary sort for that. The skill and
prompt lookups filter one chat's items by type.
"""
from alembic import op
import sqlalchemy as sa

revision = "chat01"
down_revision = "cache01"
branch_labels = None
depends_on = None


def _existing(name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(index["name"] == name for index in inspector.get_indexes("chat_items"))


def upgrade() -> None:
    if not _existing("idx_chat_items_chat_id"):
        op.create_index("idx_chat_items_chat_id", "chat_items", ["chat_id", "id"])
    if not _existing("idx_chat_items_chat_type"):
        op.create_index("idx_chat_items_chat_type", "chat_items", ["chat_id", "item_type"])


def downgrade() -> None:
    op.drop_index("idx_chat_items_chat_type", table_name="chat_items")
    op.drop_index("idx_chat_items_chat_id", table_name="chat_items")
