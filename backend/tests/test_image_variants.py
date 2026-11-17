"""Image delivery variants: `screen` (2560 px WebP) and `full` (full-res lossy)."""

import asyncio
import hashlib
import io
from pathlib import Path
from unittest.mock import patch

import pytest
from httpx import AsyncClient
from PIL import Image, ImageCms
from sqlalchemy import select

from database import MediaThumbnailCache
from database_registry import get_database_registry
from tests.helpers.media import create_media_item


def _write_image(path: Path, size, mode="RGB", fmt="PNG", **save_kwargs) -> str:
    """A noisy gradient, so encoders cannot collapse it to nothing."""
    path.parent.mkdir(parents=True, exist_ok=True)
    width, height = size
    gradient = Image.linear_gradient("L").resize(size)
    noise = Image.effect_noise(size, 24)
    channels = [gradient, noise, gradient.transpose(Image.Transpose.FLIP_LEFT_RIGHT)]
    img = Image.merge("RGB", channels)
    if mode == "RGBA":
        alpha = Image.new("L", size, 255)
        alpha.paste(0, (0, 0, width // 2, height // 2))
        img = img.convert("RGBA")
        img.putalpha(alpha)
    img.save(path, fmt, **save_kwargs)
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def _media(db_session, path, file_hash, size, file_format="png", file_size=None):
    async with db_session() as session:
        media = await create_media_item(
            session, file_path=path, file_hash=file_hash, file_format=file_format,
            width=size[0], height=size[1], file_size=file_size or path.stat().st_size,
        )
        return media.id


def _url(file_hash, tier):
    db_guid = get_database_registry().get_db_guid("default")
    return f"/api/db/{db_guid}/media/by-hash/{file_hash}/variant/{tier}"


async def _cache_paths(db_session, media_id):
    async with db_session() as session:
        rows = await session.scalars(
            select(MediaThumbnailCache.cache_path).where(MediaThumbnailCache.media_id == media_id)
        )
        return [str(path) for path in rows]


async def test_screen_variant_is_2560_webp_with_icc_and_cache_record(client: AsyncClient, db_session, tmp_path):
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    path = tmp_path / "large.png"
    file_hash = _write_image(path, (3400, 4600), icc_profile=srgb)
    media_id = await _media(db_session, path, file_hash, (3400, 4600))

    for _ in range(2):  # cold generation, then the disk cache
        response = await client.get(_url(file_hash, "screen"))
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/webp"
        assert "immutable" in response.headers["cache-control"]
        with Image.open(io.BytesIO(response.content)) as img:
            assert img.format == "WEBP"
            assert img.size == (1892, 2560)
            assert img.info.get("icc_profile") == srgb
        assert len(response.content) < path.stat().st_size / 4

    recorded = await _cache_paths(db_session, media_id)
    assert any(p.endswith(".screen.webp") and Path(p).exists() for p in recorded)


async def test_small_original_is_served_as_is(client: AsyncClient, db_session, tmp_path):
    path = tmp_path / "medium.png"
    file_hash = _write_image(path, (2400, 3200))
    await _media(db_session, path, file_hash, (2400, 3200))

    for tier in ("screen", "full"):
        response = await client.get(_url(file_hash, tier), follow_redirects=False)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content == path.read_bytes()


async def test_screen_keeps_alpha(client: AsyncClient, db_session, tmp_path):
    path = tmp_path / "alpha.png"
    file_hash = _write_image(path, (3600, 3600), mode="RGBA")
    await _media(db_session, path, file_hash, (3600, 3600))

    response = await client.get(_url(file_hash, "screen"))
    assert response.status_code == 200
    with Image.open(io.BytesIO(response.content)) as img:
        assert img.size == (2560, 2560)
        assert img.mode == "RGBA"
        assert img.getpixel((10, 10))[3] == 0
        assert img.getpixel((2500, 2500))[3] == 255


async def test_full_is_full_res_jpeg_when_opaque_and_webp_with_alpha(client: AsyncClient, db_session, tmp_path):
    opaque = tmp_path / "opaque.png"
    opaque_hash = _write_image(opaque, (3400, 4600))
    # Recorded size decides the skip rule; claim a big lossless file.
    await _media(db_session, opaque, opaque_hash, (3400, 4600), file_size=20 * 1024 * 1024)
    response = await client.get(_url(opaque_hash, "full"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(response.content)) as img:
        assert img.size == (3400, 4600)
        # 4:4:4 chroma: no subsampling of color edges.
        from PIL import JpegImagePlugin
        assert JpegImagePlugin.get_sampling(img) == 0

    alpha = tmp_path / "alpha-full.png"
    alpha_hash = _write_image(alpha, (3300, 3300), mode="RGBA")
    await _media(db_session, alpha, alpha_hash, (3300, 3300), file_size=20 * 1024 * 1024)
    response = await client.get(_url(alpha_hash, "full"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(response.content)) as img:
        assert img.size == (3300, 3300) and img.mode == "RGBA"


async def test_full_of_lossy_original_is_the_original(client: AsyncClient, db_session, tmp_path):
    path = tmp_path / "photo.jpg"
    file_hash = _write_image(path, (4000, 3000), fmt="JPEG", quality=90)
    await _media(db_session, path, file_hash, (4000, 3000), file_format="jpg")

    full = await client.get(_url(file_hash, "full"))
    assert full.headers["content-type"] == "image/jpeg"
    assert full.content == path.read_bytes()
    screen = await client.get(_url(file_hash, "screen"))
    assert screen.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(screen.content)) as img:
        assert img.size == (2560, 1920)


async def test_screen_applies_exif_orientation(client: AsyncClient, db_session, tmp_path):
    path = tmp_path / "rotated.jpg"
    exif = Image.Exif()
    exif[0x0112] = 6  # rotate 90 CW on display
    file_hash = _write_image(path, (4000, 3000), fmt="JPEG", quality=90, exif=exif.tobytes())
    await _media(db_session, path, file_hash, (4000, 3000), file_format="jpg")

    response = await client.get(_url(file_hash, "screen"))
    with Image.open(io.BytesIO(response.content)) as img:
        assert img.size == (1920, 2560)


async def test_variant_rejects_unknown_tier_and_non_images(client: AsyncClient, db_session, tmp_path):
    path = tmp_path / "unknown-tier.png"
    file_hash = _write_image(path, (3400, 3400))
    await _media(db_session, path, file_hash, (3400, 3400))
    assert (await client.get(_url(file_hash, "huge"))).status_code == 404

    doc = tmp_path / "notes.md"
    doc.write_text("# hi")
    doc_hash = hashlib.sha256(doc.read_bytes()).hexdigest()
    await _media(db_session, doc, doc_hash, (0, 0), file_format="md")
    assert (await client.get(_url(doc_hash, "screen"))).status_code == 404


async def test_profile_route_serves_the_same_variant(client: AsyncClient, db_session, tmp_path):
    path = tmp_path / "profile-route.png"
    file_hash = _write_image(path, (3500, 3500))
    await _media(db_session, path, file_hash, (3500, 3500))
    response = await client.get(f"/api/media/by-hash/{file_hash}/variant/screen")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    assert "immutable" not in response.headers.get("cache-control", "")


async def test_eager_screen_generation_records_and_writes(db_session, tmp_path):
    from config import get_settings
    from utils import image_variants as variants

    large = tmp_path / "eager-large.png"
    large_hash = _write_image(large, (3400, 4600))
    small = tmp_path / "eager-small.png"
    small_hash = _write_image(small, (1024, 1024))
    large_id = await _media(db_session, large, large_hash, (3400, 4600))
    small_id = await _media(db_session, small, small_hash, (1024, 1024))

    db = get_database_registry().get_database("default")
    assert await variants.queue_eager_screen_for_media(db, [large_id, small_id]) == 1
    key = variants.variant_cache_key(db.db_guid, large_hash, "screen")
    job = variants.eager_jobs.get(key)
    if job is not None:
        await asyncio.wrap_future(job.future)
    cached = variants.existing_variant(get_settings().get_thumbnail_cache_dir(), key, "screen")
    assert cached is not None
    with Image.open(cached) as img:
        assert img.size == (1892, 2560)
    assert str(cached) in await _cache_paths(db_session, large_id)
    assert await _cache_paths(db_session, small_id) == []
    # Already on disk: nothing is queued twice.
    assert await variants.queue_eager_screen_for_media(db, [large_id]) == 0


@pytest.mark.parametrize(
    "tier,fmt,size,file_size,expected",
    [
        ("screen", "png", (3200, 2000), 20_000_000, True),
        ("screen", "png", (3201, 2000), 20_000_000, False),
        ("screen", "png", (6000, 4000), 400_000, True),
        ("screen", "gif", (6000, 4000), 20_000_000, True),
        ("screen", "jpg", (6000, 4000), 4_000_000, False),
        ("full", "jpg", (6000, 4000), 4_000_000, True),
        ("full", "png", (6000, 4000), 2_000_000, True),
        ("full", "png", (6000, 4000), 20_000_000, False),
    ],
)
def test_skip_rule(tier, fmt, size, file_size, expected):
    from utils.image_variants import variant_serves_original

    assert variant_serves_original(tier, fmt, size[0], size[1], file_size) is expected


async def test_rgb_png_with_trns_keeps_alpha(client: AsyncClient, db_session, tmp_path):
    """An RGB PNG whose tRNS color marks transparency takes the alpha path."""
    path = tmp_path / "trns.png"
    img = Image.new("RGB", (3400, 3400), (10, 200, 30))
    img.paste((255, 0, 255), (0, 0, 1700, 1700))
    img.save(path, transparency=(255, 0, 255))
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    await _media(db_session, path, file_hash, (3400, 3400), file_size=20 * 1024 * 1024)

    screen = await client.get(_url(file_hash, "screen"))
    with Image.open(io.BytesIO(screen.content)) as out:
        assert out.mode == "RGBA"
        assert out.getpixel((10, 10))[3] == 0
        assert out.getpixel((2500, 2500))[3] == 255
    full = await client.get(_url(file_hash, "full"))
    assert full.headers["content-type"] == "image/webp"


@pytest.mark.parametrize("kind", ["cmyk", "gray-icc"])
async def test_non_rgb_sources_convert_to_srgb(client: AsyncClient, db_session, tmp_path, kind):
    """CMYK and non-RGB-profile sources get real variants, tagged sRGB."""
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB"))
    if kind == "cmyk":
        path = tmp_path / "cmyk.jpg"
        Image.new("CMYK", (4000, 3000), (0, 255, 255, 0)).save(path, quality=95)  # red
        fmt, size, expected = "jpg", (4000, 3000), (2560, 1920)
    else:
        path = tmp_path / "gray-icc.png"
        gray = ImageCms.ImageCmsProfile(ImageCms.createProfile("LAB")).tobytes()
        gray = gray[:16] + b"GRAY" + gray[20:]  # a gray-tagged profile
        Image.linear_gradient("L").resize((3400, 3400)).save(path, icc_profile=gray)
        fmt, size, expected = "png", (3400, 3400), (2560, 2560)
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    await _media(db_session, path, file_hash, size, file_format=fmt, file_size=20 * 1024 * 1024)

    response = await client.get(_url(file_hash, "screen"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/webp"
    with Image.open(io.BytesIO(response.content)) as out:
        assert out.mode == "RGB"
        assert out.size == expected
        # Compare descriptions: profile bytes carry a creation timestamp.
        profile = ImageCms.ImageCmsProfile(io.BytesIO(out.info["icc_profile"]))
        assert ImageCms.getProfileDescription(profile) == ImageCms.getProfileDescription(srgb)
        if kind == "cmyk":
            red, green, blue = out.getpixel((100, 100))
            assert red > 200 and green < 60 and blue < 60


async def test_shutdown_drops_queued_eager_jobs(monkeypatch, tmp_path):
    import queue
    from utils import image_variants as variants

    pending = queue.Queue()
    job = variants.EagerJob(str(tmp_path / "x.png"), tmp_path, "q" * 32)
    pending.put(job)
    monkeypatch.setattr(variants, "_eager_queue", pending)
    await variants.shutdown(timeout=0.1)
    assert pending.empty()
    assert job.future.cancelled()


async def test_failure_fallback_is_not_cacheable(client: AsyncClient, db_session, tmp_path):
    from utils import image_variants as variants

    path = tmp_path / "broken-encode.png"
    file_hash = _write_image(path, (3400, 3400))
    await _media(db_session, path, file_hash, (3400, 3400))

    def boom(*_args):
        raise OSError("encoder failed")

    with patch.object(variants, "generate_variant_sync", boom):
        response = await client.get(_url(file_hash, "screen"))
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"


async def test_viewer_does_not_wait_for_a_queued_eager_job(client: AsyncClient, db_session, tmp_path):
    from config import get_settings
    from utils import image_variants as variants

    path = tmp_path / "queued.png"
    file_hash = _write_image(path, (3400, 3400))
    await _media(db_session, path, file_hash, (3400, 3400))
    key = variants.variant_cache_key(get_database_registry().get_db_guid("default"), file_hash, "screen")
    queued = variants.EagerJob(str(path), get_settings().get_thumbnail_cache_dir(), key)
    variants.eager_jobs[key] = queued  # queued behind a backlog, never started
    try:
        response = await asyncio.wait_for(client.get(_url(file_hash, "screen")), timeout=30)
    finally:
        variants.eager_jobs.pop(key, None)
    assert response.headers["content-type"] == "image/webp"
    assert not queued.future.done()


async def test_eager_write_for_deleted_media_is_removed(tmp_path):
    from utils import image_variants as variants

    written = tmp_path / "orphan.screen.webp"
    written.write_bytes(b"x")
    job = variants.EagerJob(str(tmp_path / "gone.png"), tmp_path, "k" * 32)
    job.future.set_result(written)
    db = get_database_registry().get_database("default")
    await variants._finish_eager(db, 987654321, job, "k" * 32)
    assert not written.exists()


async def test_16_bit_grayscale_keeps_midtones(client: AsyncClient, db_session, tmp_path):
    """16-bit gray samples scale to 8-bit instead of clipping to white."""
    import numpy as np

    width, height = 3600, 3400
    samples = np.zeros((height, width), np.uint16)
    for band, value in enumerate((16384, 32768, 49152)):  # quarter, half, three quarters
        samples[:, band * 1200:(band + 1) * 1200] = value
    path = tmp_path / "gray16.png"
    Image.fromarray(samples).save(path)
    with Image.open(path) as check:
        assert check.mode.startswith("I")
    file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    await _media(db_session, path, file_hash, (width, height), file_size=20 * 1024 * 1024)

    for tier in ("screen", "full"):
        response = await client.get(_url(file_hash, tier))
        assert response.status_code == 200
        assert response.headers["content-type"] != "image/png", tier
        with Image.open(io.BytesIO(response.content)) as out:
            row = out.height // 2
            for band, expected in enumerate((64, 128, 191)):
                x = int((band + 0.5) * out.width / 3)
                assert all(abs(channel - expected) <= 3 for channel in out.getpixel((x, row))[:3]), (tier, band)
