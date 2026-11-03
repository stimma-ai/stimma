"""Add the shared workspace: workspace_docs and workspace_migrations.

Revision ID: wsync01
Revises: chat01

Sidebar tabs, tool working state and preferences used to live in each client's
local storage. These tables make the server their authority, so every client
of a profile sees one workspace.
"""
from alembic import op
import sqlalchemy as sa

revision = "wsync01"
down_revision = "chat01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = sa.inspect(op.get_bind()).get_table_names()
    if "workspace_docs" not in tables:
        op.create_table(
            "workspace_docs",
            sa.Column("namespace", sa.String(), primary_key=True),
            sa.Column("key", sa.String(), primary_key=True),
            sa.Column("value", sa.Text(), nullable=True),
            sa.Column("rev", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_workspace_docs_deleted_at", "workspace_docs", ["deleted_at"])
    if "workspace_migrations" not in tables:
        op.create_table(
            "workspace_migrations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("client_id", sa.String(), nullable=False),
            sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("payload", sa.Text(), nullable=False),
            sa.Column("stats", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("deleted_at", sa.DateTime(), nullable=True),
            sqlite_autoincrement=True,
        )
        op.create_index("ix_workspace_migrations_client_id", "workspace_migrations", ["client_id"])
        op.create_index(
            "uq_workspace_migrations_claim",
            "workspace_migrations",
            ["applied"],
            unique=True,
            sqlite_where=sa.text("applied = 1"),
        )


def downgrade() -> None:
    op.drop_table("workspace_migrations")
    op.drop_table("workspace_docs")
