"""Source availability semantics for the fast-discovery scan.

Sources come and go (unmounts, permission hiccups, network shares). Media
under an offline root must flit out of browse views and flit back when the
root returns — never get buried permanently or re-ingested from scratch.
"""

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import delete, select

from config import FolderConfig
from database import DeleteOperation, MediaItem
from ingestion import MediaIngestion
from tests.helpers.media import create_media_item


class _StubSettings:
    def __init__(self, folders):
        self._folders = folders

    def get_folders_for_profile(self, profile_id):
        return self._folders


class _StubDatabase:
    def __init__(self, session_maker):
        self.async_session_maker = session_maker


def _build_ingestion(session_maker, folder_paths):
    ingestion = MediaIngestion.__new__(MediaIngestion)
    ingestion.settings = _StubSettings(
        [
            FolderConfig(path=str(path), refresh_interval_seconds=300, markers=[])
            for path in folder_paths
        ]
    )

    async def _get_profile_db(profile_id):
        return _StubDatabase(session_maker)

    ingestion._get_profile_db = _get_profile_db
    return ingestion


def _write_media_file(path: Path, content: bytes = b"png") -> datetime:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return datetime.utcfromtimestamp(path.stat().st_mtime)


async def _seed_item(
    session_maker,
    file_path: Path,
    *,
    modified_date: datetime | None,
    file_size: int,
    file_unavailable: bool = False,
):
    async with session_maker() as session:
        item = await create_media_item(
            session, file_path=file_path, file_size=file_size
        )
        item.modified_date = modified_date
        item.file_unavailable = file_unavailable
        if file_unavailable:
            item.file_unavailable_since = datetime.utcnow()
        await session.commit()
        return item.id


async def _get_item(session_maker, item_id: int) -> MediaItem:
    async with session_maker() as session:
        return (
            await session.execute(select(MediaItem).where(MediaItem.id == item_id))
        ).scalar_one()


async def _items_at_path(session_maker, file_path: Path) -> list[MediaItem]:
    async with session_maker() as session:
        return list(
            (
                await session.execute(
                    select(MediaItem).where(MediaItem.file_path == str(file_path))
                )
            ).scalars()
        )


async def _run_scan(ingestion):
    with patch("app_dirs.get_source_excluded_roots", return_value=[]):
        return await ingestion._scan_and_sync_profile("default")


@pytest.mark.asyncio
async def test_source_scan_defers_to_active_permanent_deletion(
    db_session,
    tmp_path,
):
    source = tmp_path / "source"
    source.mkdir()
    ingestion = _build_ingestion(db_session, [source])
    async with db_session() as session:
        operation = DeleteOperation(
            kind="asset",
            profile_id="default",
            status="running",
            current_phase="unlinking_artifacts",
            total_items=1,
        )
        session.add(operation)
        await session.commit()
        operation_id = operation.id

    with patch(
        "ingestion.fast_scan_directories",
        new_callable=AsyncMock,
    ) as scan:
        assert await ingestion._scan_and_sync_profile("default") == 0
    scan.assert_not_awaited()

    async with db_session() as session:
        await session.execute(
            delete(DeleteOperation).where(DeleteOperation.id == operation_id)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_offline_root_never_marks_files_unavailable(db_session, tmp_path):
    online = tmp_path / "online"
    online_file = online / "kept.png"
    mtime = _write_media_file(online_file)
    offline = tmp_path / "unmounted"

    online_id = await _seed_item(
        db_session, online_file, modified_date=mtime, file_size=3
    )
    offline_id = await _seed_item(
        db_session,
        offline / "elsewhere.png",
        modified_date=datetime.utcnow(),
        file_size=3,
    )

    ingestion = _build_ingestion(db_session, [online, offline])
    await _run_scan(ingestion)

    assert not (await _get_item(db_session, online_id)).file_unavailable
    assert not (await _get_item(db_session, offline_id)).file_unavailable


@pytest.mark.asyncio
async def test_deleted_file_under_online_root_marked_unavailable(db_session, tmp_path):
    online = tmp_path / "online2"
    online.mkdir()
    gone_id = await _seed_item(
        db_session,
        online / "gone.png",
        modified_date=datetime.utcnow(),
        file_size=3,
    )

    ingestion = _build_ingestion(db_session, [online])
    await _run_scan(ingestion)

    item = await _get_item(db_session, gone_id)
    assert item.file_unavailable
    assert item.file_unavailable_since is not None


@pytest.mark.asyncio
async def test_identical_file_reappearing_is_restored_in_place(db_session, tmp_path):
    online = tmp_path / "online3"
    returned = online / "returned.png"
    mtime = _write_media_file(returned, b"bytes")

    returned_id = await _seed_item(
        db_session,
        returned,
        modified_date=mtime,
        file_size=returned.stat().st_size,
        file_unavailable=True,
    )

    ingestion = _build_ingestion(db_session, [online])
    await _run_scan(ingestion)

    item = await _get_item(db_session, returned_id)
    assert not item.file_unavailable
    assert item.file_unavailable_since is None
    # Restored in place: no duplicate Media identity for the same bytes.
    assert len(await _items_at_path(db_session, returned)) == 1


@pytest.mark.asyncio
async def test_changed_file_reappearing_becomes_new_media(db_session, tmp_path):
    online = tmp_path / "online4"
    changed = online / "changed.png"
    mtime = _write_media_file(changed, b"new-bytes-after-offline-edit")

    old_id = await _seed_item(
        db_session,
        changed,
        modified_date=mtime,
        file_size=changed.stat().st_size + 999,
        file_unavailable=True,
    )

    ingestion = _build_ingestion(db_session, [online])
    await _run_scan(ingestion)

    old_item = await _get_item(db_session, old_id)
    assert old_item.file_unavailable

    items = await _items_at_path(db_session, changed)
    assert len(items) == 2
    new_item = next(item for item in items if item.id != old_id)
    assert new_item.metadata_status == "pending"
    assert not new_item.file_unavailable
