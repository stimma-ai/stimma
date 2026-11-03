"""Add LoRA notes: trigger words and notes attached to a file fingerprint.

Revision ID: loranotes01
Revises: wsync01
"""
from alembic import op
import sqlalchemy as sa

revision = "loranotes01"
down_revision = "wsync01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "lora_notes" not in tables:
        op.create_table(
            "lora_notes",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("trigger_words", sa.JSON(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("shared", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_lora_notes_deleted_at", "lora_notes", ["deleted_at"])
    if "lora_note_files" not in tables:
        op.create_table(
            "lora_note_files",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("fingerprint", sa.String(), nullable=False),
            sa.Column("note_id", sa.Integer(), sa.ForeignKey("lora_notes.id"), nullable=False),
            sa.Column("last_seen_value", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_lora_note_files_note_id", "lora_note_files", ["note_id"])
        op.create_index(
            "uq_lora_note_files_live_fingerprint",
            "lora_note_files",
            ["fingerprint"],
            unique=True,
            sqlite_where=sa.text("deleted_at IS NULL"),
        )


def downgrade() -> None:
    op.drop_table("lora_note_files")
    op.drop_table("lora_notes")
