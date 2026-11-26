"""'Made with' an element: the library filter and the info panel's data."""

from __future__ import annotations

import pytest

from tests.test_elements import _library_image, _make_mira, _png


async def _made_with(session, tmp_path, name, element_ids):
    from elements.lineage import record_media_elements

    asset_id, media_id = await _library_image(session, _png(tmp_path / "out" / f"{name}.png"))
    await record_media_elements(session, media_id, [{"asset_id": e} for e in element_ids])
    return asset_id, media_id


def _browse_ids(response):
    assert response.status_code == 200, response.text
    return {item["asset_id"] for item in response.json()["items"]}


@pytest.mark.asyncio
async def test_library_filters_by_element(db_session, client, tmp_path):
    async with db_session() as session:
        mira, refs = await _make_mira(session, tmp_path, tmp_path / "ws")
        both_out = await _made_with(session, tmp_path, "both", [mira])
        only_out = await _made_with(session, tmp_path, "only", [mira])
        plain = await _library_image(session, _png(tmp_path / "out" / "plain.png", (1, 2, 3)))
        await session.commit()

    made = _browse_ids(await client.get("/api/assets/browse", params={"element_ids": str(mira)}))
    assert made == {both_out[0], only_out[0]}
    assert plain[0] not in made and not made & set(refs)

    ids = (await client.get("/api/assets/browse/ids", params={"element_ids": str(mira)})).json()["ids"]
    assert set(ids) == made

    counts = (await client.get("/api/assets/filter-counts", params={"element_ids": str(mira)})).json()
    assert counts["media_type"]["images"] == 2

    assert _browse_ids(await client.get("/api/assets/browse", params={"element_ids": "999999"})) == set()
    assert _browse_ids(await client.get("/api/assets/browse", params={"element_ids": "junk"})) == set()


@pytest.mark.asyncio
async def test_info_panel_lists_elements_and_outputs(db_session, client, tmp_path):
    async with db_session() as session:
        mira, _ = await _make_mira(session, tmp_path, tmp_path / "ws")
        first = await _made_with(session, tmp_path, "first", [mira])
        second = await _made_with(session, tmp_path, "second", [mira])
        await session.commit()

    used = (await client.get(f"/api/elements/made-with/{second[1]}")).json()["elements"]
    assert len(used) == 1
    row = used[0]
    assert row["asset_id"] == mira and row["name"] == "Mira" and row["kind"] == "character"
    assert row["revision_number"] == 1 and row["is_current_revision"] is True
    detail = (await client.get(f"/api/elements/{mira}")).json()
    assert row["media_id"] == detail["media_id"] and row["file_hash"]

    plain = (await client.get(f"/api/elements/made-with/{detail['media_id']}")).json()
    assert plain == {"elements": []}

    outputs = (await client.get(f"/api/elements/{mira}/outputs", params={"limit": 1})).json()
    assert outputs["total"] == 2
    assert [i["asset_id"] for i in outputs["items"]] == [second[0]]  # newest first
    assert (await client.get("/api/elements/999999/outputs")).status_code == 404


@pytest.mark.asyncio
async def test_trashed_outputs_and_elements_drop_out(db_session, client, tmp_path):
    from database import Asset

    async with db_session() as session:
        mira, _ = await _make_mira(session, tmp_path, tmp_path / "ws")
        kept = await _made_with(session, tmp_path, "kept", [mira])
        gone = await _made_with(session, tmp_path, "gone", [mira])
        (await session.get(Asset, gone[0])).state = "trashed"
        await session.commit()

    outputs = (await client.get(f"/api/elements/{mira}/outputs")).json()
    assert outputs["total"] == 1 and [i["asset_id"] for i in outputs["items"]] == [kept[0]]

    async with db_session() as session:
        (await session.get(Asset, mira)).state = "trashed"
        await session.commit()
    assert (await client.get(f"/api/elements/made-with/{kept[1]}")).json() == {"elements": []}
