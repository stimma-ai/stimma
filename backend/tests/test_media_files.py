"""Tests for media file and thumbnail serving."""

from datetime import datetime
import hashlib
import io
import json
import shutil
import subprocess
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from PIL import Image, ImageChops

from delete_operations import create_delete_operation
from database_registry import get_database_registry
from tests.helpers.media import create_media_item, generate_test_image


@pytest.mark.asyncio
async def test_known_thumbnail_cache_hit_avoids_sqlite_write(tmp_path):
    from routes.media_files import _record_thumbnail_cache, _recorded_thumbnail_cache_entries

    cache_path = tmp_path / "cached.jpg"
    cache_key = (42, str(cache_path))
    _recorded_thumbnail_cache_entries.discard(cache_key)

    class ExistingResult:
        def scalar_one_or_none(self):
            return 42

    class ReadOnlySession:
        async def execute(self, _statement):
            return ExistingResult()

        async def commit(self):
            raise AssertionError("an already-indexed cache hit must not take a SQLite write lock")

    await _record_thumbnail_cache(ReadOnlySession(), 42, cache_path)
    assert cache_key in _recorded_thumbnail_cache_entries


@pytest.mark.parametrize("extension", ["png", "mp4"])
def test_set_preview_prefers_normalized_member_paths_after_manifest_move(tmp_path, extension):
    from routes.media_files import _generate_set_preview

    member = tmp_path / f"member.{extension}"
    member.touch()
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


@pytest.mark.parametrize("extension", ["png", "mp4"])
def test_set_preview_raises_pending_when_member_file_not_on_disk(tmp_path, extension):
    """A live, resolved member whose payload hasn't landed yet must NOT cache a
    placeholder — it signals ContainerMembersPending so the route serves a
    retryable 503 and self-heals once the file appears."""
    from routes.media_files import _generate_set_preview, ContainerMembersPending

    manifest = tmp_path / "set.stimmaset.json"
    manifest.write_text(json.dumps({"items": []}))
    missing = tmp_path / f"not-yet-here.{extension}"  # resolved but not on disk yet
    normalized = {"items": [{"resolved": {"file_path": str(missing)}}]}

    with pytest.raises(ContainerMembersPending):
        _generate_set_preview(str(manifest), 32, normalized_content=normalized)


@pytest.mark.parametrize("extension", ["png", "mp4"])
def test_set_preview_placeholder_for_unavailable_member_does_not_retry(tmp_path, extension):
    """An unavailable/old-style member (no resolved path, only a stale manifest
    path) that's missing on disk is a stable, cacheable placeholder — not a
    transient miss, so it must not raise (which would retry forever)."""
    from routes.media_files import _generate_set_preview, _generate_placeholder_thumbnail

    manifest = tmp_path / "set.stimmaset.json"
    # Only a manifest path (no `resolved`), pointing at a missing file.
    manifest.write_text(json.dumps({"items": [{"path": f"gone/member.{extension}"}]}))

    sentinel = Image.new("RGB", (8, 8))
    with patch(
        "routes.media_files._generate_placeholder_thumbnail",
        return_value=sentinel,
    ) as placeholder:
        result = _generate_set_preview(str(manifest), 32)

    assert result is sentinel
    assert placeholder.called


