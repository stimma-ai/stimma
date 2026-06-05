"""add_state_to_tools

Revision ID: k4l5m6n7o8p9
Revises: j3k4l5m6n7o8
Create Date: 2025-12-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'k4l5m6n7o8p9'
down_revision: Union[str, Sequence[str], None] = 'j3k4l5m6n7o8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add state column to tools table for unified tool state storage."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table exists first (for fresh databases)
    if 'tools' not in inspector.get_table_names():
        print("tools table does not exist yet, skipping migration")
        return

    # Check if column already exists
    existing_columns = [col['name'] for col in inspector.get_columns('tools')]

    if 'state' not in existing_columns:
        op.add_column('tools', sa.Column('state', sa.String(), nullable=True))
        print("Successfully added state column to tools")
    else:
        print("state column already exists, skipping")

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))


def downgrade() -> None:
    """Remove state column from tools table."""
    op.drop_column('tools', 'state')
