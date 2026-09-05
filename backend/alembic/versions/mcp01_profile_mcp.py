"""Profile MCP client identities and durable operation receipts.

Revision ID: mcp01
Revises: t1u2v3w4x5y6
"""

from alembic import op
import sqlalchemy as sa

revision = "mcp01"
down_revision = "t1u2v3w4x5y6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_clients",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("profile_id", sa.String(), nullable=False),
        sa.Column("credential_hash", sa.String(), nullable=False, unique=True),
        sa.Column("installation", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
    )
    op.create_table(
        "mcp_operations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("client_id", sa.String(), nullable=False),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("request_key", sa.String(), nullable=False),
        sa.Column("input_hash", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("input_json", sa.Text(), nullable=False),
        sa.Column("result_json", sa.Text()),
        sa.Column("chat_id", sa.Integer()),
        sa.Column("controller_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime()),
        sa.UniqueConstraint("operation", "request_key", name="uq_mcp_request"),
    )


def downgrade():
    op.drop_table("mcp_operations")
    op.drop_table("mcp_clients")