@pytest.mark.parametrize("extension", ["mp4", "webm", "mov", "avi", "mkv", "m4v", "MP4"])
def test_set_preview_uses_first_video_frames_in_member_order(tmp_path, extension):
    from routes.media_files import _generate_set_preview

    video = tmp_path / f"member.{extension}"
    video.touch()
    image = tmp_path / "member.png"
    generate_test_image(image, color=(20, 220, 30))
    manifest = tmp_path / "set.stimmaset.json"
    manifest.write_text(json.dumps({"items": [{"path": video.name}, {"path": image.name}]}))
    first_frame = Image.new("RGB", (40, 20), (220, 30, 20))

    with patch(
        "utils.video_frames.extract_frame_to_image",
        return_value=(first_frame, 0.0, 1.0, 24.0),
    ) as extract:
        result = _generate_set_preview(str(manifest), 128)

    extract.assert_called_once_with(str(video), position="first")
    assert result.getpixel((64, 64)) == (220, 30, 20)  # first member is on top
    assert result.getpixel((25, 25)) == (20, 220, 30)  # image member behind it


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not installed",
)
@pytest.mark.parametrize("route", ["legacy", "profile", "thumbnail-path"])
@pytest.mark.parametrize("file_format", ["stimmaset.json", "stimmapackage"])
async def test_video_container_thumbnail_replaces_cached_placeholder(
    client: AsyncClient, db_session, tmp_path, route, file_format,
):
    """Decode a real two-frame video and bypass the old cached placeholder
    through every thumbnail entry point, including native drag-out's path API."""
    from config import get_settings
    from routes.media_files import _sharded_cache_path

    source_dir = tmp_path
    if file_format == "stimmapackage":
        source_dir = tmp_path / "video.stimmapackage"
        source_dir.mkdir()
    video = source_dir / "red-then-blue.mp4"
    subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=40x20:r=1:d=1",
            "-f", "lavfi", "-i", "color=c=blue:s=40x20:r=1:d=1",
            "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0",
            "-c:v", "mpeg4", "-q:v", "2", str(video),
        ],
        check=True, capture_output=True,
    )
    if file_format == "stimmapackage":
        manifest = source_dir
        content_path = manifest / "stimma-package.json"
        content_path.write_text(json.dumps({"members": [{"path": video.name}]}))
        mtime_path = manifest / "index.html"
        mtime_path.write_text("<html></html>")
    else:
        manifest = tmp_path / "set.stimmaset.json"
        manifest.write_text(json.dumps({"items": [{"path": video.name}]}))
        content_path = mtime_path = manifest
    file_hash = hashlib.sha256(content_path.read_bytes()).hexdigest()
    async with db_session() as session:
        media = await create_media_item(
            session, file_path=manifest, file_hash=file_hash, file_format=file_format,
        )
        media_id = media.id

    db_guid = get_database_registry().get_db_guid("default")
    prefix = "" if route == "legacy" else f"{db_guid}_"
    old_key = hashlib.md5(
        f"{prefix}{manifest}_64_crop_0_v32_mtime{mtime_path.stat().st_mtime}_themedark".encode()
    ).hexdigest()
    old_cache = _sharded_cache_path(get_settings().get_thumbnail_cache_dir(), old_key, "jpg")
    old_cache.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 64), (0, 255, 255)).save(old_cache)

    urls = {
        "legacy": f"/api/thumbnail/{file_hash}",
        "profile": f"/api/db/{db_guid}/thumbnail/{file_hash}",
        "thumbnail-path": f"/api/db/{db_guid}/media/{media_id}/thumbnail-path",
    }
    response = await client.get(urls[route], params={"size": 64})
    assert response.status_code == 200, response.text
    if route == "thumbnail-path":
        assert response.json()["path"] != str(old_cache)
        thumbnail = Image.open(response.json()["path"])
    else:
        thumbnail = Image.open(io.BytesIO(response.content))
    with thumbnail:
        red, green, blue = thumbnail.getpixel((32, 32))
        assert red > 180 and green < 70 and blue < 70  # first frame, not blue or placeholder


@pytest.mark.parametrize("size", [64, 128, 256, 512, 1024])
@pytest.mark.parametrize("theme", ["dark", "light"])
def test_empty_set_icon_fits_and_is_centered(size, theme):
    from routes.media_files import _generate_placeholder_thumbnail, THEME_PALETTES

    palette = THEME_PALETTES[theme]
    result = _generate_placeholder_thumbnail(size, "set", palette=palette)
    background = Image.new("RGB", result.size, palette["placeholder_set_bg"])
    left, top, right, bottom = ImageChops.difference(result, background).getbbox()

    assert 0 < left < right < size
    assert 0 < top < bottom < size
    assert abs(left - (size - right)) <= 1
    assert abs(top - (size - bottom)) <= 1
    assert right - left == bottom - top


