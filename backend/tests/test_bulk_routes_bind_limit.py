"""Select-all sized requests stay under SQLite's bound-parameter cap.

40,000 ids exceed the 32,766-variable limit of current SQLite builds, so any
unchunked ``IN (...)`` on these routes or their helpers fails with "too many
SQL variables".
"""

from unittest.mock import AsyncMock

from tests.helpers.media import create_test_media

MANY = 40_000


async def test_bulk_routes_accept_select_all_sized_requests(client, db_session):
    async with db_session() as session:
        (media,) = await create_test_media(session, count=1)
    ids = [media.id, *range(10_000_000, 10_000_000 + MANY)]

    marker_id = (await client.get("/api/markers")).json()[0]["id"]
    project = (await client.post("/api/projects", json={"name": "Big"})).json()

    responses = [
        await client.post("/api/assets/batch/markers", json={"asset_ids": ids, "marker_id": marker_id, "add": True}),
        await client.post("/api/assets/batch/tags", json={"asset_ids": ids, "tag_texts": ["big"], "remove_tag_ids": []}),
        await client.post(f"/api/assets/batch/projects/{project['id']}", json={"asset_ids": ids}),
        await client.post("/api/trash/batch/delete", json={"media_ids": ids}),
        await client.post("/api/media/check-existence", json=ids),
        await client.post("/api/media/download", json={"media_ids": ids}),
    ]
    for response in responses:
        assert response.status_code < 500, (response.request.url, response.text[:300])


async def test_bulk_helpers_chunk_request_sized_lists(db_session):
    from asset_association_service import (
        broadcast_asset_organization_updated,
        broadcast_assets_retained,
    )
    from media_actions import MARKED, record_media_actions
    from project_service import current_media_ids_for_assets

    ids = list(range(10_000_000, 10_000_000 + MANY))
    ws = AsyncMock()
    async with db_session() as session:
        await record_media_actions(session, MARKED, [(None, a) for a in ids])
        await record_media_actions(session, MARKED, [(m, None) for m in ids])
        await session.rollback()
        assert await current_media_ids_for_assets(session, ids) == []
        await broadcast_assets_retained(session, ids, ws)
        await broadcast_asset_organization_updated(session, ids, ws)
