"""Face and CLIP similarity methods on the run_code stimma SDK."""

import asyncio
from datetime import datetime

import numpy as np
import pytest
from PIL import Image
from sqlalchemy import func, select

from agent.v2 import embeddings
from agent.v2.code_runtime import StimmaSDK
from clip_service import CLIP_EMBEDDING_DIM, CLIP_MODEL_VERSION
from database import Asset, AssetRevision, Face, MediaItem
from tests.helpers.media import create_media_item

FACE_DIM = 512


def _unit(dim: int, *hot: tuple[int, float]) -> np.ndarray:
    vector = np.zeros(dim, dtype=np.float32)
    for index, value in hot:
        vector[index] = value
    return vector / np.linalg.norm(vector)


def _add_face(session, media_id, embedding, *, width=0.2, confidence=0.9):
    face = Face(
        media_id=media_id, bbox_x=0.1, bbox_y=0.1, bbox_width=width,
        bbox_height=width, confidence=confidence,
    )
    if embedding is not None:
        face.set_embedding(embedding)
    session.add(face)
    return face


def _sdk(session, workspace):
    return StimmaSDK(
        session=session, chat_id=None, workspace_dir=workspace,
        project_workspace_dir=None, interrupt_checker=lambda: False,
    )


class _Forbidden:
    """A model service that fails if anything tries to embed live."""

    def __getattr__(self, name):
        raise AssertionError(f"model call {name} should have read the cache")


class _FakeFaces:
    def __init__(self, faces_by_name):
        self.faces_by_name = faces_by_name
        self.calls = []

    def detect_faces(self, image):
        self.calls.append(image)
        return self.faces_by_name.get(image.name, [])


def _detected(embedding, width):
    return {
        "bbox": {"x": 0.1, "y": 0.1, "width": width, "height": width},
        "confidence": 0.9, "embedding": embedding, "landmarks": None,
    }


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    for name in ("a.png", "b.png", "empty.png"):
        Image.new("RGB", (16, 16), "gray").save(root / name)
    return root


@pytest.fixture(autouse=True)
def fast_poll(monkeypatch):
    monkeypatch.setattr(embeddings, "POLL_INTERVAL", 0.02)


async def _set_asset_state(session, media_id, state):
    asset = (await session.execute(
        select(Asset).join(AssetRevision, AssetRevision.asset_id == Asset.id)
        .where(AssetRevision.primary_media_id == media_id)
    )).scalar_one()
    asset.state = state


async def _row_counts(session):
    media = (await session.execute(select(func.count(MediaItem.id)))).scalar_one()
    faces = (await session.execute(select(func.count(Face.id)))).scalar_one()
    return media, faces


async def test_detect_faces_reads_cache_sorted_with_area(db_session, workspace, monkeypatch):
    monkeypatch.setattr("face_detection_service.get_face_detection_service", lambda *a, **k: _Forbidden())
    async with db_session() as session:
        item = await create_media_item(session, face_detection_status="completed", materialize_asset=True)
        _add_face(session, item.id, _unit(FACE_DIM, (0, 1)), width=0.1, confidence=0.6)
        _add_face(session, item.id, _unit(FACE_DIM, (1, 1)), width=0.4, confidence=0.95)
        await session.commit()

        faces = await _sdk(session, workspace).detect_faces(item.id)

    assert [f["confidence"] for f in faces] == [0.95, 0.6]
    assert faces[0]["area"] == pytest.approx(0.16)
    assert set(faces[0]) == {"id", "bbox", "area", "confidence", "embedding"}
    assert len(faces[0]["embedding"]) == FACE_DIM


async def test_detect_faces_waits_for_pending_and_wakes_indexer(db_session, workspace, monkeypatch):
    woken = asyncio.Event()

    class _Event:
        def set(self):
            woken.set()

    monkeypatch.setattr("core.app.get_process_pending_event", lambda: _Event())
    async with db_session() as session:
        item = await create_media_item(session, face_detection_status="pending", materialize_asset=True)
        media_id = item.id

    async def finish_indexing():
        await woken.wait()
        await asyncio.sleep(0.05)
        async with db_session() as writer:
            _add_face(writer, media_id, _unit(FACE_DIM, (2, 1)))
            row = await writer.get(MediaItem, media_id)
            row.face_detection_status = "completed"
            await writer.commit()

    async with db_session() as session:
        sdk = _sdk(session, workspace)
        with pytest.raises(RuntimeError, match="still pending"):
            await sdk.detect_faces(media_id, wait=False)
        indexer = asyncio.create_task(finish_indexing())
        faces = await sdk.detect_faces(media_id, timeout=5)
        await indexer

    assert len(faces) == 1