@pytest.mark.parametrize("extension", ["jpg", "webp", "mp4"])
@pytest.mark.parametrize("source", ["member", "run"])
def test_package_preview_uses_visual_members_and_outputs(tmp_path, extension, source):
    from routes.media_files import _generate_package_preview

    hero = tmp_path / f"hero.{extension}"
    if extension == "mp4":
        hero.touch()
    else:
        Image.new("RGB", (40, 20), (220, 30, 20)).save(hero)
    manifest = {"members": [], "runs": []}
    if source == "member":
        manifest["members"] = [{"path": hero.name}]
    else:
        smaller = tmp_path / "smaller.png"
        Image.new("RGB", (4, 4), (0, 0, 255)).save(smaller)
        manifest["runs"] = [{"files": [
            {"path": smaller.name, "size": 100},
            {"path": hero.name, "size": 1024},
        ]}]
    (tmp_path / "stimma-package.json").write_text(json.dumps(manifest))

    with patch(
        "utils.video_frames.extract_frame_to_image",
        return_value=(Image.new("RGB", (40, 20), (220, 30, 20)), 0.0, 1.0, 24.0),
    ) as extract:
        result = _generate_package_preview(str(tmp_path), 64)

    red, green, blue = result.getpixel((32, 32))
    assert red > 180 and green < 70 and blue < 70
    if extension == "mp4":
        extract.assert_called_once_with(hero, position="first")
    else:
        extract.assert_not_called()


def test_package_preview_prefers_designed_cover_over_video(tmp_path):
    from routes.media_files import _generate_package_preview

    Image.new("RGB", (40, 20), (20, 30, 220)).save(tmp_path / "cover.png")
    (tmp_path / "member.mp4").touch()
    (tmp_path / "stimma-package.json").write_text(json.dumps({
        "cover_image": "cover.png", "members": [{"path": "member.mp4"}],
    }))

    with patch("utils.video_frames.extract_frame_to_image") as extract:
        result = _generate_package_preview(str(tmp_path), 64)

    extract.assert_not_called()
    assert result.getpixel((32, 32)) == (20, 30, 220)


def test_grid_preview_passes_video_cells_to_mosaic(tmp_path):
    from routes.media_files import _generate_grid_preview

    video = tmp_path / "member.mp4"
    video.touch()
    manifest = tmp_path / "grid.stimmagrid.json"
    manifest.write_text(json.dumps({"rows": 1, "cols": 1, "cells": []}))
    normalized = {
        "rows": 1,
        "cols": 1,
        "cells": [{"row": 0, "col": 0, "resolved": {"file_path": str(video)}}],
    }
    expected = Image.new("RGB", (32, 32))

    with patch("routes.media_files._create_grid_mosaic", return_value=expected) as mosaic:
        result = _generate_grid_preview(
            str(manifest),
            32,
            normalized_content=normalized,
        )

    assert result is expected
    assert mosaic.call_args.args[0] == [str(video)]


def test_grid_mosaic_uses_first_video_frame(tmp_path):
    from routes.media_files import _create_grid_mosaic

    video = tmp_path / "member.mp4"
    video.touch()
    first_frame = Image.new("RGB", (40, 20), (220, 30, 20))

    with patch(
        "utils.video_frames.extract_frame_to_image",
        return_value=(first_frame, 0.0, 1.0, 24.0),
    ) as extract:
        result = _create_grid_mosaic(
            [str(video)],
            64,
            "#00ffff",
            grid_cols=1,
            grid_rows=1,
        )

    extract.assert_called_once_with(str(video), position="first")
    assert result.getpixel((32, 32)) == (220, 30, 20)


