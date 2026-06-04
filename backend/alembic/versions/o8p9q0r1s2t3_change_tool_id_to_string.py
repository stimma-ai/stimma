"""change_tool_id_to_string

Change tool_id column in generation_jobs from Integer to String
to support full tool IDs like "builtin:ComfyUI:z-image-turbo:text-to-image"

Revision ID: o8p9q0r1s2t3
Revises: n7o8p9q0r1s2
Create Date: 2025-12-26

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'o8p9q0r1s2t3'
down_revision: Union[str, Sequence[str], None] = 'n7o8p9q0r1s2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change tool_id from Integer to String in generation_jobs table."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Check if table exists first (for fresh databases)
    if 'generation_jobs' not in inspector.get_table_names():
        print("generation_jobs table does not exist yet, skipping migration")
        return

    # Check if column exists and its type
    existing_columns = {col['name']: col for col in inspector.get_columns('generation_jobs')}

    if 'tool_id' not in existing_columns:
        # Column doesn't exist - add it as String (the table definition will create it correctly)
        print("tool_id column does not exist, skipping (will be created by table definition)")
        return

    col_type = str(existing_columns['tool_id']['type'])
    if 'VARCHAR' in col_type.upper() or 'TEXT' in col_type.upper() or 'STRING' in col_type.upper():
        print("tool_id column is already a string type, skipping")
        return

    # SQLite requires table recreation to change column type
    # Use batch_alter_table which handles this automatically
    with op.batch_alter_table('generation_jobs', recreate='always') as batch_op:
        batch_op.alter_column(
            'tool_id',
            existing_type=sa.Integer(),
            type_=sa.String(),
            existing_nullable=True
        )

    print("Successfully changed tool_id column from Integer to String")


def downgrade() -> None:
    """Change tool_id back from String to Integer in generation_jobs table."""
    with op.batch_alter_table('generation_jobs', recreate='always') as batch_op:
        batch_op.alter_column(
            'tool_id',
            existing_type=sa.String(),
            type_=sa.Integer(),
            existing_nullable=True
        )
