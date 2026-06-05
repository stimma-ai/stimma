"""add_face_detection

Revision ID: e031f59ab103
Revises: 85d85ace5bb9
Create Date: 2025-11-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e031f59ab103'
down_revision: Union[str, Sequence[str], None] = '85d85ace5bb9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add face detection tables and tracking columns."""

    # Import for table checking
    from sqlalchemy import inspect

    conn = op.get_bind()
    inspector = inspect(conn)
    existing_tables = inspector.get_table_names()

    # Create faces table only if it doesn't exist
    if 'faces' not in existing_tables:
        op.create_table(
            'faces',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('media_id', sa.Integer(), nullable=False),
            sa.Column('bbox_x', sa.Float(), nullable=False),
            sa.Column('bbox_y', sa.Float(), nullable=False),
            sa.Column('bbox_width', sa.Float(), nullable=False),
            sa.Column('bbox_height', sa.Float(), nullable=False),
            sa.Column('confidence', sa.Float(), nullable=False),
            sa.Column('auraface_embedding', sa.LargeBinary(), nullable=True),
            sa.Column('landmarks', sa.String(), nullable=True),  # JSON string
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.PrimaryKeyConstraint('id'),
            sa.ForeignKeyConstraint(['media_id'], ['media_items.id'], ondelete='CASCADE')
        )

        # Create indexes on faces table
        op.create_index('ix_faces_media_id', 'faces', ['media_id'])
        op.create_index('ix_faces_confidence', 'faces', ['confidence'])

    # Add face_detection phase tracking columns to media_items
    existing_columns = [col['name'] for col in inspector.get_columns('media_items')]

    if 'face_detection_status' not in existing_columns:
        op.add_column('media_items', sa.Column('face_detection_status', sa.String(), nullable=False, server_default='pending'))
    if 'face_detection_config_version' not in existing_columns:
        op.add_column('media_items', sa.Column('face_detection_config_version', sa.String(), nullable=True))
    if 'face_detection_processed_at' not in existing_columns:
        op.add_column('media_items', sa.Column('face_detection_processed_at', sa.DateTime(), nullable=True))
    if 'face_detection_error' not in existing_columns:
        op.add_column('media_items', sa.Column('face_detection_error', sa.String(), nullable=True))
    if 'face_detection_retry_count' not in existing_columns:
        op.add_column('media_items', sa.Column('face_detection_retry_count', sa.Integer(), nullable=False, server_default='0'))

    # Create index on face_detection_status for efficient querying
    existing_indexes = [idx['name'] for idx in inspector.get_indexes('media_items')]
    if 'ix_media_items_face_detection_status' not in existing_indexes:
        op.create_index('ix_media_items_face_detection_status', 'media_items', ['face_detection_status'])


def downgrade() -> None:
    """Remove face detection tables and tracking columns."""

    # Drop index and columns from media_items
    op.drop_index('ix_media_items_face_detection_status', table_name='media_items')
    op.drop_column('media_items', 'face_detection_retry_count')
    op.drop_column('media_items', 'face_detection_error')
    op.drop_column('media_items', 'face_detection_processed_at')
    op.drop_column('media_items', 'face_detection_config_version')
    op.drop_column('media_items', 'face_detection_status')

    # Drop indexes and table
    op.drop_index('ix_faces_confidence', table_name='faces')
    op.drop_index('ix_faces_media_id', table_name='faces')
    op.drop_table('faces')