async def test_pending_wait_times_out_with_a_way_forward(db_session, workspace):
    async with db_session() as session:
        item = await create_media_item(session, clip_status="pending", materialize_asset=True)
        with pytest.raises(TimeoutError, match="library.get"):
            await embeddings.clip_embedding(_sdk(session, workspace), item.id, timeout=0.1)


async def test_clip_embedding_reads_cache_and_reschedules_stale(db_session, workspace, monkeypatch):
    monkeypatch.setattr("clip_service.get_clip_service", lambda *a, **k: _Forbidden())
    async with db_session() as session:
        cached = await create_media_item(session, clip_status="completed", materialize_asset=True)
        cached.set_embedding(_unit(CLIP_EMBEDDING_DIM, (3, 1)))
        stale = await create_media_item(session, clip_status="completed", materialize_asset=True)
        stale.set_embedding(np.ones(1024, dtype=np.float32))
        await session.commit()
        sdk = _sdk(session, workspace)

        result = await sdk.clip_embedding(cached.id)
        assert result["dim"] == CLIP_EMBEDDING_DIM
        assert result["model"] == CLIP_MODEL_VERSION
        assert result["media_id"] == cached.id
        assert result["embedding"][3] == pytest.approx(1.0)

        with pytest.raises(TimeoutError):
            await embeddings.clip_embedding(sdk, stale.id, timeout=0.1)
        async with db_session() as check:
            row = await check.get(MediaItem, stale.id)
            assert row.clip_status == "pending" and row.clip_embedding is None


async def test_workspace_paths_and_text_embed_live_without_library_writes(db_session, workspace, monkeypatch):
    person = _unit(FACE_DIM, (5, 1))
    faces = _FakeFaces({
        "a.png": [_detected(_unit(FACE_DIM, (9, 1)), 0.05), _detected(person, 0.3)],
        "b.png": [_detected(person * 0.5, 0.2)],
    })
    monkeypatch.setattr("face_detection_service.get_face_detection_service", lambda *a, **k: faces)
    async with db_session() as session:
        before = await _row_counts(session)
        sdk = _sdk(session, workspace)

        same = await sdk.face_similarity("a.png", "b.png")
        assert same["similarity"] == pytest.approx(1.0)
        assert same["a"]["path"] == "a.png" and same["a"]["area"] == pytest.approx(0.09)

        missing = await sdk.face_similarity("a.png", "empty.png")
        assert missing["similarity"] is None
        assert "No face found" in missing["error"]

        image = await sdk.clip_embedding("a.png")
        text = await sdk.clip_embedding("a red bicycle")
        assert image["path"] == "a.png" and text["text"] == "a red bicycle"
        assert len(image["embedding"]) == CLIP_EMBEDDING_DIM

        assert await _row_counts(session) == before

    with pytest.raises(FileNotFoundError):
        async with db_session() as session:
            await _sdk(session, workspace).clip_embedding("missing.png")


async def test_face_similarity_uses_largest_face_unless_face_given(db_session, workspace):
    async with db_session() as session:
        group = await create_media_item(session, face_detection_status="completed", materialize_asset=True)
        small = _add_face(session, group.id, _unit(FACE_DIM, (10, 1)), width=0.05)
        _add_face(session, group.id, _unit(FACE_DIM, (11, 1)), width=0.3)
        solo = await create_media_item(session, face_detection_status="completed", materialize_asset=True)
        _add_face(session, solo.id, _unit(FACE_DIM, (10, 1)))
        await session.commit()
        sdk = _sdk(session, workspace)

        by_media = await sdk.face_similarity(group.id, solo.id)
        assert by_media["similarity"] == pytest.approx(0.0)
        assert by_media["a"]["face_id"] != small.id

        detected = await sdk.detect_faces(group.id)
        entry = next(f for f in detected if f["id"] == small.id)
        by_face = await sdk.face_similarity(entry, {"face_id": small.id})
        assert by_face["similarity"] == pytest.approx(1.0)
        assert (await sdk.face_similarity({"face_id": small.id}, solo.id))["similarity"] == pytest.approx(1.0)


async def _population(session, make_item):
    """One live Asset plus one of each kind of media searches must skip."""
    live = await make_item(materialize_asset=True)
    bare = await make_item(materialize_asset=False)
    trashed = await make_item(materialize_asset=True)
    await _set_asset_state(session, trashed.id, "trashed")
    deleting = await make_item(materialize_asset=True)
    deleting.deletion_pending_at = datetime.utcnow()
    ephemeral = await make_item(materialize_asset=True)
    ephemeral.ephemeral_run_id = "run-1"
    unavailable = await make_item(materialize_asset=True)
    unavailable.file_unavailable = True
    return live, [bare, trashed, deleting, ephemeral, unavailable]


