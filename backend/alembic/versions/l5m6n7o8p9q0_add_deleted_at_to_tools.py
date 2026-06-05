"""add_deleted_at_to_tools

Revision ID: l5m6n7o8p9q0
Revises: k4l5m6n7o8p9
Create Date: 2025-12-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'l5m6n7o8p9q0'
down_revision: Union[str, Sequence[str], None] = 'k4l5m6n7o8p9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add deleted_at column to tools table for soft delete support."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table exists first (for fresh databases)
    if 'tools' not in inspector.get_table_names():
        print("tools table does not exist yet, skipping migration")
        return

    # Check if column already exists
    existing_columns = [col['name'] for col in inspector.get_columns('tools')]

    if 'deleted_at' not in existing_columns:
        op.add_column('tools', sa.Column('deleted_at', sa.DateTime(), nullable=True))
        # Create index for deleted_at
        op.create_index('ix_tools_deleted_at', 'tools', ['deleted_at'], unique=False)
        print("Successfully added deleted_at column to tools")
    else:
        print("deleted_at column already exists, skipping")

    # Drop the unique index on (profile_id, name) since soft-deleted tools can have duplicate names
    # Uniqueness is now enforced at the application level for non-deleted tools only
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('tools')]
    if 'idx_tools_profile_name' in existing_indexes:
        op.drop_index('idx_tools_profile_name', table_name='tools')
        print("Dropped unique index idx_tools_profile_name")
    else:
        print("idx_tools_profile_name index does not exist, skipping drop")

    # Make parameters and loras columns nullable (they're now legacy, state is the source of truth)
    # SQLite doesn't support ALTER COLUMN, so we need to recreate the table
    # Instead, we'll just ensure new rows can have NULL by using a workaround:
    # Set default empty values for existing NULL-constraint columns
    # Actually for SQLite, we need to use batch operations
    try:
        with op.batch_alter_table('tools') as batch_op:
            batch_op.alter_column('parameters', existing_type=sa.String(), nullable=True)
            batch_op.alter_column('loras', existing_type=sa.String(), nullable=True)
        print("Made parameters and loras columns nullable")
    except Exception as e:
        print(f"Could not alter columns (may already be nullable): {e}")

    # Run ANALYZE to update SQLite statistics
    connection.execute(text("ANALYZE"))


def downgrade() -> None:
    """Remove deleted_at column from tools table."""
    op.drop_index('ix_tools_deleted_at', table_name='tools')
    op.drop_column('tools', 'deleted_at')
    # Recreate the unique index (may fail if there are duplicate names)
    op.create_index('idx_tools_profile_name', 'tools', ['profile_id', 'name'], unique=True)
