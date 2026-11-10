"""Asset grouping engine (asset_grouping.py) on a real schema with synthetic CLIP vectors."""

import hashlib
import json
from datetime import datetime, timedelta

import numpy as np
import pytest
from sqlalchemy import delete, select

from asset_grouping import (
    CLIP_DIM,
    DEFAULT_DRIFT,
    DEFAULT_LOOKS_ALIKE,
    GroupingEngine,
    calibrate,
    Item,
    prompt_title,
)
from database import (
    Asset,
    AssetGroup,
    AssetGroupMember,
    AssetGroupRef,
    AssetRevision,
    Base,
    Chat,
    ChatItem,
    Database,
    MediaItem,
    MediaLineage,
)

T0 = datetime(2026, 10, 1, 12, 0, 0)
NOW = T0 + timedelta(days=60)
TOOL = "local:gen"


@pytest.fixture
async def db(tmp_path):
    database = Database(str(tmp_path / "grouping.db"))
    async with database.async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield database
    await database.async_engine.dispose()


def unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


class Vectors:
    """Random directions are near-orthogonal in 512 dims (similarity about 0)."""

    def __init__(self, seed=1):
        self.rng = np.random.default_rng(seed)

    def base(self):
        return unit(self.rng.normal(size=CLIP_DIM))

    def near(self, v, sim):
        """A unit vector with cosine ``sim`` to ``v``."""
        noise = self.rng.normal(size=CLIP_DIM)
        noise -= (noise @ v) * v
        noise = unit(noise)
        return unit(sim * v + np.sqrt(1 - sim * sim) * noise)


_n = 0


async def add_media(s, *, at, prompt=None, tool=TOOL, vec=None, clip="completed", meta="completed",
                    folder="/library/shoot", created=None, fmt="png"):
    global _n
    _n += 1
    m = MediaItem(
        file_path=f"{folder}/{_n}.{fmt}",
        file_hash=hashlib.sha256(f"{folder}/{_n}".encode()).hexdigest(),
        file_size=1, file_format=fmt, width=1, height=1, megapixels=0.000001,
        created_date=created or at, indexed_date=created or at, tool_id=tool,
        generation_metadata=json.dumps({"prompt": "rewritten " + prompt, "prompt_metadata": {"original_prompt": prompt}}) if prompt else None,
        metadata_status=meta, clip_status=clip if vec is not None or clip != "completed" else "skipped",
    )
    if vec is not None:
        m.set_embedding(vec)
    s.add(m)
    await s.flush()
    return m


async def add_asset(s, *, at, sources=(), state="active", inspired=None, **kw):
    m = await add_media(s, at=at, **kw)
    if inspired is not None:
        gm = json.loads(m.generation_metadata or "{}")
        gm["parameters"] = {"inspired_by_media_id": inspired}
        m.generation_metadata = json.dumps(gm)
    a = Asset(asset_type="image", state=state, created_at=at, updated_at=at,
              deleted_at=at if state != "active" else None)
    s.add(a)
    await s.flush()
    r = AssetRevision(asset_id=a.id, primary_media_id=m.id, revision_number=1)
    s.add(r)
    await s.flush()
    a.current_revision_id = r.id
    for order, source in enumerate(sources):
        s.add(MediaLineage(media_id=m.id, source_media_id=source, source_order=order, task_type="image-to-video"))
    await s.commit()
    return a.id, m.id


async def run(db, engine=None, **kw):
    engine = engine or GroupingEngine()
    kw.setdefault("now", NOW)
    total = 0
    while True:
        async with db.async_session_maker() as s:
            n = await engine.process(s, **kw)
        total += n
        if not n or "limit" in kw:
            return engine, total


async def homes(db, kind="auto"):
    async with db.async_session_maker() as s:
        rows = (await s.execute(
            select(AssetGroupMember.asset_id, AssetGroupMember.group_id, AssetGroupMember.reason)
            .where(AssetGroupMember.kind == kind)
        )).all()
    return {a: (g, r) for a, g, r in rows}


