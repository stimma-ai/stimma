"""Grouped browse: /api/assets/browse, /browse/groups and /browse/ids with group_by."""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import delete

from asset_grouping import GroupingEngine
from database import Asset, AssetGroup, AssetGroupMember, AssetGroupRef, Project, ProjectAsset
from tests.test_asset_grouping import Vectors, add_asset

T0 = datetime(2026, 10, 1, 10, 0)
NOW = datetime(2026, 11, 1, 12, 0)
FOLDER = "/grouping-api"


@pytest.fixture
async def library(db_session):
    """Two tied Auto groups, a revisit group with a ref, a day-boundary frame,
    a project, and two Assets the grouping pass hasn't reached yet."""
    async with db_session() as s:
        for table in (AssetGroupRef, AssetGroupMember, AssetGroup, ProjectAsset):
            await s.execute(delete(table))
        await s.execute(delete(Asset))
        await s.commit()
    v = Vectors(3)
    ids = {}
    async with db_session() as s:
        kw = {"folder": FOLDER}
        ids["a1"], a1_media = await add_asset(s, at=T0, created=T0, prompt="castle", vec=v.base(), **kw)
        ids["a2"], _ = await add_asset(s, at=T0 + timedelta(minutes=1), created=T0 + timedelta(hours=1), prompt="castle", vec=v.base(), **kw)
        ids["a3"], _ = await add_asset(s, at=T0 + timedelta(minutes=2), created=T0 + timedelta(minutes=30), prompt="castle", vec=v.base(), fmt="mp4", **kw)
        # Ties the castle group's newest item exactly.
        ids["b1"], _ = await add_asset(s, at=T0 + timedelta(days=1), created=T0 + timedelta(hours=1), prompt="forest", tool="x:other", vec=v.base(), **kw)
        # 02:00 UTC on 10 Oct is 9 Oct in New York.
        ids["d1"], _ = await add_asset(s, at=T0 + timedelta(days=9), created=datetime(2026, 10, 10, 2, 0), prompt="night", tool="x:night", vec=v.base(), **kw)
        # Twenty idle days later, made from a1: a revisit showing a1 as a ref.
        ids["c1"], _ = await add_asset(s, at=T0 + timedelta(days=20), created=T0 + timedelta(days=20), tool="x:edit", vec=v.base(), sources=[a1_media], **kw)
        project = Project(name="Harbor")
        s.add(project)
        await s.flush()
        s.add(ProjectAsset(project_id=project.id, asset_id=ids["a1"]))
        s.add(ProjectAsset(project_id=project.id, asset_id=ids["a2"]))
        await s.commit()
        ids["project"] = project.id
    engine = GroupingEngine()
    async with db_session() as s:
        await engine.process(s, now=NOW)
    async with db_session() as s:
        ids["p1"], _ = await add_asset(s, at=NOW, created=datetime(2026, 10, 25), prompt="later", vec=v.base(), **kw)
        ids["p2"], _ = await add_asset(s, at=NOW, created=datetime(2026, 10, 26), prompt="later", vec=v.base(), **kw)
    ids["homes"] = {}
    async with db_session() as s:
        for member in (await s.execute(AssetGroupMember.__table__.select().where(AssetGroupMember.kind == "auto"))).all():
            ids["homes"][member.asset_id] = f"g{member.group_id}"
    return ids


async def _all_pages(client, params, page_size=2):
    items, page = [], 1
    while True:
        r = await client.get("/api/assets/browse", params={**params, "page": page, "page_size": page_size})
        assert r.status_code == 200, r.text
        data = r.json()
        items += [item["asset_id"] for item in data["items"]]
        if page * page_size >= data["total"]:
            return items, data
        page += 1


