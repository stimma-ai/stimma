"""Add AUTOINCREMENT to prevent ID reuse after deletion

Rebuilds tables with SQLite AUTOINCREMENT to prevent ID reuse.
This is critical for tables whose IDs appear in URLs or caching.

Revision ID: r1s2t3u4v5w6
Revises: q0r1s2t3u4v5
Create Date: 2026-01-01

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision: str = 'r1s2t3u4v5w6'
down_revision: Union[str, Sequence[str], None] = 'q0r1s2t3u4v5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Tables to migrate (order matters for FK dependencies)
# Independent tables first, then tables with FK references
TABLES_TO_MIGRATE = [
    'markers',
    'tags',
    'collections',
    'saved_views',
    'presets',
    'chats',
    'generation_jobs',
    'media_items',
    'chat_items',
]


def upgrade() -> None:
    """Rebuild tables with AUTOINCREMENT to prevent ID reuse."""
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    # Must disable FK enforcement during table rebuilds
    connection.execute(text("PRAGMA foreign_keys = OFF"))

    for table_name in TABLES_TO_MIGRATE:
        if table_name not in inspector.get_table_names():
            print(f"Table {table_name} does not exist, skipping")
            continue

        # Check if already has AUTOINCREMENT by checking sqlite_sequence
        try:
            result = connection.execute(
                text("SELECT name FROM sqlite_sequence WHERE name = :table"),
                {"table": table_name}
            )
            if result.fetchone():
                print(f"Table {table_name} already has AUTOINCREMENT, skipping")
                continue
        except Exception:
            # sqlite_sequence table may not exist if no AUTOINCREMENT tables yet
            pass

        print(f"Rebuilding {table_name} with AUTOINCREMENT...")
        rebuild_table_with_autoincrement(connection, inspector, table_name)

    # Re-enable FK enforcement
    connection.execute(text("PRAGMA foreign_keys = ON"))

    print("Successfully added AUTOINCREMENT to all tables")


def rebuild_table_with_autoincrement(connection, inspector, table_name):
    """Rebuild a single table with AUTOINCREMENT."""
    # Get current max ID
    result = connection.execute(text(f"SELECT MAX(id) FROM \"{table_name}\""))
    max_id = result.scalar() or 0

    # Get table info
    columns = inspector.get_columns(table_name)
    indexes = inspector.get_indexes(table_name)
    fks = inspector.get_foreign_keys(table_name)

    # Build column definitions
    col_defs = []
    col_names = []

    for col in columns:
        col_names.append(f"\"{col['name']}\"")
        col_type = str(col['type'])
        nullable = col['nullable']
        default = col.get('default')

        if col['name'] == 'id':
            # This is the key change: add AUTOINCREMENT
            col_defs.append('"id" INTEGER PRIMARY KEY AUTOINCREMENT')
        else:
            null_str = "" if nullable else " NOT NULL"
            default_str = f" DEFAULT {default}" if default else ""
            col_defs.append(f"\"{col['name']}\" {col_type}{null_str}{default_str}")

    # Add foreign key constraints
    for fk in fks:
        ref_table = fk['referred_table']
        ref_cols = ', '.join(f'"{c}"' for c in fk['referred_columns'])
        constrained_cols = ', '.join(f'"{c}"' for c in fk['constrained_columns'])
        ondelete = fk.get('options', {}).get('ondelete', '')
        ondelete_str = f" ON DELETE {ondelete}" if ondelete else ""
        col_defs.append(
            f"FOREIGN KEY ({constrained_cols}) REFERENCES \"{ref_table}\"({ref_cols}){ondelete_str}"
        )

    # Create new table
    new_table = f"_new_{table_name}"
    create_sql = f"CREATE TABLE \"{new_table}\" ({', '.join(col_defs)})"
    connection.execute(text(create_sql))

    # Copy data
    cols_str = ', '.join(col_names)
    connection.execute(text(f"INSERT INTO \"{new_table}\" ({cols_str}) SELECT {cols_str} FROM \"{table_name}\""))

    # Drop old table
    connection.execute(text(f"DROP TABLE \"{table_name}\""))

    # Rename new table
    connection.execute(text(f"ALTER TABLE \"{new_table}\" RENAME TO \"{table_name}\""))

    # Initialize sqlite_sequence to prevent ID reuse
    # Use INSERT OR REPLACE to handle case where row may or may not exist
    connection.execute(text(
        "INSERT OR REPLACE INTO sqlite_sequence (name, seq) VALUES (:table, :seq)"
    ), {"table": table_name, "seq": max_id})

    # Recreate indexes (excluding auto-generated ones)
    for idx in indexes:
        if idx['name'] and not idx['name'].startswith('sqlite_'):
            cols = ', '.join(f'"{c}"' for c in idx['column_names'])
            unique = "UNIQUE " if idx['unique'] else ""
            try:
                connection.execute(text(f"CREATE {unique}INDEX \"{idx['name']}\" ON \"{table_name}\" ({cols})"))
            except Exception as e:
                print(f"  Warning: Could not recreate index {idx['name']}: {e}")

    print(f"  Rebuilt {table_name}, max_id={max_id}")


def downgrade() -> None:
    """Downgrade is a no-op - AUTOINCREMENT doesn't hurt anything."""
    # Removing AUTOINCREMENT would require another full table rebuild
    # and could re-introduce the ID reuse issue, so we leave it in place
    print("Downgrade is a no-op - AUTOINCREMENT remains in place")
