"""add audio metadata columns

Revision ID: y8z9a0b1c2d3
Revises: x7y8z9a0b1c2
Create Date: 2026-01-27 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'y8z9a0b1c2d3'
down_revision: Union[str, Sequence[str], None] = 'x7y8z9a0b1c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add audio metadata columns to media_items.

    These columns store technical metadata for audio files:
    - sample_rate: Hz (e.g., 44100, 48000)
    - channels: 1=mono, 2=stereo, etc.
    - bit_depth: bits per sample (16, 24, 32)
    - bitrate: bits per second
    - codec: codec name (mp3, flac, aac, etc.)
    """
    op.add_column('media_items', sa.Column('audio_sample_rate', sa.Integer(), nullable=True))
    op.add_column('media_items', sa.Column('audio_channels', sa.Integer(), nullable=True))
    op.add_column('media_items', sa.Column('audio_bit_depth', sa.Integer(), nullable=True))
    op.add_column('media_items', sa.Column('audio_bitrate', sa.Integer(), nullable=True))
    op.add_column('media_items', sa.Column('audio_codec', sa.String(), nullable=True))


def downgrade() -> None:
    """Remove audio metadata columns."""
    op.drop_column('media_items', 'audio_codec')
    op.drop_column('media_items', 'audio_bitrate')
    op.drop_column('media_items', 'audio_bit_depth')
    op.drop_column('media_items', 'audio_channels')
    op.drop_column('media_items', 'audio_sample_rate')
