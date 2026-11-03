"""Column-only CLIP search preserves scalar scoring and browse ordering."""
from datetime import datetime, timedelta
import random

import numpy as np
import pytest
from sqlalchemy import event

from asset_service import create_asset_from_media
from clip_service import CLIP_EMBEDDING_DIM
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_vectorized_similarity_preserves_scores_filters_and_order(client, db_session, tmp_path):
    query = np.zeros(CLIP_EMBEDDING_DIM, dtype=np.float32)
    query[0] = 1
    vectors = []
    for x, y in [(1, 0), (.8, .6), (.6, .8), (6, 8), (.4, .9), (-1, 0), (0, 1), (0, 0)]:
        vector = np.zeros(CLIP_EMBEDDING_DIM, dtype=np.float32)
        vector[:2] = [x, y]
        vectors.append(vector)
    statements = []
    engine = db_session.kw["bind"].sync_engine

    def record_sql(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", record_sql)
    try:
        async with db_session() as session:
            items = []
            for i, vector in enumerate(vectors):
                path = tmp_path / f"candidate-{i}.png"
                path.write_bytes(b"fixture")
                item = await create_media_item(
                    session, file_path=path, materialize_asset=True,
                    vlm_caption="vector fixture", clip_status="completed",
                    created_date=datetime(2025, 1, 1) + timedelta(days=i // 2),
                    generation_metadata='{"prompt":"fixture"}' if i % 2 else None,
                )
                item.set_embedding(vector)
                item.indexed_date = datetime(2025, 2, 1) + timedelta(days=(len(vectors) - i) // 2)
                items.append(item)
            reference = items[0]
            # Each should score 1.0 but remain excluded by the existing filters.
            for reason in ("bare", "trashed", "unavailable", "unfinished"):
                item = await create_media_item(session, vlm_caption="vector fixture")
                item.set_embedding(query)
                if reason != "bare":
                    asset = await create_asset_from_media(session, media_id=item.id)
                    if reason == "trashed":
                        asset.state = "trashed"
                    elif reason == "unavailable":
                        item.file_unavailable = True
                    else:
                        item.metadata_status = "pending"
            stale = await create_media_item(session, materialize_asset=True, vlm_caption="vector fixture", clip_status="completed")
            stale.set_embedding(np.ones(3, dtype=np.float32))
            await session.commit()
            reference_id = reference.id
            with np.errstate(invalid="ignore"):
                scores = {item.id: float(np.dot(query / np.linalg.norm(query), vector / np.linalg.norm(vector)))
                          for item, vector in zip(items, vectors)}
            threshold = scores[items[2].id]  # Exercise the exact float32 boundary.
            for generated in (None, True, False):
                for sort in ("similarity", "created_desc", "created_asc", "indexed_desc", "indexed_asc", "random"):
                    expected = [item for item in items if (item.id == reference_id or scores[item.id] >= threshold)
                                and (generated is None or bool(item.generation_metadata) == generated)]
                    if sort == "similarity":
                        expected.sort(key=lambda item: scores[item.id], reverse=True)
                    elif sort.startswith("created"):
                        expected.sort(key=lambda item: item.created_date, reverse=sort.endswith("desc"))
                    elif sort.startswith("indexed"):
                        expected.sort(key=lambda item: item.indexed_date, reverse=sort.endswith("desc"))
                    else:
                        random.Random(17).shuffle(expected)
                    params = dict(similar_to=str(reference_id), similarity_threshold=threshold,
                                  caption_query="vector fixture", sort_by=sort, random_seed=17, page_size=2, page=2)
                    if generated is not None:
                        params["is_generated"] = str(generated).lower()
                    statements.clear()
                    response = await client.get("/api/media", params=params)
                    assert response.status_code == 200, response.text
                    data = response.json()
                    assert data["total"] == len(expected)
                    assert [row["media_id"] for row in data["items"]] == [item.id for item in expected[2:4]]
                    assert [row["similarity_score"] for row in data["items"]] == [scores[item.id] for item in expected[2:4]]
                    candidate_sql = [sql for sql in statements if "media_items.clip_embedding IS NOT NULL" in sql]
                    assert len(candidate_sql) == 1
                    assert candidate_sql[0].split("FROM", 1)[0].strip() == "SELECT media_items.id, media_items.clip_embedding"
                    if generated is None:
                        params.pop("page_size")
                        params.pop("page")
                        ids = await client.get("/api/media/ids", params=params)
                        assert ids.status_code == 200
                        assert ids.json()["ids"] == [item.id for item in expected]

            mixed_query = (vectors[0] + vectors[6]) / 2
            mixed_query /= np.linalg.norm(mixed_query)
            with np.errstate(invalid="ignore"):
                mixed_scores = {item.id: float(np.dot(mixed_query / np.linalg.norm(mixed_query), vector / np.linalg.norm(vector)))
                                for item, vector in zip(items, vectors)}
            refs = {items[0].id, items[6].id}
            expected = sorted((item.id for item in items if item.id in refs or mixed_scores[item.id] >= .95),
                              key=mixed_scores.get, reverse=True)
            response = await client.get("/api/media", params={
                "similar_to": f"{items[0].id},{items[6].id}", "similarity_threshold": .95,
                "caption_query": "vector fixture", "sort_by": "similarity",
            })
            assert [row["media_id"] for row in response.json()["items"]] == expected
            assert [row["similarity_score"] for row in response.json()["items"]] == [mixed_scores[media_id] for media_id in expected]

            # Text encoding in the suite produces the same unit-axis query.
            response = await client.get("/api/media", params={
                "similar_to_text": "fixture", "similarity_threshold": threshold,
                "caption_query": "vector fixture", "sort_by": "similarity",
            })
            expected = sorted((item.id for item in items if scores[item.id] >= threshold), key=scores.get, reverse=True)
            assert [row["media_id"] for row in response.json()["items"]] == expected

            from config import get_settings
            response = await client.post("/api/search/similar", json={"media_id": reference_id})
            expected = sorted((item.id for item in items if item.id != reference_id and scores[item.id] >= get_settings().clip_similarity_threshold), key=scores.get, reverse=True)
            assert [row["media_id"] for row in response.json()["items"]] == expected
            await session.refresh(stale)
            assert stale.clip_embedding is None
            assert stale.clip_status == "pending"
    finally:
        event.remove(engine, "before_cursor_execute", record_sql)


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["text", "media", "ids", "post"])
async def test_similarity_winner_lookups_are_chunked(client, db_session, monkeypatch, mode):
    import routes.media as media_routes

    monkeypatch.setattr(media_routes, "SIMILARITY_LOOKUP_CHUNK_SIZE", 2, raising=False)
    vector = np.zeros(CLIP_EMBEDDING_DIM, dtype=np.float32)
    vector[-1 if mode == "post" else 0] = 1
    async with db_session() as session:
        items = []
        for _ in range(5):
            item = await create_media_item(session, materialize_asset=True, vlm_caption=f"chunked winners {mode}")
            item.set_embedding(vector)
            items.append(item)
        await session.commit()
        ids = [item.id for item in items]

    chunks = []

    def limit_winner_query(connection, cursor, statement, parameters, context, executemany):
        metadata_lookup = statement.startswith("SELECT media_items.id, media_items.created_date, media_items.indexed_date")
        payload_lookup = statement.startswith("SELECT media_items.id, media_items.file_path") and "WHERE media_items.id IN" in statement
        if (mode == "post" and payload_lookup) or (mode != "post" and metadata_lookup):
            chunks.append(len(parameters))
            assert len(parameters) <= 2, "winner lookup exceeds SQL variable limit"

    engine = db_session.kw["bind"].sync_engine
    event.listen(engine, "before_cursor_execute", limit_winner_query)
    try:
        params = dict(caption_query=f"chunked winners {mode}", similarity_threshold=0.5, sort_by="similarity")
        params["similar_to_text" if mode == "text" else "similar_to"] = "fixture" if mode == "text" else str(ids[0])
        if mode != "ids":
            params.update(page=1, page_size=1)
        if mode == "post":
            response = await client.post("/api/search/similar", json={"media_id": ids[0]})
        else:
            response = await client.get("/api/media/ids" if mode == "ids" else "/api/media", params=params)
        assert response.status_code == 200, response.text
        data = response.json()
        if mode == "post":
            assert [item["media_id"] for item in data["items"]] == ids[1:]
        elif mode == "ids":
            assert data["ids"] == ids
        else:
            assert data["total"] == len(ids)
            assert [item["media_id"] for item in data["items"]] == ids[:1]
        assert chunks == ([2, 2] if mode == "post" else [2, 2, 1])
    finally:
        event.remove(engine, "before_cursor_execute", limit_winner_query)
