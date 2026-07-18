"""Watched-file re-ingest guards (born from the buried-library incident).

A reappearing watched file whose bytes are unchanged must restore its
original Media row in place — never grow a new revision — and bytes whose
Asset the user trashed must never resurface as a fresh active Asset.
"""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from asset_service import create_asset_from_media, trash_asset
from database import Asset, AssetRevision, MediaItem
from storage_service import register_external_asset
from tests.helpers.media import create_media_item


MTIME = datetime(2026, 7, 1, 12, 0, 0)


async def _seed_watched_asset(
    session,
    file_path: Path,
    *,
    file_hash: str,
    trashed: bool = False,
) -> tuple[int, int, int]:
    """Original pre-damage state: available media backing a watched-file Asset."""
    media = await create_media_item(
        session, file_path=file_path, file_hash=file_hash, file_size=1000
    )
    media.modified_date = MTIME
    asset = await create_asset_from_media(
        session,
        media_id=media.id,
        origin_type="watched_file",
        origin_id=str(file_path),
    )
    if trashed:
        await trash_asset(session, asset_id=asset.id)
    await session.commit()
    return media.id, asset.id, asset.current_revision_id


async def _bury(session, media_id: int) -> None:
    """The old sweep: mark the original unavailable."""
    media = await session.get(MediaItem, media_id)
    media.file_unavailable = True
    media.file_unavailable_since = datetime.utcnow()
    await session.commit()


async def _media(session_maker, media_id: int) -> MediaItem:
    async with session_maker() as session:
        return (
            await session.execute(select(MediaItem).where(MediaItem.id == media_id))
        ).scalar_one()


async def _asset(session_maker, asset_id: int) -> Asset:
    async with session_maker() as session:
        return (
            await session.execute(select(Asset).where(Asset.id == asset_id))
        ).scalar_one()


async def _live_revisions(session_maker, asset_id: int) -> list[AssetRevision]:
    async with session_maker() as session:
        return list(
            (
                await session.execute(
                    select(AssetRevision).where(
                        AssetRevision.asset_id == asset_id,
                        AssetRevision.deleted_at.is_(None),
                    )
                )
            ).scalars()
        )


@pytest.mark.asyncio
async def test_register_never_creates_revision_for_unchanged_bytes(db_session, tmp_path):
    path = tmp_path / "touched-not-changed.png"
    path.write_bytes(b"png")

    async with db_session() as session:
        old_media, asset_id, rev_id = await _seed_watched_asset(
            session, path, file_hash="hash-same"
        )
        await _bury(session, old_media)
        # Fixed-build ingest of the reappeared identical file.
        new_media = await create_media_item(
            session, file_path=path, file_hash="hash-same", file_size=1000
        )
        _, asset = await register_external_asset(session, media=new_media)
        await session.commit()
        new_media_id = new_media.id

    assert asset.id == asset_id
    assert (await _media(db_session, old_media)).file_unavailable is False
    assert (await _media(db_session, new_media_id)).deleted_at is not None
    assert [r.id for r in await _live_revisions(db_session, asset_id)] == [rev_id]


@pytest.mark.asyncio
async def test_register_never_resurrects_trashed_assets(db_session, tmp_path):
    unchanged = tmp_path / "trashed-unchanged.png"
    unchanged.write_bytes(b"png")
    changed = tmp_path / "trashed-changed.png"
    changed.write_bytes(b"png2")

    async with db_session() as session:
        old_a, asset_a, rev_a = await _seed_watched_asset(
            session, unchanged, file_hash="hash-a", trashed=True
        )
        await _bury(session, old_a)
        old_b, asset_b, rev_b = await _seed_watched_asset(
            session, changed, file_hash="hash-b-before", trashed=True
        )
        await _bury(session, old_b)

        same = await create_media_item(
            session, file_path=unchanged, file_hash="hash-a", file_size=1000
        )
        _, got_a = await register_external_asset(session, media=same)

        edited = await create_media_item(
            session, file_path=changed, file_hash="hash-b-after", file_size=1234
        )
        _, got_b = await register_external_asset(session, media=edited)
        await session.commit()

    # Unchanged bytes: restored in place, asset untouched and still trashed.
    assert got_a.id == asset_a
    assert (await _asset(db_session, asset_a)).state == "trashed"
    assert (await _media(db_session, old_a)).file_unavailable is False
    assert (await _asset(db_session, asset_a)).current_revision_id == rev_a

    # Changed bytes: history advances on the SAME asset, which stays trashed —
    # no new active asset appears anywhere.
    assert got_b.id == asset_b
    trashed_b = await _asset(db_session, asset_b)
    assert trashed_b.state == "trashed"
    assert trashed_b.current_revision_id != rev_b
    async with db_session() as session:
        active_dupes = (
            await session.execute(
                select(Asset).where(
                    Asset.state == "active",
                    Asset.origin_id.in_([str(unchanged), str(changed)]),
                )
            )
        ).scalars().all()
    assert active_dupes == []