async def test_same_typed_prompt_joins_even_when_it_looks_different(db):
    v = Vectors()
    async with db.async_session_maker() as s:
        a, _ = await add_asset(s, at=T0, prompt="a lighthouse at dusk", vec=v.base())
        b, _ = await add_asset(s, at=T0 + timedelta(hours=5), prompt="a lighthouse at dusk", vec=v.base())
        c, _ = await add_asset(s, at=T0 + timedelta(hours=6), prompt="a lighthouse at dusk, stormy", vec=v.base())
    await run(db)
    h = await homes(db)
    assert h[b] == (h[a][0], "same prompt")
    # Word overlap is not a link: a different typed prompt is a new group.
    assert h[c][0] != h[a][0]
    async with db.async_session_maker() as s:
        group = await s.get(AssetGroup, h[a][0])
    assert (group.title, group.title_source) == ("a lighthouse at dusk", "prompt")


async def test_drift_stays_a_hop_splits_and_is_not_pulled_back(db):
    v = Vectors()
    a, b = v.base(), v.base()
    async with db.async_session_maker() as s:
        # A run that starts on look a, then (same prompt) moves to look b.
        first, _ = await add_asset(s, at=T0, prompt="p1", vec=v.near(a, 0.99))
        for i in range(1, 3):
            await add_asset(s, at=T0 + timedelta(minutes=i), prompt="p1", vec=v.near(a, 0.99))
        for i in range(3, 7):
            await add_asset(s, at=T0 + timedelta(minutes=i), prompt="p1", vec=v.near(b, 0.99))
        # Drift: a new prompt that still looks like the last four frames.
        drift, _ = await add_asset(s, at=T0 + timedelta(minutes=10), prompt="p2", vec=v.near(b, 0.95))
        # Hop: a new prompt that doesn't look like the last four, though it
        # looks just like the run's first frames (looks-alike would take it).
        hop, _ = await add_asset(s, at=T0 + timedelta(minutes=12), prompt="p3", vec=v.near(a, 0.99))
    await run(db)
    h = await homes(db)
    assert h[drift] == (h[first][0], "drift")
    assert h[hop][1] == "hop"
    assert h[hop][0] != h[first][0]


async def test_looks_alike_joins_an_active_group_but_not_an_idle_one(db):
    v = Vectors()
    a = v.base()
    async with db.async_session_maker() as s:
        first, _ = await add_asset(s, at=T0, prompt="p1", vec=v.near(a, 0.99), tool="x:one")
        near, _ = await add_asset(s, at=T0 + timedelta(days=5), prompt="p2", vec=v.near(a, 0.99), tool="x:two")
        late, _ = await add_asset(s, at=T0 + timedelta(days=40), prompt="p3", vec=v.near(a, 0.99), tool="x:three")
    await run(db)
    h = await homes(db)
    assert h[near] == (h[first][0], "looks alike")
    assert h[late] == (h[late][0], "new") and h[late][0] != h[first][0]


async def test_lineage_joins_an_active_group_and_revisits_an_idle_one(db):
    v = Vectors()
    async with db.async_session_maker() as s:
        source, source_media = await add_asset(s, at=T0, prompt="p", vec=v.base())
        video, _ = await add_asset(s, at=T0 + timedelta(days=3), tool="x:video", vec=v.base(), sources=[source_media])
        # Ten idle days later: a revisit, with the source shown as a ref.
        remix, _ = await add_asset(s, at=T0 + timedelta(days=13), tool="x:edit", vec=v.base(), inspired=source_media)
    await run(db)
    h = await homes(db)
    assert h[video] == (h[source][0], "lineage")
    assert h[remix][1] == "revisit" and h[remix][0] != h[source][0]
    async with db.async_session_maker() as s:
        refs = (await s.execute(select(AssetGroupRef.group_id, AssetGroupRef.asset_id))).all()
    assert refs == [(h[remix][0], source)]
    # Theme still walks lineage all the way back.
    t = await homes(db, "theme")
    assert t[source][0] == t[video][0] == t[remix][0]


async def test_lineage_source_resolves_through_an_older_revision(db):
    v = Vectors()
    async with db.async_session_maker() as s:
        source, old_media = await add_asset(s, at=T0, prompt="p", vec=v.base())
        new_media = await add_media(s, at=T0 + timedelta(hours=1), prompt="p edited", vec=v.base())
        r2 = AssetRevision(asset_id=source, primary_media_id=new_media.id, revision_number=2)
        s.add(r2)
        await s.flush()
        (await s.get(Asset, source)).current_revision_id = r2.id
        await s.commit()
        child, _ = await add_asset(s, at=T0 + timedelta(hours=2), tool="x:video", vec=v.base(), sources=[old_media])
    await run(db)
    h = await homes(db)
    assert h[child] == (h[source][0], "lineage")


