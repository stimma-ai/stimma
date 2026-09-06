"""Record when each MCP connection last authenticated.

Revision ID: mcp02
Revises: mcp01
"""

from alembic import op
import sqlalchemy as sa

revision = "mcp02"
down_revision = "mcp01"
branch_labels = None
depends_on = None


def upgrade():
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("mcp_clients")}
    if "last_used_at" not in columns:
        op.add_column("mcp_clients", sa.Column("last_used_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("mcp_clients", "last_used_at")