async def test_find_faces_like_searches_library_population(db_session, workspace):
    person = _unit(FACE_DIM, (20, 1))
    async with db_session() as session:
        async def make_item(materialize_asset):
            item = await create_media_item(
                session, face_detection_status="completed", materialize_asset=materialize_asset,
            )
            _add_face(session, item.id, _unit(FACE_DIM, (20, 1), (21, 0.1)))
            return item

        reference = await make_item(True)
        _add_face(session, reference.id, person, width=0.5)
        live, hidden = await _population(session, make_item)
        stranger = await create_media_item(session, face_detection_status="completed", materialize_asset=True)
        _add_face(session, stranger.id, _unit(FACE_DIM, (22, 1)))
        await session.commit()

        result = await _sdk(session, workspace).find_faces_like(reference.id, limit=10)

    ids = [m["media_id"] for m in result["matches"]]
    assert ids == [live.id]
    assert reference.id not in ids and stranger.id not in ids
    assert not set(ids) & {item.id for item in hidden}
    match = result["matches"][0]
    assert set(match) == {"media_id", "face_id", "similarity", "bbox", "area"}
    assert result["reference"]["media_id"] == reference.id


async def test_find_similar_searches_population_and_reschedules_stale(db_session, workspace):
    async with db_session() as session:
        async def make_item(materialize_asset):
            item = await create_media_item(
                session, clip_status="completed", materialize_asset=materialize_asset,
            )
            item.set_embedding(_unit(CLIP_EMBEDDING_DIM, (30, 1), (31, 0.1)))
            return item

        reference = await make_item(True)
        reference.set_embedding(_unit(CLIP_EMBEDDING_DIM, (30, 1)))
        live, hidden = await _population(session, make_item)
        unrelated = await make_item(True)
        unrelated.set_embedding(_unit(CLIP_EMBEDDING_DIM, (32, 1)))
        stale = await create_media_item(session, clip_status="completed", materialize_asset=True)
        stale.set_embedding(np.ones(1024, dtype=np.float32))
        await session.commit()
        sdk = _sdk(session, workspace)

        result = await sdk.find_similar(reference.id, limit=50)
        ids = [m["media_id"] for m in result["matches"]]
        assert live.id in ids
        assert reference.id not in ids and unrelated.id not in ids
        assert not set(ids) & {item.id for item in hidden}
        assert result["min_similarity"] == pytest.approx(0.75)
        scores = [m["similarity"] for m in result["matches"]]
        assert scores == sorted(scores, reverse=True)

        everything = await sdk.find_similar(reference.id, min_similarity=-1)
        assert unrelated.id in [m["media_id"] for m in everything["matches"]]

    async with db_session() as check:
        row = await check.get(MediaItem, stale.id)
        assert row.clip_status == "pending" and row.clip_embedding is None


async def test_pairwise_similarity_matrix(db_session, workspace, monkeypatch):
    faces = _FakeFaces({"a.png": [_detected(_unit(FACE_DIM, (40, 1)), 0.2)]})
    monkeypatch.setattr("face_detection_service.get_face_detection_service", lambda *a, **k: faces)
    async with db_session() as session:
        items = []
        for hot in (41, 41, 42):
            item = await create_media_item(session, clip_status="completed", materialize_asset=True)
            item.set_embedding(_unit(CLIP_EMBEDDING_DIM, (hot, 1)))
            items.append(item)
        await session.commit()
        sdk = _sdk(session, workspace)

        clip = await sdk.pairwise_similarity([item.id for item in items] + ["a.png"])
        matrix = clip["matrix"]
        assert len(matrix) == 4 and all(len(row) == 4 for row in matrix)
        assert [matrix[i][i] for i in range(4)] == [pytest.approx(1.0)] * 4
        assert matrix[0][1] == pytest.approx(1.0) and matrix[0][2] == pytest.approx(0.0)
        assert all(matrix[i][j] == matrix[j][i] for i in range(4) for j in range(4))
        assert clip["targets"][3] == {"path": "a.png"}

        face = await sdk.pairwise_similarity(["a.png", "empty.png"], kind="face")
        assert face["matrix"] == [[pytest.approx(1.0), None], [None, None]]
        assert "error" in face["targets"][1]

        with pytest.raises(ValueError, match="1 to"):
            await sdk.pairwise_similarity(list(range(embeddings.MAX_PAIRWISE_TARGETS + 1)))
        with pytest.raises(ValueError, match="kind"):
            await sdk.pairwise_similarity([items[0].id], kind="pixels")


def test_similarity_help_lists_every_method():
    from agent.v2.sdk_help import get_sdk_method_help, get_sdk_overview

    assert "Similarity" in get_sdk_overview()
    group = get_sdk_method_help("similarity")
    for name in ("detect_faces", "face_similarity", "find_faces_like", "clip_embedding",
                 "clip_similarity", "find_similar", "pairwise_similarity"):
        assert f"stimma.{name}(" in group
        assert hasattr(StimmaSDK, name)
