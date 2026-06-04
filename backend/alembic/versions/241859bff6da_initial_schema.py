"""initial_schema

Revision ID: 241859bff6da
Revises:
Create Date: 2025-11-16 11:09:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '241859bff6da'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create all tables from scratch."""
    op.create_table(
        'media_items',
        sa.Column('id', sa.Integer(), nullable=False),

        # File information
        sa.Column('file_path', sa.String(), nullable=False),
        sa.Column('file_hash', sa.String(), nullable=False),
        sa.Column('file_size', sa.Integer(), nullable=False),
        sa.Column('file_format', sa.String(), nullable=False),

        # Media properties
        sa.Column('width', sa.Integer(), nullable=False),
        sa.Column('height', sa.Integer(), nullable=False),
        sa.Column('megapixels', sa.Float(), nullable=False),
        sa.Column('duration', sa.Float(), nullable=True),

        # Dates
        sa.Column('created_date', sa.DateTime(), nullable=True),
        sa.Column('modified_date', sa.DateTime(), nullable=True),
        sa.Column('indexed_date', sa.DateTime(), nullable=False),

        # AI/ML processed data
        sa.Column('clip_embedding', sa.LargeBinary(), nullable=True),
        sa.Column('vlm_caption', sa.String(), nullable=True),
        sa.Column('raw_metadata', sa.String(), nullable=True),
        sa.Column('extracted_prompt', sa.String(), nullable=True),
        sa.Column('keywords', sa.String(), nullable=True),

        # Config version tracking
        sa.Column('clip_config_version', sa.String(), nullable=True),
        sa.Column('vlm_caption_config_version', sa.String(), nullable=True),
        sa.Column('vlm_extract_config_version', sa.String(), nullable=True),
        sa.Column('llm_keywords_config_version', sa.String(), nullable=True),

        # Per-phase status
        sa.Column('clip_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('vlm_caption_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('vlm_extract_status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('llm_keywords_status', sa.String(), nullable=False, server_default='pending'),

        # Per-phase completion timestamps
        sa.Column('clip_processed_at', sa.DateTime(), nullable=True),
        sa.Column('vlm_caption_processed_at', sa.DateTime(), nullable=True),
        sa.Column('vlm_extract_processed_at', sa.DateTime(), nullable=True),
        sa.Column('llm_keywords_processed_at', sa.DateTime(), nullable=True),

        # Per-phase error tracking
        sa.Column('clip_error', sa.String(), nullable=True),
        sa.Column('clip_retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vlm_caption_error', sa.String(), nullable=True),
        sa.Column('vlm_caption_retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('vlm_extract_error', sa.String(), nullable=True),
        sa.Column('vlm_extract_retry_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('llm_keywords_error', sa.String(), nullable=True),
        sa.Column('llm_keywords_retry_count', sa.Integer(), nullable=False, server_default='0'),

        sa.PrimaryKeyConstraint('id')
    )

    # Create indexes
    op.create_index(op.f('ix_media_items_file_path'), 'media_items', ['file_path'], unique=True)
    op.create_index(op.f('ix_media_items_file_hash'), 'media_items', ['file_hash'], unique=False)
    op.create_index(op.f('ix_media_items_megapixels'), 'media_items', ['megapixels'], unique=False)
    op.create_index(op.f('ix_media_items_created_date'), 'media_items', ['created_date'], unique=False)
    op.create_index(op.f('ix_media_items_modified_date'), 'media_items', ['modified_date'], unique=False)
    op.create_index(op.f('ix_media_items_indexed_date'), 'media_items', ['indexed_date'], unique=False)
    op.create_index(op.f('ix_media_items_clip_status'), 'media_items', ['clip_status'], unique=False)
    op.create_index(op.f('ix_media_items_vlm_caption_status'), 'media_items', ['vlm_caption_status'], unique=False)
    op.create_index(op.f('ix_media_items_vlm_extract_status'), 'media_items', ['vlm_extract_status'], unique=False)
    op.create_index(op.f('ix_media_items_llm_keywords_status'), 'media_items', ['llm_keywords_status'], unique=False)
    op.create_index('idx_created_desc', 'media_items', [sa.text('created_date DESC')], unique=False)
    op.create_index('idx_indexed_desc', 'media_items', [sa.text('indexed_date DESC')], unique=False)


def downgrade() -> None:
    """Drop all tables."""
    op.drop_index('idx_indexed_desc', table_name='media_items')
    op.drop_index('idx_created_desc', table_name='media_items')
    op.drop_index(op.f('ix_media_items_llm_keywords_status'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_vlm_extract_status'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_vlm_caption_status'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_clip_status'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_indexed_date'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_modified_date'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_created_date'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_megapixels'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_file_hash'), table_name='media_items')
    op.drop_index(op.f('ix_media_items_file_path'), table_name='media_items')
    op.drop_table('media_items')
