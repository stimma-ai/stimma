"""normalize_keywords_to_separate_tables

Revision ID: 24362b773b75
Revises: 9e53026276a4
Create Date: 2025-11-20 07:51:59.432844

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '24362b773b75'
down_revision: Union[str, Sequence[str], None] = '9e53026276a4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to normalize keywords into separate tables."""
    from sqlalchemy import text
    from sqlalchemy.exc import OperationalError

    # Check if tables already exist (they might have been created by Base.metadata.create_all)
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # Create keywords table if it doesn't exist
    if 'keywords' not in existing_tables:
        op.create_table(
            'keywords',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('keyword_text', sa.String(), nullable=False),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_keywords_id', 'keywords', ['id'])
        op.create_index('ix_keywords_keyword_text', 'keywords', ['keyword_text'], unique=True)

    # Create media_keywords junction table if it doesn't exist
    if 'media_keywords' not in existing_tables:
        op.create_table(
            'media_keywords',
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('keyword_id', sa.Integer(), nullable=False),
            sa.PrimaryKeyConstraint('media_id', 'keyword_id')
        )
        op.create_index('idx_keyword_media', 'media_keywords', ['keyword_id', 'media_id'])
        op.create_index('idx_media_keyword', 'media_keywords', ['media_id', 'keyword_id'])

    # Add index on file_format for media type filters (if it doesn't exist)
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('media_items')]
    if 'ix_media_items_file_format' not in existing_indexes:
        op.create_index('ix_media_items_file_format', 'media_items', ['file_format'])

    # Migrate existing keywords data (only if keywords table is empty)
    # This will be done in Python to handle the comma-separated strings
    connection = op.get_bind()

    # Check if keywords have already been migrated
    existing_keywords_count = connection.execute(text("SELECT COUNT(*) FROM keywords")).scalar()
    existing_media_keywords_count = connection.execute(text("SELECT COUNT(*) FROM media_keywords")).scalar()

    if existing_keywords_count > 0 or existing_media_keywords_count > 0:
        print(f"Keywords already migrated ({existing_keywords_count} keywords, {existing_media_keywords_count} media-keyword relationships found). Skipping data migration.")
        return

    # Get all media items with keywords
    result = connection.execute(text(
        "SELECT id, keywords FROM media_items WHERE keywords IS NOT NULL AND keywords != ''"
    ))

    keyword_id_map = {}  # Map keyword text to id
    next_keyword_id = 1

    media_keyword_pairs = []  # List of (media_id, keyword_id) tuples

    for row in result:
        media_id = row[0]
        keywords_str = row[1]

        # Split and normalize keywords
        if keywords_str:
            # Use set() to deduplicate keywords for this media item
            keywords = list(set(kw.strip().lower() for kw in keywords_str.split(',') if kw.strip()))

            for keyword in keywords:
                # Get or create keyword id
                if keyword not in keyword_id_map:
                    keyword_id_map[keyword] = next_keyword_id
                    # Insert into keywords table
                    connection.execute(text(
                        "INSERT INTO keywords (id, keyword_text) VALUES (:id, :keyword)"
                    ), {"id": next_keyword_id, "keyword": keyword})
                    next_keyword_id += 1

                # Add to media_keywords pairs
                keyword_id = keyword_id_map[keyword]
                media_keyword_pairs.append((media_id, keyword_id))

    # Bulk insert media_keywords
    if media_keyword_pairs:
        # Use executemany for better performance
        connection.execute(text(
            "INSERT INTO media_keywords (media_id, keyword_id) VALUES (:media_id, :keyword_id)"
        ), [{"media_id": m_id, "keyword_id": k_id} for m_id, k_id in media_keyword_pairs])

    # Run ANALYZE to update SQLite statistics for query optimization
    connection.execute(text("ANALYZE"))

    print(f"Migrated {len(keyword_id_map)} unique keywords across {len(media_keyword_pairs)} media-keyword relationships")


def downgrade() -> None:
    """Downgrade schema - restore keywords to comma-separated format."""
    from sqlalchemy import text

    connection = op.get_bind()

    # Restore keywords column data from normalized tables
    result = connection.execute(text("""
        SELECT m.id, GROUP_CONCAT(k.keyword_text, ', ')
        FROM media_items m
        JOIN media_keywords mk ON m.id = mk.media_id
        JOIN keywords k ON mk.keyword_id = k.id
        GROUP BY m.id
    """))

    # Update media_items with comma-separated keywords
    for row in result:
        media_id = row[0]
        keywords_str = row[1]
        connection.execute(text(
            "UPDATE media_items SET keywords = :keywords WHERE id = :id"
        ), {"keywords": keywords_str, "id": media_id})

    # Drop indexes
    op.drop_index('idx_media_keyword', 'media_keywords')
    op.drop_index('idx_keyword_media', 'media_keywords')
    op.drop_index('ix_keywords_keyword_text', 'keywords')
    op.drop_index('ix_keywords_id', 'keywords')
    op.drop_index('ix_media_items_file_format', 'media_items')

    # Drop tables
    op.drop_table('media_keywords')
    op.drop_table('keywords')
