"""Lineage writers keep a finished output when a source Media is gone.

A ToolView reference slot can remember a source after it was permanently
deleted: a cropped or otherwise prepared copy still runs, so the job finishes
and its lineage must not point at the missing Media row.
"""

from sqlalchemy import select

from database import MediaLineage
from tests.helpers.media import create_media_item
from utils.lineage import record_lineage, record_lineage_from_inputs

GONE = 987654


async def _rows(session, media_id):
    return list(await session.scalars(
        select(MediaLineage).where(MediaLineage.media_id == media_id).order_by(MediaLineage.source_order)
    ))


async def test_inputs_with_deleted_source_fall_back_to_file_path(db_session):
    async with db_session() as session:
        kept = await create_media_item(session)
        output = await create_media_item(session)
        await record_lineage_from_inputs(session, output.id, [
            {"media_id": GONE, "file_path": "/objects/media/gone/ref.jpg", "role": "input_image"},
            {"media_id": kept.id, "file_path": "/objects/media/kept.jpg", "role": "input_image"},
        ], "image-to-image")
        await session.commit()

        rows = await _rows(session, output.id)
        assert [(r.source_media_id, r.source_file_path) for r in rows] == [
            (None, "/objects/media/gone/ref.jpg"),
            (kept.id, None),
        ]


async def test_record_lineage_skips_deleted_sources(db_session):
    async with db_session() as session:
        kept = await create_media_item(session)
        output = await create_media_item(session)
        await record_lineage(session, output.id, [GONE, kept.id], "grid-creation")
        await session.commit()

        rows = await _rows(session, output.id)
        assert [(r.source_media_id, r.source_order) for r in rows] == [(kept.id, 0)]