async def test_auto_groups_order_offsets_and_pending(client, library):
    homes = library["homes"]
    r = await client.get("/api/assets/browse/groups", params={"group_by": "auto"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["grouped"] is True
    groups = data["groups"]
    keys = [g["key"] for g in groups]
    castle, forest, revisit = homes[library["a1"]], homes[library["b1"]], homes[library["c1"]]
    assert castle == homes[library["a2"]] == homes[library["a3"]] != forest
    # Newest item first: the revisit (20 Oct), New (26 Oct) above it; the
    # castle and forest groups tie on 11:00 and order by key, never interleaving.
    assert keys == ["__pending", revisit, homes[library["d1"]], *sorted([castle, forest])]
    pending = groups[0]
    assert pending["title"] == "New" and pending["count"] == 2 and data["pending"] == 2
    by_key = {g["key"]: g for g in groups}
    assert by_key[castle]["title"] == "castle"
    assert by_key[castle]["count"] == by_key[castle]["total"] == 3
    assert by_key[castle]["project_id"] == library["project"]
    assert [ref["asset_id"] for ref in by_key[revisit]["refs"]] == [library["a1"]]
    assert by_key[revisit]["refs"][0]["media_id"]  # a full browser projection
    assert by_key[revisit]["refs"][0]["home_key"] == castle  # where the source lives
    offsets = [g["offset"] for g in groups]
    assert offsets == [sum(g["count"] for g in groups[:i]) for i in range(len(groups))]
    assert data["total"] == sum(g["count"] for g in groups) == 8
    assert data["grouping_version"]

    # Paging stays by flat index and matches the sections exactly.
    items, page = await _all_pages(client, {"group_by": "auto"})
    assert page["grouped"] is True and page["total"] == 8
    ids = (await client.get("/api/assets/browse/ids", params={"group_by": "auto"})).json()["ids"]
    assert items == ids
    for group in groups:
        section = items[group["offset"]:group["offset"] + group["count"]]
        if group["key"] == "__pending":
            assert set(section) == {library["p1"], library["p2"]}
        else:
            assert {homes[a] for a in section} == {group["key"]}
    # Inside a group: newest first.
    castle_section = items[by_key[castle]["offset"]:by_key[castle]["offset"] + 3]
    assert castle_section == [library["a2"], library["a3"], library["a1"]]


async def test_counts_and_totals_with_filters(client, library):
    castle = library["homes"][library["a1"]]
    data = (await client.get("/api/assets/browse/groups", params={"group_by": "auto", "media_types": "images"})).json()
    by_key = {g["key"]: g for g in data["groups"]}
    assert by_key[castle]["count"] == 2 and by_key[castle]["total"] == 3
    assert data["total"] == 7
    items, page = await _all_pages(client, {"group_by": "auto", "media_types": "images"})
    assert len(items) == page["total"] == 7
    assert library["a3"] not in items


async def test_browse_ids_for_one_group_with_refs(client, library):
    homes = library["homes"]
    castle, revisit = homes[library["a1"]], homes[library["c1"]]
    r = await client.get("/api/assets/browse/ids", params={"group_by": "auto", "group_key": castle})
    assert r.json() == {"ids": [library["a2"], library["a3"], library["a1"]], "ref_ids": []}
    r = await client.get("/api/assets/browse/ids", params={"group_by": "auto", "group_key": revisit})
    assert r.json() == {"ids": [library["c1"]], "ref_ids": [library["a1"]]}
    r = await client.get("/api/assets/browse/ids", params={"group_by": "auto", "group_key": "__pending"})
    assert set(r.json()["ids"]) == {library["p1"], library["p2"]}
    assert (await client.get("/api/assets/browse/ids", params={"group_key": castle})).status_code == 422


async def test_day_month_and_project_keys(client, library):
    day = (await client.get("/api/assets/browse/groups", params={"group_by": "day", "tz_offset": -300})).json()
    keys = {g["key"]: g for g in day["groups"]}
    assert "2026-10-09" in keys and "2026-10-10" not in keys
    assert keys["2026-10-09"]["title"] is None
    utc = (await client.get("/api/assets/browse/groups", params={"group_by": "day"})).json()
    assert "2026-10-10" in {g["key"] for g in utc["groups"]}
    month = (await client.get("/api/assets/browse/groups", params={"group_by": "month"})).json()
    assert [g["key"] for g in month["groups"]] == ["2026-10"]
    project = (await client.get("/api/assets/browse/groups", params={"group_by": "project"})).json()
    by_key = {g["key"]: g for g in project["groups"]}
    pkey = f"p{library['project']}"
    assert by_key[pkey]["title"] == "Harbor" and by_key[pkey]["count"] == 2
    assert by_key["p0"]["title"] == "No project" and by_key["p0"]["count"] == 6
    items, _ = await _all_pages(client, {"group_by": "project"})
    for group in project["groups"]:
        ids = (await client.get("/api/assets/browse/ids", params={"group_by": "project", "group_key": group["key"]})).json()["ids"]
        assert items[group["offset"]:group["offset"] + group["count"]] == ids


async def test_ascending_sort_orders_groups_by_their_oldest_item(client, library):
    data = (await client.get("/api/assets/browse/groups", params={"group_by": "auto", "sort_by": "created_asc"})).json()
    castle = library["homes"][library["a1"]]
    assert data["groups"][0]["key"] == castle
    items, _ = await _all_pages(client, {"group_by": "auto", "sort_by": "created_asc"})
    assert items[:3] == [library["a1"], library["a3"], library["a2"]]


async def test_random_and_similarity_answer_ungrouped(client, library):
    r = (await client.get("/api/assets/browse/groups", params={"group_by": "auto", "sort_by": "random"})).json()
    assert r["grouped"] is False and r["groups"] == [] and r["total"] == 8
    page = (await client.get("/api/assets/browse", params={"group_by": "auto", "sort_by": "random"})).json()
    assert page["grouped"] is False
    r = (await client.get("/api/assets/browse/groups", params={"group_by": "auto", "similar_to": "1"})).json()
    assert r["grouped"] is False and r["total"] is None
    # Without group_by the browse response is unchanged.
    plain = (await client.get("/api/assets/browse")).json()
    assert "grouped" not in plain
