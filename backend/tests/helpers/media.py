"""
Helpers for creating test media items directly in the database.

These helpers bypass the ingestion pipeline for fast test setup.
Use when you need media items but don't care about testing ingestion itself.
"""

import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional
from PIL import Image

from sqlalchemy.ext.asyncio import AsyncSession

from database import MediaItem


def generate_test_image(path: Path, width: int = 100, height: int = 100, color: tuple = (255, 0, 0)) -> str:
    """Generate a simple test image and return its file hash.

    Args:
        path: Where to save the image
        width: Image width in pixels
        height: Image height in pixels
        color: RGB tuple for fill color

    Returns:
        SHA256 hash of the file
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    # Create a simple solid color image
    img = Image.new("RGB", (width, height), color)
    img.save(path, format="PNG")

    # Calculate file hash
    with open(path, "rb") as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()

    return file_hash


async def create_media_item(
    session: AsyncSession,
    *,
    file_path: Optional[Path] = None,
    file_hash: Optional[str] = None,
    file_format: str = "png",
    width: int = 100,
    height: int = 100,
    file_size: int = 1000,
    vlm_caption: Optional[str] = None,
    metadata_status: str = "completed",
    clip_status: str = "pending",
    vlm_caption_status: str = "pending",
    face_detection_status: str = "pending",
    created_date: Optional[datetime] = None,
    generation_metadata: Optional[str] = None,
    extracted_prompt: Optional[str] = None,
    tool_id: Optional[str] = None,
    duration: Optional[float] = None,
    raw_metadata: Optional[str] = None,
    # Audio-specific metadata
    audio_sample_rate: Optional[int] = None,
    audio_channels: Optional[int] = None,
    audio_bit_depth: Optional[int] = None,
    audio_bitrate: Optional[int] = None,
    audio_codec: Optional[str] = None,
) -> MediaItem:
    """Create a single MediaItem directly in the database.

    Args:
        session: Database session
        file_path: Path to the file (can be fake for DB-only tests)
        file_hash: File hash (generated if not provided)
        file_format: File format (png, jpg, mp4, etc.)
        width: Image width
        height: Image height
        file_size: File size in bytes
        vlm_caption: Optional caption for search tests
        metadata_status: Processing status for metadata
        clip_status: Processing status for CLIP embedding
        vlm_caption_status: Processing status for VLM caption
        face_detection_status: Processing status for face detection
        created_date: File creation date (for date filtering)
        generation_metadata: JSON string marking as generated (sets is_generated=True in API)
        extracted_prompt: Prompt extracted from generated image
        tool_id: Tool ID that created the media
        duration: Duration in seconds (for audio/video)
        raw_metadata: Raw metadata JSON string (for structured types)

    Returns:
        The created MediaItem
    """
    if file_hash is None:
        # Generate a unique hash based on current time
        file_hash = hashlib.sha256(str(datetime.now().timestamp()).encode()).hexdigest()

    if file_path is None:
        file_path = Path(f"/fake/path/{file_hash[:8]}.{file_format}")

    megapixels = (width * height) / 1_000_000

    item = MediaItem(
        file_hash=file_hash,
        file_path=str(file_path),
        file_format=file_format,
        width=width,
        height=height,
        file_size=file_size,
        megapixels=megapixels,
        vlm_caption=vlm_caption,
        metadata_status=metadata_status,
        clip_status=clip_status,
        vlm_caption_status=vlm_caption_status,
        face_detection_status=face_detection_status,
        indexed_date=datetime.now(),
        created_date=created_date,
        generation_metadata=generation_metadata,
        extracted_prompt=extracted_prompt,
        tool_id=tool_id,
        duration=duration,
        raw_metadata=raw_metadata,
        # Audio-specific metadata
        audio_sample_rate=audio_sample_rate,
        audio_channels=audio_channels,
        audio_bit_depth=audio_bit_depth,
        audio_bitrate=audio_bitrate,
        audio_codec=audio_codec,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)

    return item


async def create_test_media(
    session: AsyncSession,
    count: int = 5,
    temp_dir: Optional[Path] = None,
    with_captions: bool = False,
) -> list[MediaItem]:
    """Create multiple test media items.

    Args:
        session: Database session
        count: Number of items to create
        temp_dir: Optional directory to create real image files
        with_captions: If True, add unique captions for search testing

    Returns:
        List of created MediaItem objects
    """
    items = []
    colors = [
        (255, 0, 0),    # Red
        (0, 255, 0),    # Green
        (0, 0, 255),    # Blue
        (255, 255, 0),  # Yellow
        (255, 0, 255),  # Magenta
        (0, 255, 255),  # Cyan
        (128, 128, 128),  # Gray
        (255, 128, 0),  # Orange
        (128, 0, 255),  # Purple
        (0, 128, 128),  # Teal
    ]

    for i in range(count):
        color = colors[i % len(colors)]

        if temp_dir:
            # Create real image file
            file_path = temp_dir / f"test_image_{i}.png"
            file_hash = generate_test_image(file_path, color=color)
        else:
            file_path = None
            file_hash = None

        caption = f"Test image {i} with {['red', 'green', 'blue', 'yellow', 'magenta', 'cyan', 'gray', 'orange', 'purple', 'teal'][i % 10]} color" if with_captions else None

        item = await create_media_item(
            session,
            file_path=file_path,
            file_hash=file_hash,
            vlm_caption=caption,
            vlm_caption_status="complete" if caption else "pending",
        )
        items.append(item)

    return items