class TestFileCacheHeaders:
    """Only content-addressed URLs may be cached immutably.

    Historical schemas recycled media_items.id after permanent deletion.
    Revalidation keeps those old URL entries from painting deleted images.
    """

    async def test_id_keyed_file_is_revalidated_not_immutable(self, client: AsyncClient, db_session, tmp_path):
        file_path = tmp_path / "id-keyed.png"
        file_hash = generate_test_image(file_path, color=(10, 20, 30))

        async with db_session() as session:
            media = await create_media_item(session, file_path=file_path, file_hash=file_hash)
            media_id = media.id

        db_guid = get_database_registry().get_db_guid("default")

        for url in (f"/api/media/{media_id}/file", f"/api/db/{db_guid}/media/{media_id}/file"):
            response = await client.get(url)
            assert response.status_code == 200, url
            assert "immutable" not in response.headers.get("cache-control", ""), url
            assert response.headers["cache-control"] == "no-cache", url

    async def test_hash_keyed_file_stays_immutable(self, client: AsyncClient, db_session, tmp_path):
        file_path = tmp_path / "hash-keyed.png"
        file_hash = generate_test_image(file_path, color=(30, 20, 10))

        async with db_session() as session:
            await create_media_item(session, file_path=file_path, file_hash=file_hash)

        db_guid = get_database_registry().get_db_guid("default")

        response = await client.get(f"/api/db/{db_guid}/media/by-hash/{file_hash}/file")
        assert response.status_code == 200
        assert "immutable" in response.headers["cache-control"]

    async def test_id_thumbnail_redirect_is_revalidated(self, client: AsyncClient, db_session, tmp_path):
        path = tmp_path / "redirect.png"
        file_hash = generate_test_image(path, width=73)
        async with db_session() as session:
            media = await create_media_item(session, file_path=path, file_hash=file_hash)
            media_id = media.id
        db_guid = get_database_registry().get_db_guid("default")
        for url in (
            f"/api/media/{media_id}/thumbnail",
            f"/api/db/{db_guid}/media/{media_id}/thumbnail",
        ):
            response = await client.get(url, follow_redirects=False)
            assert response.status_code == 307
            assert response.headers.get("cache-control") == "no-cache"
            assert "v=" in response.headers["location"]


@pytest.mark.parametrize("route", ["legacy", "profile", "thumbnail-path"])
async def test_thumbnail_cache_distinguishes_content_at_same_path(
    client: AsyncClient, db_session, tmp_path, route,
):
    """A new payload at a reused locator must never inherit the old bitmap."""
    path = tmp_path / f"reused-{route}.png"
    db_guid = get_database_registry().get_db_guid("default")
    responses = []
    for color in ((255, 0, 0), (0, 0, 255)):
        file_hash = generate_test_image(
            path, color=color, width={"legacy": 137, "profile": 139, "thumbnail-path": 149}[route],
        )
        async with db_session() as session:
            media = await create_media_item(session, file_path=path, file_hash=file_hash)
            media_id = media.id
        urls = {
            "legacy": f"/api/thumbnail/{file_hash}",
            "profile": f"/api/db/{db_guid}/thumbnail/{file_hash}",
            "thumbnail-path": f"/api/db/{db_guid}/media/{media_id}/thumbnail-path",
        }
        response = await client.get(urls[route], params={"size": 64})
        assert response.status_code == 200, response.text
        if route == "thumbnail-path":
            bitmap = Image.open(response.json()["path"])
        else:
            bitmap = Image.open(io.BytesIO(response.content))
        with bitmap:
            responses.append(bitmap.convert("RGB").getpixel((32, 32)))
    for actual, expected in zip(responses, ((255, 0, 0), (0, 0, 255))):
        assert all(abs(a - b) <= 2 for a, b in zip(actual, expected)), responses


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
