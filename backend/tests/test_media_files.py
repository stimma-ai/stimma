"""Tests for media file and thumbnail serving."""

from datetime import datetime
import json
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from PIL import Image

from delete_operations import create_delete_operation
from database_registry import get_database_registry
from tests.helpers.media import create_media_item, generate_test_image


def test_set_preview_prefers_normalized_member_paths_after_manifest_move(tmp_path):
    from routes.media_files import _generate_set_preview

    member = tmp_path / "member.png"
    generate_test_image(member)
    moved_manifest = tmp_path / "managed" / "set.stimmaset.json"
    moved_manifest.parent.mkdir()
    moved_manifest.write_text(json.dumps({"items": [{"path": "../old/member.png"}]}))
    normalized = {
        "items": [
            {"resolved": {"file_path": str(member)}}
        ]
    }
    expected = Image.new("RGB", (32, 32))
    with patch(
        "routes.media_files._create_stacked_cards",
        return_value=expected,
    ) as stacked:
        result = _generate_set_preview(
            str(moved_manifest),
            32,
            normalized_content=normalized,
        )

    assert result is expected
    assert stacked.call_args.args[0] == [str(member)]


def test_set_preview_raises_pending_when_member_file_not_on_disk(tmp_path):
    """A live, resolved member whose payload hasn't landed yet must NOT cache a
    placeholder — it signals ContainerMembersPending so the route serves a
    retryable 503 and self-heals once the file appears."""
    from routes.media_files import _generate_set_preview, ContainerMembersPending

    manifest = tmp_path / "set.stimmaset.json"
    manifest.write_text(json.dumps({"items": []}))
    missing = tmp_path / "not-yet-here.png"  # resolved but not on disk yet
    normalized = {"items": [{"resolved": {"file_path": str(missing)}}]}

    with pytest.raises(ContainerMembersPending):
        _generate_set_preview(str(manifest), 32, normalized_content=normalized)


def test_set_preview_placeholder_for_unavailable_member_does_not_retry(tmp_path):
    """An unavailable/old-style member (no resolved path, only a stale manifest
    path) that's missing on disk is a stable, cacheable placeholder — not a
    transient miss, so it must not raise (which would retry forever)."""
    from routes.media_files import _generate_set_preview, _generate_placeholder_thumbnail

    manifest = tmp_path / "set.stimmaset.json"
    # Only a manifest path (no `resolved`), pointing at a missing file.
    manifest.write_text(json.dumps({"items": [{"path": "gone/member.png"}]}))

    sentinel = Image.new("RGB", (8, 8))
    with patch(
        "routes.media_files._generate_placeholder_thumbnail",
        return_value=sentinel,
    ) as placeholder:
        result = _generate_set_preview(str(manifest), 32)

    assert result is sentinel
    assert placeholder.called


class TestThumbnailDeletionRaces:
    async def test_thumbnail_generation_does_not_lazy_load_expired_media(self, client: AsyncClient, db_session, tmp_path):
        file_path = tmp_path / "existing-source.png"
        file_hash = generate_test_image(file_path, color=(0, 0, 255))

        async with db_session() as session:
            await create_media_item(session, file_path=file_path, file_hash=file_hash)

        response = await client.get(f"/api/thumbnail/{file_hash}", params={"size": 128})
        assert response.status_code == 200
        assert response.headers["content-type"] in {"image/png", "image/jpeg"}

    async def test_db_guid_thumbnail_routes_do_not_lazy_load_expired_media(self, client: AsyncClient, db_session, tmp_path):
        file_path = tmp_path / "db-guid-source.png"
        file_hash = generate_test_image(file_path, color=(255, 255, 0))

        async with db_session() as session:
            media = await create_media_item(session, file_path=file_path, file_hash=file_hash)
            media_id = media.id

        db_guid = get_database_registry().get_db_guid("default")

        response = await client.get(f"/api/db/{db_guid}/thumbnail/{file_hash}", params={"size": 128})
        assert response.status_code == 200
        assert response.headers["content-type"] in {"image/png", "image/jpeg"}

        path_response = await client.get(f"/api/db/{db_guid}/media/{media_id}/thumbnail-path", params={"size": 128})
        assert path_response.status_code == 200
        assert path_response.json()["path"]

    async def test_thumbnail_missing_source_returns_404(self, client: AsyncClient, db_session, tmp_path):
        file_path = tmp_path / "missing-source.png"
        file_hash = generate_test_image(file_path, color=(255, 0, 0))

        async with db_session() as session:
            await create_media_item(session, file_path=file_path, file_hash=file_hash)

        file_path.unlink()

        response = await client.get(f"/api/thumbnail/{file_hash}")
        assert response.status_code == 404
        assert "file not found" in response.json()["detail"].lower()

    async def test_thumbnail_skips_media_queued_for_permanent_delete(self, client: AsyncClient, db_session, tmp_path):
        file_path = tmp_path / "queued-delete.png"
        file_hash = generate_test_image(file_path, color=(0, 255, 0))

        async with db_session() as session:
            media = await create_media_item(session, file_path=file_path, file_hash=file_hash)
            media.deleted_at = datetime.utcnow()
            await session.commit()
            await create_delete_operation(
                session,
                profile_id="default",
                kind="single",
                media_items=[media],
            )

        response = await client.get(f"/api/thumbnail/{file_hash}")
        assert response.status_code == 404
        assert "permanently deleted" in response.json()["detail"].lower()


class TestContainerMembersPending:
    """A set/grid whose member files aren't on disk yet must return a retryable
    503 instead of caching the placeholder — otherwise the stale placeholder
    sticks forever (the container-json mtime never changes when members land)."""

    async def _make_source(self, db_session, tmp_path, name):
        file_path = tmp_path / name
        file_hash = generate_test_image(file_path, color=(10, 20, 30))
        async with db_session() as session:
            await create_media_item(session, file_path=file_path, file_hash=file_hash)
        return file_hash

    async def test_legacy_route_returns_retryable_503(self, client: AsyncClient, db_session, tmp_path):
        from routes.media_files import ContainerMembersPending

        file_hash = await self._make_source(db_session, tmp_path, "pending-legacy.png")

        async def _raise(*args, **kwargs):
            raise ContainerMembersPending("members not ready")

        with patch("routes.media_files._generate_thumbnail_in_pool", side_effect=_raise):
            response = await client.get(f"/api/thumbnail/{file_hash}", params={"size": 256})

        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "1"

    async def test_db_guid_route_returns_retryable_503(self, client: AsyncClient, db_session, tmp_path):
        from routes.media_files import ContainerMembersPending

        file_hash = await self._make_source(db_session, tmp_path, "pending-db-guid.png")
        db_guid = get_database_registry().get_db_guid("default")

        async def _raise(*args, **kwargs):
            raise ContainerMembersPending("members not ready")

        with patch("routes.media_files._generate_thumbnail_in_pool", side_effect=_raise):
            response = await client.get(f"/api/db/{db_guid}/thumbnail/{file_hash}", params={"size": 256})

        assert response.status_code == 503
        assert response.headers.get("Retry-After") == "1"
