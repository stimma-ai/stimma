"""add_library_management_features

Revision ID: d5ff85f1130d
Revises: 24362b773b75
Create Date: 2025-11-20 20:43:55.732494

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd5ff85f1130d'
down_revision: Union[str, Sequence[str], None] = '24362b773b75'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to add library management features: markers, tags, collections, and soft delete."""
    from sqlalchemy import text

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    # 1. Create markers table if it doesn't exist
    if 'markers' not in existing_tables:
        op.create_table(
            'markers',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('icon_svg', sa.String(), nullable=False),
            sa.Column('color', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_markers_id', 'markers', ['id'])
        op.create_index('ix_markers_name', 'markers', ['name'], unique=True)

        # Seed default 'favorite' marker with heroicons heart icon
        connection.execute(text("""
            INSERT INTO markers (name, icon_svg, color)
            VALUES (
                'favorite',
                '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor"><path d="m11.645 20.91-.007-.003-.022-.012a15.247 15.247 0 0 1-.383-.218 25.18 25.18 0 0 1-4.244-3.17C4.688 15.36 2.25 12.174 2.25 8.25 2.25 5.322 4.714 3 7.688 3A5.5 5.5 0 0 1 12 5.052 5.5 5.5 0 0 1 16.313 3c2.973 0 5.437 2.322 5.437 5.25 0 3.925-2.438 7.111-4.739 9.256a25.175 25.175 0 0 1-4.244 3.17 15.247 15.247 0 0 1-.383.219l-.022.012-.007.004-.003.001a.752.752 0 0 1-.704 0l-.003-.001Z" /></svg>',
                '#ef4444'
            )
        """))

    # 2. Create media_markers junction table if it doesn't exist
    if 'media_markers' not in existing_tables:
        op.create_table(
            'media_markers',
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('marker_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('media_id', 'marker_id')
        )
        op.create_index('idx_marker_media', 'media_markers', ['marker_id', 'media_id'])
        op.create_index('idx_media_marker', 'media_markers', ['media_id', 'marker_id'])

    # 3. Create tags table if it doesn't exist (separate from AI keywords)
    if 'tags' not in existing_tables:
        op.create_table(
            'tags',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('tag_text', sa.String(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_tags_id', 'tags', ['id'])
        op.create_index('ix_tags_tag_text', 'tags', ['tag_text'], unique=True)

    # 4. Create media_tags junction table if it doesn't exist
    if 'media_tags' not in existing_tables:
        op.create_table(
            'media_tags',
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('tag_id', sa.Integer(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('media_id', 'tag_id')
        )
        op.create_index('idx_tag_media', 'media_tags', ['tag_id', 'media_id'])
        op.create_index('idx_media_tag', 'media_tags', ['media_id', 'tag_id'])

    # 5. Create collections table if it doesn't exist
    if 'collections' not in existing_tables:
        op.create_table(
            'collections',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('name', sa.String(), nullable=False),
            sa.Column('description', sa.String(), nullable=True),
            sa.Column('cover_media_id', sa.Integer(), nullable=True),
            sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('id')
        )
        op.create_index('ix_collections_id', 'collections', ['id'])
        op.create_index('ix_collections_name', 'collections', ['name'])

    # 6. Create media_collections junction table if it doesn't exist
    if 'media_collections' not in existing_tables:
        op.create_table(
            'media_collections',
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('collection_id', sa.Integer(), nullable=False),
            sa.Column('added_at', sa.DateTime(), nullable=False, server_default=sa.text('CURRENT_TIMESTAMP')),
            sa.PrimaryKeyConstraint('media_id', 'collection_id')
        )
        op.create_index('idx_collection_media', 'media_collections', ['collection_id', 'media_id'])
        op.create_index('idx_media_collection', 'media_collections', ['media_id', 'collection_id'])

    # 7. Add deleted_at column to media_items for soft delete (if it doesn't exist)
    existing_columns = [col['name'] for col in inspector.get_columns('media_items')]
    if 'deleted_at' not in existing_columns:
        op.add_column('media_items', sa.Column('deleted_at', sa.DateTime(), nullable=True))
        op.create_index('ix_media_items_deleted_at', 'media_items', ['deleted_at'])

    # Run ANALYZE to update SQLite statistics for query optimization
    connection.execute(text("ANALYZE"))

    print("Successfully added library management features: markers, tags, collections, and soft delete")


def downgrade() -> None:
    """Downgrade schema - remove library management features."""

    # Remove indexes and tables in reverse order
    op.drop_index('ix_media_items_deleted_at', 'media_items')
    op.drop_column('media_items', 'deleted_at')

    op.drop_index('idx_media_collection', 'media_collections')
    op.drop_index('idx_collection_media', 'media_collections')
    op.drop_table('media_collections')

    op.drop_index('ix_collections_name', 'collections')
    op.drop_index('ix_collections_id', 'collections')
    op.drop_table('collections')

    op.drop_index('idx_media_tag', 'media_tags')
    op.drop_index('idx_tag_media', 'media_tags')
    op.drop_table('media_tags')

    op.drop_index('ix_tags_tag_text', 'tags')
    op.drop_index('ix_tags_id', 'tags')
    op.drop_table('tags')

    op.drop_index('idx_media_marker', 'media_markers')
    op.drop_index('idx_marker_media', 'media_markers')
    op.drop_table('media_markers')

    op.drop_index('ix_markers_name', 'markers')
    op.drop_index('ix_markers_id', 'markers')
    op.drop_table('markers')