async def test_theme_merges_two_themes_into_the_larger(db):
    v = Vectors()
    async with db.async_session_maker() as s:
        a1, a1_media = await add_asset(s, at=T0, prompt="castle", vec=v.base())
        a2, _ = await add_asset(s, at=T0 + timedelta(minutes=1), prompt="castle", vec=v.base())
        b1, _ = await add_asset(s, at=T0 + timedelta(days=30), prompt="forest", vec=v.base())
        # Made from a castle frame, typed with the forest prompt: one theme.
        c, _ = await add_asset(s, at=T0 + timedelta(days=31), prompt="forest", vec=v.base(), sources=[a1_media])
    await run(db)
    t = await homes(db, "theme")
    assert len({t[a][0] for a in (a1, a2, b1, c)}) == 1
    async with db.async_session_maker() as s:
        groups = (await s.execute(select(AssetGroup).where(AssetGroup.kind == "theme"))).scalars().all()
    live = [g for g in groups if g.deleted_at is None]
    assert [g.id for g in live] == [t[a1][0]]  # the larger theme absorbed the smaller
    assert any(g.deleted_at is not None for g in groups)


async def test_pass_stops_at_an_unready_asset_until_clip_lands_or_times_out(db):
    v = Vectors()
    async with db.async_session_maker() as s:
        first, _ = await add_asset(s, at=NOW - timedelta(minutes=30), prompt="p", vec=v.base())
        waiting, waiting_media = await add_asset(s, at=NOW - timedelta(minutes=5), prompt="q", clip="pending")
        after, _ = await add_asset(s, at=NOW - timedelta(minutes=4), prompt="r", vec=v.base())
    engine, placed = await run(db)
    assert placed == 1 and set(await homes(db)) == {first}
    # CLIP disabled: nothing waits for it.
    _, placed = await run(db, engine, clip_enabled=False)
    assert placed == 2 and set(await homes(db)) == {first, waiting, after}


async def test_pending_clip_times_out_after_ten_minutes(db):
    async with db.async_session_maker() as s:
        waiting, _ = await add_asset(s, at=NOW - timedelta(minutes=9), prompt="q", clip="pending")
    _, placed = await run(db)
    assert placed == 0
    _, placed = await run(db, now=NOW + timedelta(minutes=2))
    assert placed == 1
    async with db.async_session_maker() as s:
        member = await s.get(AssetGroupMember, (waiting, "auto"))
    assert member.vector is None


async def test_skipped_clip_and_trashed_assets_never_block(db):
    v = Vectors()
    async with db.async_session_maker() as s:
        audio, _ = await add_asset(s, at=NOW - timedelta(minutes=3), clip="skipped", tool=None)
        trashed, _ = await add_asset(s, at=NOW - timedelta(minutes=2), clip="pending", meta="pending", state="trashed")
        ready, _ = await add_asset(s, at=NOW - timedelta(minutes=1), prompt="p", vec=v.base())
    _, placed = await run(db)
    assert placed == 3 and set(await homes(db)) == {audio, trashed, ready}


async def test_arrival_order_is_asset_created_at_not_media_date(db):
    """Old media promoted today arrives today: it joins a group active now."""
    v = Vectors()
    async with db.async_session_maker() as s:
        recent, recent_media = await add_asset(s, at=NOW - timedelta(days=1), prompt="p", vec=v.base())
        promoted, _ = await add_asset(
            s, at=NOW - timedelta(hours=1), created=datetime(2020, 1, 1), tool="x:edit",
            vec=v.base(), sources=[recent_media],
        )
        earlier, _ = await add_asset(s, at=NOW - timedelta(days=2), prompt="z", vec=v.base())
    await run(db)
    async with db.async_session_maker() as s:
        order = list(await s.scalars(
            select(AssetGroupMember.asset_id)
            .where(AssetGroupMember.kind == "auto")
            .order_by(AssetGroupMember.arrived_at)
        ))
    assert order == [earlier, recent, promoted]
    h = await homes(db)
    assert h[promoted] == (h[recent][0], "lineage")
    async with db.async_session_maker() as s:
        group = await s.get(AssetGroup, h[recent][0])
    assert group.first_at == datetime(2020, 1, 1)  # display span uses the media date


