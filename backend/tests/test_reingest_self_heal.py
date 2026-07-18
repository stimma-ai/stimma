"""Self-heal proof for the buried-library incident.

Reconstructs the exact damage the old build inflicted when a source root
scanned as empty — originals buried as unavailable, files re-ingested as
brand-new rows, no-op revisions on unchanged Assets, trashed Assets
resurrected as fresh active duplicates — and proves the repair converges the
database back to the state it was in before the bug, including trash.
"""

from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from asset_migration import collapse_duplicate_reingest
from asset_service import commit_revision, create_asset_from_media, trash_asset
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


async def _old_build_reingest(
    session,
    file_path: Path,
    *,
    file_hash: str,
    original_asset_id: int | None,
    pending: bool = False,
) -> int:
    """What the old build did when the file was seen again: a brand-new row,
    then either a no-op revision on the active original or a fresh active
    Asset when the original was trashed (resurrection)."""
    media = await create_media_item(
        session,
        file_path=file_path,
        file_hash="" if pending else file_hash,
        file_size=1000,
        metadata_status="pending" if pending else "completed",
    )
    media.modified_date = MTIME
    if not pending:
        if original_asset_id is not None:
            await commit_revision(
                session,
                asset_id=original_asset_id,
                media_id=media.id,
                note="Watched file changed",
            )
        else:
            await create_asset_from_media(
                session,
                media_id=media.id,
                origin_type="watched_file",
                origin_id=str(file_path),
            )
    await session.commit()
    return media.id


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
async def test_full_damage_converges_back_to_original_state(db_session, tmp_path):
    active_path = tmp_path / "active.png"
    trashed_path = tmp_path / "cleaned-up.png"
    pending_path = tmp_path / "pending.png"

    async with db_session() as session:
        active_media, active_asset, active_rev = await _seed_watched_asset(
            session, active_path, file_hash="hash-active"
        )
        trashed_media, trashed_asset, trashed_rev = await _seed_watched_asset(
            session, trashed_path, file_hash="hash-trashed", trashed=True
        )
        pending_media, pending_asset, pending_rev = await _seed_watched_asset(
            session, pending_path, file_hash="hash-pending"
        )

        for media_id in (active_media, trashed_media, pending_media):
            await _bury(session, media_id)

        dup_active = await _old_build_reingest(
            session, active_path, file_hash="hash-active",
            original_asset_id=active_asset,
        )
        # Trashed original was invisible to the old build's active-only match:
        # it minted a fresh active Asset for the same bytes.
        dup_trashed = await _old_build_reingest(
            session, trashed_path, file_hash="hash-trashed",
            original_asset_id=None,
        )
        # Re-ingest that never finished hashing before the app quit.
        dup_pending = await _old_build_reingest(
            session, pending_path, file_hash="hash-pending",
            original_asset_id=None, pending=True,
        )

    async with db_session() as session:
        counts = await collapse_duplicate_reingest(session, profile_id="default")
        await session.commit()

    assert counts["restored"] == 3
    assert counts["noop_revisions_removed"] == 1
    assert counts["duplicate_assets_removed"] == 1

    # Originals restored in place, duplicates gone.
    for original_id, dup_id in (
        (active_media, dup_active),
        (trashed_media, dup_trashed),
        (pending_media, dup_pending),
    ):
        original = await _media(db_session, original_id)
        assert original.file_unavailable is False
        assert original.file_unavailable_since is None
        assert original.deleted_at is None
        duplicate = await _media(db_session, dup_id)
        assert duplicate.deleted_at is not None

    # Active asset: current revision rolled back, exactly one live revision.
    asset = await _asset(db_session, active_asset)
    assert asset.state == "active"
    assert asset.current_revision_id == active_rev
    assert [r.id for r in await _live_revisions(db_session, active_asset)] == [active_rev]

    # The user's cleanup pass survives: trashed asset untouched, still trashed,
    # its payload visible to the Trash browser again.
    trashed = await _asset(db_session, trashed_asset)
    assert trashed.state == "trashed"
    assert trashed.current_revision_id == trashed_rev

    # The resurrected duplicate active asset is tombstoned.
    async with db_session() as session:
        resurrected = (
            await session.execute(
                select(Asset)
                .join(AssetRevision, AssetRevision.asset_id == Asset.id)
                .where(
                    AssetRevision.primary_media_id == dup_trashed,
                )
            )
        ).scalars().first()
    assert resurrected is not None
    assert resurrected.deleted_at is not None

    # Idempotent: a second pass finds nothing.
    async with db_session() as session:
        assert await collapse_duplicate_reingest(session) == {}


@pytest.mark.asyncio
async def test_genuinely_changed_content_is_left_alone(db_session, tmp_path):
    changed_path = tmp_path / "edited-while-offline.png"

    async with db_session() as session:
        old_media, asset_id, old_rev = await _seed_watched_asset(
            session, changed_path, file_hash="hash-before"
        )
        await _bury(session, old_media)
        new_media = await _old_build_reingest(
            session, changed_path, file_hash="hash-after",
            original_asset_id=asset_id,
        )

    async with db_session() as session:
        counts = await collapse_duplicate_reingest(session)
        await session.commit()

    assert counts.get("restored") is None
    assert counts["skipped_changed_content"] == 1
    # Real edit: the new revision stands, the old payload stays historical.
    asset = await _asset(db_session, asset_id)
    assert asset.current_revision_id != old_rev
    assert (await _media(db_session, old_media)).file_unavailable is True
    assert (await _media(db_session, new_media)).deleted_at is None


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
