"""Tests for the ephemeral media scope used by one-shot flow-as-tool runs.

``purge_ephemeral_run`` must hard-delete a run's media (rows + files), leave
normal library media untouched, and not trip on self-referential
``superseded_by`` links within the run.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete, select

from cleanup_service import CleanupService
from database import MediaItem
from flow_runtime.ephemeral import (
    current_ephemeral_run_id,
    ephemeral_run,
    new_ephemeral_run_id,
    purge_ephemeral_run,
)
from utils.query_builder import build_filtered_query


def test_ephemeral_run_contextvar():
    assert current_ephemeral_run_id() is None
    rid = new_ephemeral_run_id()
    with ephemeral_run(rid):
        assert current_ephemeral_run_id() == rid
    assert current_ephemeral_run_id() is None


def _make_media(file_path, file_hash, *, ephemeral_run_id=None, indexed_date=None):
    kwargs = dict(
        file_path=str(file_path),
        file_hash=file_hash,
        file_size=10,
        file_format="png",
        width=1,
        height=1,
        megapixels=0.0,
        ephemeral_run_id=ephemeral_run_id,
        is_hidden=True if ephemeral_run_id else None,
    )
    if indexed_date is not None:
        kwargs["indexed_date"] = indexed_date
    return MediaItem(**kwargs)


@pytest.mark.asyncio
async def test_purge_ephemeral_run_hard_deletes_only_the_run(db_session, tmp_path):
    run_id = "eph_test_purge"

    eph_paths = [tmp_path / "eph_0.png", tmp_path / "eph_1.png"]
    keep_path = tmp_path / "keep.png"
    for p in (*eph_paths, keep_path):
        p.write_bytes(b"x" * 10)

    async with db_session() as session:
        eph0 = _make_media(eph_paths[0], "he0", ephemeral_run_id=run_id)
        eph1 = _make_media(eph_paths[1], "he1", ephemeral_run_id=run_id)
        keep = _make_media(keep_path, "hek")  # normal library media — must survive
        session.add_all([eph0, eph1, keep])
        await session.flush()
        # self-referential supersede link *within the run* — must not block delete
        eph0.superseded_by = eph1.id
        await session.commit()
        keep_id = keep.id

    async with db_session() as session:
        deleted = await purge_ephemeral_run(session, run_id)

    assert deleted == 2
    # ephemeral files removed; the normal file is untouched
    assert not eph_paths[0].exists()
    assert not eph_paths[1].exists()
    assert keep_path.exists()

    async with db_session() as session:
        remaining = (
            await session.execute(
                select(MediaItem).where(MediaItem.ephemeral_run_id == run_id)
            )
        ).scalars().all()
        assert remaining == []
        kept = (
            await session.execute(select(MediaItem).where(MediaItem.id == keep_id))
        ).scalar_one_or_none()
        assert kept is not None and kept.ephemeral_run_id is None

        # don't leak the survivor into other module-scoped tests
        await session.execute(delete(MediaItem).where(MediaItem.id == keep_id))
        await session.commit()


@pytest.mark.asyncio
async def test_purge_ephemeral_run_noop_when_empty(db_session):
    async with db_session() as session:
        assert await purge_ephemeral_run(session, "eph_does_not_exist") == 0


@pytest.mark.asyncio
async def test_build_filtered_query_excludes_ephemeral(db_session):
    """The shared base query must hide ephemeral media but return normal media."""
    run_id = "eph_filter_test"

    async with db_session() as session:
        normal = _make_media("/fake/qb_normal.png", "qbn")  # normal library media
        eph = _make_media("/fake/qb_eph.png", "qbe", ephemeral_run_id=run_id)
        session.add_all([normal, eph])
        await session.commit()
        normal_id = normal.id
        eph_id = eph.id

    try:
        async with db_session() as session:
            base = select(MediaItem.id)

            # Default: ephemeral excluded.
            filtered = build_filtered_query(base)
            ids = set((await session.execute(filtered)).scalars().all())
            assert normal_id in ids
            assert eph_id not in ids

            # Opt-in: ephemeral surfaced (used by the runner/sweeper paths, not the UI).
            with_eph = build_filtered_query(base, include_ephemeral=True)
            ids_all = set((await session.execute(with_eph)).scalars().all())
            assert normal_id in ids_all
            assert eph_id in ids_all
    finally:
        # don't leak rows into other module-scoped tests
        async with db_session() as session:
            await session.execute(
                delete(MediaItem).where(MediaItem.id.in_([normal_id, eph_id]))
            )
            await session.commit()


@pytest.mark.asyncio
async def test_cleanup_ephemeral_media_sweeps_only_old_orphans(db_session, tmp_path):
    """The crash sweeper hard-deletes old orphaned ephemeral media (rows + files)
    and leaves recent ephemeral media + normal library media untouched."""
    old_run = "eph_sweep_old"
    recent_run = "eph_sweep_recent"

    old_path = tmp_path / "sweep_old.png"
    recent_path = tmp_path / "sweep_recent.png"
    keep_path = tmp_path / "sweep_keep.png"
    for p in (old_path, recent_path, keep_path):
        p.write_bytes(b"x" * 10)

    old_indexed = datetime.utcnow() - timedelta(minutes=90)
    recent_indexed = datetime.utcnow() - timedelta(minutes=1)

    async with db_session() as session:
        old = _make_media(
            old_path, "swo", ephemeral_run_id=old_run, indexed_date=old_indexed
        )
        recent = _make_media(
            recent_path, "swr", ephemeral_run_id=recent_run, indexed_date=recent_indexed
        )
        keep = _make_media(keep_path, "swk")  # normal library media — must survive
        session.add_all([old, recent, keep])
        await session.commit()
        recent_id = recent.id
        keep_id = keep.id

    async with db_session() as session:
        swept = await CleanupService().cleanup_ephemeral_media(
            session, older_than_minutes=30
        )

    assert swept == 1  # only the old orphaned run

    # old ephemeral file gone; recent ephemeral + normal files untouched
    assert not old_path.exists()
    assert recent_path.exists()
    assert keep_path.exists()

    async with db_session() as session:
        old_remaining = (
            await session.execute(
                select(MediaItem).where(MediaItem.ephemeral_run_id == old_run)
            )
        ).scalars().all()
        assert old_remaining == []

        recent_remaining = (
            await session.execute(select(MediaItem).where(MediaItem.id == recent_id))
        ).scalar_one_or_none()
        assert recent_remaining is not None

        kept = (
            await session.execute(select(MediaItem).where(MediaItem.id == keep_id))
        ).scalar_one_or_none()
        assert kept is not None and kept.ephemeral_run_id is None

        # clean up survivors so other module-scoped tests see a pristine DB
        await session.execute(
            delete(MediaItem).where(MediaItem.id.in_([recent_id, keep_id]))
        )
        await session.commit()