async def test_chat_and_import_folder_rules_and_titles(db):
    async with db.async_session_maker() as s:
        chat = Chat(name="Moodboard chat")
        s.add(chat)
        await s.flush()
        c1, c1_media = await add_asset(s, at=T0, prompt="first", tool=None)
        c2, c2_media = await add_asset(s, at=T0 + timedelta(days=2), prompt="second", tool=None)
        for media_id in (c1_media, c2_media):
            s.add(ChatItem(chat_id=chat.id, item_type="generated_media", media_id=media_id))
        i1, _ = await add_asset(s, at=T0 + timedelta(days=3), tool=None, folder="/photos/Rome", created=datetime(2024, 3, 2))
        i2, _ = await add_asset(s, at=T0 + timedelta(days=3, minutes=1), tool=None, folder="/photos/Rome", created=datetime(2024, 3, 20))
        i3, _ = await add_asset(s, at=T0 + timedelta(days=3, minutes=2), tool=None, folder="/photos/Rome", created=datetime(2024, 4, 1))
        await s.commit()
    await run(db)
    h = await homes(db)
    assert h[c2] == (h[c1][0], "chat")
    assert h[i2] == (h[i1][0], "import folder")
    assert h[i3][0] != h[i1][0]
    async with db.async_session_maker() as s:
        assert (await s.get(AssetGroup, h[c1][0])).title == "Moodboard chat"
        assert (await s.get(AssetGroup, h[i1][0])).title == "Rome · Mar 2024"


async def test_managed_uploads_group_by_batch_not_by_per_file_folder(db):
    async with db.async_session_maker() as s:
        # Managed storage gives every file its own folder; uploads batch by arrival.
        u1, _ = await add_asset(s, at=T0, tool=None, folder="@data/p/objects/media/1")
        u2, _ = await add_asset(s, at=T0 + timedelta(minutes=4), tool=None, folder="@data/p/objects/media/2")
        u3, _ = await add_asset(s, at=T0 + timedelta(minutes=40), tool=None, folder="@data/p/objects/media/3")
        await s.commit()
    await run(db)
    h = await homes(db)
    assert h[u2] == (h[u1][0], "upload batch")
    assert h[u3][0] != h[u1][0]
    async with db.async_session_maker() as s:
        assert (await s.get(AssetGroup, h[u1][0])).title == "Uploads"


async def _dataset(db, v):
    """Assets whose later placements depend on the earlier ones' frozen inputs."""
    a, b, c = v.base(), v.base(), v.base()
    ids = {}
    async with db.async_session_maker() as s:
        ids["x"], _ = await add_asset(s, at=NOW - timedelta(hours=10), prompt="p1", vec=v.near(a, 0.99))
        ids["y"], _ = await add_asset(s, at=NOW - timedelta(hours=9), prompt="p2", vec=v.near(a, 0.98), tool="x:other")
        # Times out with no vector; a late CLIP result must not change its group's state.
        ids["z"], _ = await add_asset(s, at=NOW - timedelta(hours=8), prompt="p3", clip="pending", tool="x:third")
        for i in range(3):
            ids[f"w{i}"], _ = await add_asset(s, at=NOW - timedelta(hours=7, minutes=-i), prompt="p4", vec=v.near(b, 0.99), tool="x:w")
        # After the restart point:
        ids["same_as_x_new_revision"], _ = await add_asset(s, at=NOW - timedelta(hours=5), prompt="p1 revised", vec=v.base())
        ids["looks_like_z_late"], _ = await add_asset(s, at=NOW - timedelta(hours=4), prompt="p5", vec=v.near(c, 0.99), tool="x:fourth")
        ids["drift_after_w"], _ = await add_asset(s, at=NOW - timedelta(hours=7, minutes=-10), prompt="p6", vec=v.near(b, 0.97), tool="x:w")
        ids["same_as_y"], _ = await add_asset(s, at=NOW - timedelta(hours=3), prompt="p2", vec=v.base(), tool="x:other")
    return ids, c


def _partition(h):
    groups = {}
    for asset_id, (gid, _) in h.items():
        groups.setdefault(gid, set()).add(asset_id)
    return sorted(sorted(members) for members in groups.values()), {a: r for a, (_, r) in h.items()}


