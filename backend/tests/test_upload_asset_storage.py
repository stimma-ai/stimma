"""Uploads become managed Assets rather than flat-folder Media."""

import io

import pytest
from PIL import Image
from sqlalchemy import select

from database import AssetRevision, StorageObject
from upload_service import UploadService


@pytest.mark.asyncio
async def test_upload_creates_asset_and_managed_storage(
    test_app, db_session
):
    buffer = io.BytesIO()
    Image.new("RGB", (12, 8), (20, 40, 60)).save(buffer, format="PNG")

    media, returned_path = await UploadService("default").upload_file(
        buffer.getvalue(), "human-name.png"
    )

    assert returned_path == media.file_path
    assert media.original_filename == "human-name.png"
    assert media.storage_object_id is not None
    async with db_session() as session:
        storage = await session.get(StorageObject, media.storage_object_id)
        revision = await session.scalar(
            select(AssetRevision).where(AssetRevision.primary_media_id == media.id)
        )
        assert storage.kind == "managed"
        assert revision is not None