async def test_warm_up_rebuild_matches_one_continuous_run(db):
    v = Vectors(7)
    ids, c = await _dataset(db, v)
    await run(db)
    continuous = {kind: _partition(await homes(db, kind)) for kind in ("auto", "theme")}
    h = await homes(db)
    # The later placements hinge on frozen inputs the mutations below change.
    assert h[ids["same_as_y"]] == (h[ids["y"]][0], "same prompt")
    assert h[ids["same_as_x_new_revision"]][0] != h[ids["x"]][0]
    assert h[ids["looks_like_z_late"]][0] != h[ids["z"]][0]
    assert h[ids["drift_after_w"]] == (h[ids["w0"]][0], "drift")

    async with db.async_session_maker() as s:
        for table in (AssetGroupRef, AssetGroupMember, AssetGroup):
            await s.execute(delete(table))
        await s.commit()
    first, _ = await run(db, limit=6)
    assert len(await homes(db)) == 6

    async with db.async_session_maker() as s:
        # A new revision of x with another prompt and look.
        new_media = await add_media(s, at=NOW, prompt="p1 revised", vec=v.base())
        r2 = AssetRevision(asset_id=ids["x"], primary_media_id=new_media.id, revision_number=2)
        s.add(r2)
        await s.flush()
        (await s.get(Asset, ids["x"])).current_revision_id = r2.id
        # An in-place autosave: y's head now points at different Media.
        autosave = await add_media(s, at=NOW, prompt="p2 autosaved", vec=v.base(), tool="x:other")
        head = await s.get(AssetRevision, (await s.get(Asset, ids["y"])).current_revision_id)
        head.primary_media_id = autosave.id
        # A late CLIP result for z, which looks like the later frame.
        z_media = await s.get(MediaItem, (await s.get(AssetRevision, (await s.get(Asset, ids["z"])).current_revision_id)).primary_media_id)
        z_media.set_embedding(v.near(c, 0.99))
        z_media.clip_status = "completed"
        await s.commit()

    restarted = GroupingEngine()
    await run(db, restarted)
    resumed = {kind: _partition(await homes(db, kind)) for kind in ("auto", "theme")}
    assert resumed == continuous
    assert restarted.thresholds["looks_alike"] == first.thresholds["looks_alike"] == DEFAULT_LOOKS_ALIKE


def test_calibration_falls_back_below_two_hundred_samples():
    v = Vectors()
    items = [Item(i, T0 + timedelta(minutes=i), typed_prompt="p", tool_id=TOOL, vector=v.base()) for i in range(20)]
    t = calibrate(items)
    assert (t["looks_alike"], t["drift"]) == (DEFAULT_LOOKS_ALIKE, DEFAULT_DRIFT)


def test_calibration_uses_the_library_above_two_hundred_samples():
    v = Vectors()
    items, i = [], 0
    for p in range(60):
        base = v.base()
        for k in range(6):
            items.append(Item(i, T0 + timedelta(hours=p, minutes=k), typed_prompt=f"p{p}", tool_id=TOOL, vector=v.near(base, 0.93)))
            i += 1
    t = calibrate(items)
    assert t["n_same"] >= 200 and t["n_steps"] >= 200
    assert 0.8 < t["looks_alike"] < 0.9
    assert 0.8 < t["drift"] < 0.9


def test_prompt_title_is_display_only_first_clause():
    assert prompt_title("a red fox, in snow, cinematic") == "a red fox"
    long = "x" * 100
    assert prompt_title(long) == "x" * 64 + "…"


async def test_monitor_broadcasts_when_the_grouping_version_moves(db):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, MagicMock
    from utils.background_tasks import _broadcast_grouping_changes

    settings = SimpleNamespace(profiles=[SimpleNamespace(id="alpha")])
    registry = MagicMock()
    registry.has_profile.return_value = True
    registry.get_database.return_value = db
    ws = SimpleNamespace(broadcast=AsyncMock())
    seen: dict = {}

    await _broadcast_grouping_changes(ws, settings, registry, seen)  # baseline
    await _broadcast_grouping_changes(ws, settings, registry, seen)
    assert ws.broadcast.await_count == 0
    async with db.async_session_maker() as s:
        await add_asset(s, at=NOW - timedelta(hours=1), prompt="p", vec=Vectors().base())
    await run(db)
    await _broadcast_grouping_changes(ws, settings, registry, seen)
    (call,) = ws.broadcast.await_args_list
    event, data = call.args
    assert event == "asset_groups_updated"
    assert data["profile_id"] == "alpha" and data["grouping_version"] == seen["alpha"]
