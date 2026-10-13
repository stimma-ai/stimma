"""Share links: status, payload builders per media type, provenance, size, links.

The cloud is never contacted: ``routes.share._cloud_client`` is swapped for an
httpx client on a ``MockTransport`` and the sign-in token is faked. Payloads are
built from real files and real library rows, and every one of them is checked
for local paths, ids and raw metadata, which must never be published.
"""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import subprocess
import zipfile
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path
from typing import Any

import httpx
import pytest
from PIL import Image, ImageDraw, PngImagePlugin

import routes.share as share_route
import share_payloads
from share_payloads import (
    build_payload,
    strip_jpeg_metadata,
    strip_png_metadata,
    strip_webp_metadata,
)
from share_provenance import ProvenanceError, build_public_sidecar, looks_like_path, parse_provenance
from tests.helpers.media import create_media_item

HAS_FFMPEG = shutil.which("ffmpeg") is not None


# Fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module", autouse=True)
def share_router(test_app):
    test_app.include_router(share_route.router)
    return test_app


@pytest.fixture(scope="module")
def root(temp_appdata_dir: Path) -> Path:
    path = temp_appdata_dir / "share-fixtures"
    path.mkdir(exist_ok=True)
    return path


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    share_route._account_cache.clear()
    monkeypatch.setattr(share_route, "is_privacy_lockdown_enabled", lambda: False)
    yield
    share_route._account_cache.clear()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _png_with_secrets(path: Path, secret: str, color=(200, 40, 40), size=(64, 48)) -> None:
    info = PngImagePlugin.PngInfo()
    info.add_text("parameters", f"a red box, model {secret}/models/flux.safetensors")
    info.add_text("workflow", json.dumps({"ckpt": f"{secret}/ckpt.safetensors"}))
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, color).save(path, format="PNG", pnginfo=info)


async def _media(session, path: Path, fmt: str | None = None, **kw):
    fmt = fmt or path.suffix.lstrip(".").lower()
    w, h = kw.pop("width", 64), kw.pop("height", 48)
    return await create_media_item(
        session, file_path=path, file_hash=_sha(path) if path.is_file() else None,
        file_format=fmt, width=w, height=h, file_size=path.stat().st_size if path.is_file() else 0, **kw,
    )


def _fake_token(monkeypatch, value: str | None = "tok"):
    import firebase_auth

    async def fake(*args, **kwargs):
        return value

    monkeypatch.setattr(firebase_auth, "get_valid_id_token", fake)


class Cloud:
    """Records requests to the mocked cloud and answers from a handler table."""

    def __init__(self, monkeypatch, responder=None):
        self.requests: list[httpx.Request] = []
        self.responder = responder or (lambda req: httpx.Response(200, json={"shortcode": "abc123", "url": "https://share.example/abc123", "status": "approved"}))
        real = httpx.AsyncClient

        def factory(timeout: float):
            return real(transport=httpx.MockTransport(self._handle), timeout=timeout)

        monkeypatch.setattr(share_route, "_cloud_client", factory)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        request.read()
        self.requests.append(request)
        return self.responder(request)


def parse_multipart(request: httpx.Request) -> tuple[dict[str, str], list[tuple[str, str, str, bytes]]]:
    head = b"Content-Type: " + request.headers["content-type"].encode() + b"\r\n\r\n"
    msg = BytesParser(policy=email_policy).parsebytes(head + request.content)
    fields: dict[str, str] = {}
    files: list[tuple[str, str, str, bytes]] = []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        data = part.get_payload(decode=True)
        if part.get_filename():
            files.append((name, part.get_filename(), part.get_content_type(), data))
        else:
            fields[name] = data.decode("utf-8")
    return fields, files


# The privacy checker ──────────────────────────────────────────────────────────

FORBIDDEN_KEYS = {"file_path", "filePath", "media_id", "mediaId", "file_hash", "generation_metadata", "resolved", "asset_id"}


def _blob_strings(name: str, data: bytes) -> list[tuple[str, str]]:
    """Searchable text of a blob, unpacking zips (their members are compressed)."""
    out = [(name, data.decode("latin-1"))]
    if data[:4] == b"PK\x03\x04":
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            for info in zf.infolist():
                out.extend(_blob_strings(f"{name}!{info.filename}", zf.read(info)))
    return out


def assert_private(value: Any, forbidden: list[str], where: str = "payload") -> None:
    """Recursively assert no forbidden substring, path-looking string or private key."""
    if isinstance(value, dict):
        for k, v in value.items():
            assert k not in FORBIDDEN_KEYS, f"{where}: private key {k!r}"
            assert_private(v, forbidden, f"{where}.{k}")
    elif isinstance(value, (list, tuple)):
        for i, v in enumerate(value):
            assert_private(v, forbidden, f"{where}[{i}]")
    elif isinstance(value, (bytes, bytearray)):
        for name, text in _blob_strings(where, bytes(value)):
            for needle in forbidden:
                assert needle not in text, f"{name}: contains {needle!r}"
            if name.endswith(".json"):
                assert_private(json.loads(text), forbidden, name)
    elif isinstance(value, str):
        for needle in forbidden:
            assert needle not in value, f"{where}: contains {needle!r}"
        assert not looks_like_path(value), f"{where}: path-looking string {value[:80]!r}"


def assert_payload_private(payload, root: Path) -> None:
    forbidden = [str(root), str(root.parent), "file_path", "/fake/path"]
    assert_private(payload.metadata, forbidden + [], "metadata")  # sourceHash is allowed here
    if payload.structured_content is not None:
        assert "sourceHash" not in json.dumps(payload.structured_content)
        assert_private(payload.structured_content, forbidden, "structuredContent")
    for field, (filename, data, ctype) in payload.files():
        assert "/" not in filename and "\\" not in filename, filename
        assert_private(filename, forbidden, f"{field}.filename")
        if ctype.startswith(("text/", "application/zip", "image/svg")):
            assert_private(data, forbidden, f"{field}:{filename}")
        else:
            # Binary media: no embedded paths or generator metadata.
            text = data.decode("latin-1")
            for needle in forbidden + ["safetensors", "workflow", "parameters"]:
                assert needle not in text, f"{field}:{filename} embeds {needle!r}"


def _metadata_ok(payload, media):
    assert payload.metadata["sourceHash"] == media.file_hash
    assert payload.metadata["mediaType"] == payload.media_type
    assert "toolId" not in payload.metadata


# Status ───────────────────────────────────────────────────────────────────────

async def test_status_privacy_lockdown(client, monkeypatch):
    monkeypatch.setattr(share_route, "is_privacy_lockdown_enabled", lambda: True)
    body = (await client.get("/api/share/status")).json()
    assert body["can_share"] is False and body["reason_code"] == "privacy_lockdown"


async def test_status_signed_out(client, monkeypatch):
    _fake_token(monkeypatch, None)
    body = (await client.get("/api/share/status")).json()
    assert body == {**body, "can_share": False, "reason_code": "signed_out", "account": None}


async def test_status_auth_expired_on_refresh(client, monkeypatch):
    import firebase_auth

    async def expired(*args, **kwargs):
        raise firebase_auth.AuthSessionExpiredError("expired")

    monkeypatch.setattr(firebase_auth, "get_valid_id_token", expired)
    body = (await client.get("/api/share/status")).json()
    assert body["reason_code"] == "auth_expired" and body["can_share"] is False


async def test_status_auth_expired_on_401(client, monkeypatch):
    import cloud_api

    _fake_token(monkeypatch)

    async def unauthorized(token):
        resp = httpx.Response(401, request=httpx.Request("GET", "https://cloud.test/api/auth/me"))
        raise httpx.HTTPStatusError("401", request=resp.request, response=resp)

    monkeypatch.setattr(cloud_api, "fetch_user_account", unauthorized)
    body = (await client.get("/api/share/status")).json()
    assert body["reason_code"] == "auth_expired"


async def _status_with_account(client, monkeypatch, account: dict) -> dict:
    import cloud_api

    _fake_token(monkeypatch)

    async def fetch(token):
        return account

    monkeypatch.setattr(cloud_api, "fetch_user_account", fetch)
    monkeypatch.setattr(share_route, "_local_profile", lambda: {"displayName": "Local Name", "photoURL": "https://img.test/local.png"})
    return (await client.get("/api/share/status")).json()


async def test_status_banned(client, monkeypatch):
    body = await _status_with_account(client, monkeypatch, {"username": "courier", "sharingBanned": True})
    assert body["reason_code"] == "banned" and body["can_share"] is False


async def test_status_identity_required(client, monkeypatch):
    body = await _status_with_account(client, monkeypatch, {"username": None})
    assert body["can_share"] is False and body["identity_required"] is True and body["reason_code"] is None


async def test_status_ok_reports_publishing_account(client, monkeypatch):
    body = await _status_with_account(
        client, monkeypatch, {"username": "courier", "avatarUrl": "https://img.test/a.png"},
    )
    assert body["can_share"] is True and body["reason_code"] is None
    assert body["account"] == {
        "username": "courier", "display_name": "Local Name", "avatar_url": "https://img.test/a.png",
    }
    assert body["username"] == "courier"


# Embedded metadata stripping ──────────────────────────────────────────────────

def test_png_text_chunks_are_stripped(root):
    path = root / "secret.png"
    _png_with_secrets(path, str(root))
    stripped = strip_png_metadata(path.read_bytes())
    assert str(root).encode() not in stripped and b"workflow" not in stripped
    with Image.open(io.BytesIO(stripped)) as im:
        assert im.size == (64, 48) and im.getpixel((1, 1)) == (200, 40, 40)


def test_jpeg_exif_is_stripped_but_orientation_kept(root):
    exif = Image.Exif()
    exif[0x010E] = f"{root}/private/photo.jpg"  # ImageDescription
    exif[0x0112] = 6
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (10, 200, 10)).save(buf, format="JPEG", exif=exif.tobytes())
    stripped = strip_jpeg_metadata(buf.getvalue())
    assert str(root).encode() not in stripped
    with Image.open(io.BytesIO(stripped)) as im:
        assert im.getexif().get(0x0112) == 6 and im.size == (40, 20)


def test_webp_exif_is_stripped(root):
    exif = Image.Exif()
    exif[0x010E] = f"{root}/private/photo.webp"
    buf = io.BytesIO()
    Image.new("RGB", (40, 20), (10, 10, 200)).save(buf, format="WEBP", exif=exif.tobytes())
    stripped = strip_webp_metadata(buf.getvalue())
    assert str(root).encode() not in stripped
    with Image.open(io.BytesIO(stripped)) as im:
        assert im.size == (40, 20)


# Payload builders ─────────────────────────────────────────────────────────────

async def test_image_payload_strips_metadata(db_session, root):
    path = root / "image" / "render.png"
    _png_with_secrets(path, str(root))
    async with db_session() as session:
        media = await _media(session, path)
        payload = await build_payload(session, media)
    assert payload.media_type == "image"
    assert payload.file.filename == "original.png" and payload.file.content_type == "image/png"
    assert payload.thumbnail and Image.open(io.BytesIO(payload.thumbnail)).format == "WEBP"
    _metadata_ok(payload, media)
    assert_payload_private(payload, root)


@pytest.mark.parametrize("fmt", ["bmp", "tiff"])
async def test_bmp_and_tiff_convert_to_png(db_session, root, fmt):
    path = root / "convert" / f"scan.{fmt}"
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (30, 20), (1, 2, 3)).save(path)
    async with db_session() as session:
        media = await _media(session, path, width=30, height=20)
        payload = await build_payload(session, media)
    assert payload.media_type == "image"
    assert payload.file.content_type == "image/png" and payload.file.filename == "original.png"
    with Image.open(io.BytesIO(payload.file.data)) as im:
        assert im.format == "PNG" and im.size == (30, 20)
    assert_payload_private(payload, root)


def _ffmpeg(*args: str) -> None:
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
async def test_avi_transcodes_to_faststart_mp4(db_session, root):
    path = root / "video" / "clip.avi"
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-metadata", f"comment={root}/private", "-shortest", str(path))
    async with db_session() as session:
        media = await _media(session, path, duration=1.0)
        payload = await build_payload(session, media)
    assert payload.media_type == "video"
    assert payload.file.content_type == "video/mp4" and payload.file.filename == "original.mp4"
    data = payload.file.data
    assert 0 < data.find(b"moov") < data.find(b"mdat"), "moov atom should precede mdat (faststart)"
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_name", "-of", "json", "-"],
        input=data, capture_output=True, check=True,
    )
    codecs = {s["codec_name"] for s in json.loads(probe.stdout)["streams"]}
    assert {"h264", "aac"} <= codecs
    assert payload.thumbnail
    assert_payload_private(payload, root)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
async def test_mp4_passes_through_without_metadata(db_session, root):
    path = root / "video" / "clip.mp4"
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "testsrc=size=64x48:rate=10:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-metadata", f"title={root}/private", str(path))
    assert str(root).encode() in path.read_bytes()
    async with db_session() as session:
        media = await _media(session, path)
        payload = await build_payload(session, media)
    assert payload.file.content_type == "video/mp4"
    assert_payload_private(payload, root)


async def test_video_conversion_without_ffmpeg_is_a_clear_error(db_session, root, monkeypatch):
    path = root / "video" / "nofmpeg.mkv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\x1aE\xdf\xa3not really mkv")
    monkeypatch.setattr(share_payloads, "ffmpeg_path", lambda: None)
    async with db_session() as session:
        media = await _media(session, path)
        with pytest.raises(share_payloads.ShareBuildError, match="FFmpeg"):
            await build_payload(session, media)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
async def test_audio_payload_has_waveform_card(db_session, root):
    path = root / "audio" / "tone.wav"
    path.parent.mkdir(parents=True, exist_ok=True)
    _ffmpeg("-f", "lavfi", "-i", "sine=frequency=330:duration=2", "-metadata", f"title={root}/private", str(path))
    async with db_session() as session:
        media = await _media(session, path, duration=2.0, width=0, height=0)
        payload = await build_payload(session, media)
    assert payload.media_type == "audio"
    assert payload.file.content_type == "audio/wav" and payload.file.filename == "original.wav"
    with Image.open(io.BytesIO(payload.thumbnail)) as im:
        assert im.format == "WEBP" and im.size == (1200, 630)
        im = im.convert("RGB")
        assert max(im.getpixel((5, 5))) < 20, "matte corner should be near-black"
        assert max(im.getpixel((600, 315))) > 150, "waveform should be light"
    _metadata_ok(payload, media)
    assert payload.metadata["width"] is None
    assert_payload_private(payload, root)


async def test_markdown_rewrites_library_refs_and_drops_local_ones(db_session, root):
    doc_dir = root / "text"
    pic = doc_dir / "pics" / "pic.png"
    other = root / "elsewhere" / "other.png"
    _png_with_secrets(pic, str(root), color=(0, 0, 255))
    _png_with_secrets(other, str(root), color=(0, 255, 0))
    md = doc_dir / "notes.md"
    md.write_text(
        "---\nauthor: Someone Private\nsource: " + str(root) + "\n---\n"
        "# Notes\n\n"
        "![relative](pics/pic.png)\n"
        f"![absolute]({other})\n"
        "![again](./pics/pic.png \"same picture\")\n"
        f"![gone]({root}/missing.png)\n"
        "![web](https://example.com/a.png)\n"
        f"[a local file](file://{root}/secret.txt) and [a site](https://example.com)\n"
        f'<img src="{root}/missing2.png">\n'
        "[ref]: " + str(other) + "\n",
        encoding="utf-8",
    )
    async with db_session() as session:
        await _media(session, pic)
        await _media(session, other)
        media = await _media(session, md, fmt="md", width=0, height=0)
        payload = await build_payload(session, media)

    body = payload.file.data.decode("utf-8")
    assert payload.media_type == "text" and payload.file.content_type == "text/markdown"
    assert "![relative](members/0.png)" in body
    assert "![absolute](members/1.png)" in body
    assert '![again](members/0.png "same picture")' in body
    assert "![gone]" not in body and "gone" in body
    assert "![web](https://example.com/a.png)" in body
    assert "a local file" in body and "file://" not in body
    assert "[a site](https://example.com)" in body
    assert "[ref]: members/1.png" in body
    assert "Someone Private" not in body
    assert len(payload.members) == 2
    assert [m.filename for m in payload.members] == ["0.png", "1.png"]
    assert payload.structured_content == {"version": 1, "images": 2}
    assert payload.thumbnail
    assert_payload_private(payload, root)


async def test_markdown_without_images_has_no_thumbnail(db_session, root):
    md = root / "text" / "plain.md"
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text("Just words.\n", encoding="utf-8")
    async with db_session() as session:
        media = await _media(session, md, fmt="md", width=0, height=0)
        payload = await build_payload(session, media)
    assert payload.thumbnail is None and payload.members == []
    assert payload.structured_content == {"version": 1, "images": 0}


async def test_vector_payload(db_session, root, monkeypatch):
    svg = root / "vector" / "mark.svg"
    svg.parent.mkdir(parents=True, exist_ok=True)
    svg.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="24" height="24">'
        f'<!-- {root} --><image xlink:href="file://{root}/x.png" width="4" height="4"/>'
        '<circle cx="12" cy="12" r="10" fill="#000"/></svg>',
        encoding="utf-8",
    )

    async def fake_raster(path, long_side=560):
        return Image.new("RGBA", (200, 200), (0, 0, 0, 255))

    monkeypatch.setattr(share_payloads, "rasterize_svg", fake_raster)
    async with db_session() as session:
        media = await _media(session, svg, fmt="svg", width=24, height=24)
        payload = await build_payload(session, media)
    assert payload.media_type == "vector"
    assert payload.file.content_type == "image/svg+xml" and payload.file.filename == "original.svg"
    assert payload.file.data.decode().lstrip().startswith("<svg")
    with Image.open(io.BytesIO(payload.thumbnail)) as im:
        assert im.size == (1200, 630)
    assert_payload_private(payload, root)


def _frames(n, color=(200, 60, 60, 255)):
    frames = []
    for i in range(n):
        im = Image.new("RGBA", (16, 24), (0, 0, 0, 0))
        ImageDraw.Draw(im).rectangle([2, 2 + i, 12, 20], fill=color)
        frames.append(im)
    return frames


def _write_webp(path: Path, frames, fps=12):
    path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(path, format="WEBP", save_all=True, append_images=frames[1:],
                   duration=round(1000 / fps), loop=0, lossless=True)


def _anim(name, direction, ref, n, fps=12, loop="loop"):
    return {
        "name": name, "direction": direction, "mirrored_from": None, "fps": fps, "loop": loop,
        "loop_start": 0, "loop_end": n - 1, "source_video": None, "anchor": None, "prompt": None,
        "animation": {**ref, "format": "webp"}, "frame_count": n,
        "frames": [{"duration_ms": None, "rects": {}, "events": []} for _ in range(n)],
    }


async def test_sprite_payload(db_session, root):
    sdir = root / "sprite"
    run, idle, base = sdir / "run.webp", sdir / "idle.webp", sdir / "base.png"
    _write_webp(run, _frames(6))
    _write_webp(idle, _frames(4, (60, 60, 200, 255)), fps=8)
    _frames(1)[0].save(base)
    async with db_session() as session:
        run_m = await _media(session, run, fmt="webp", width=16, height=24)
        idle_m = await _media(session, idle, fmt="webp", width=16, height=24)
        base_m = await _media(session, base, width=16, height=24)
        doc = {
            "type": "sprite", "version": 1, "title": "Courier", "style": "16-bit pixel art",
            "base_image": {"media_id": base_m.id, "hash": base_m.file_hash},
            "base_image_nobg": None, "portrait": None, "anchor": {"x": 0.5, "y": 1.0},
            "production": {"notes": str(root)},
            "animations": [
                _anim("run", "east", {"media_id": run_m.id, "hash": run_m.file_hash}, 6),
                _anim("idle", None, {"hash": idle_m.file_hash}, 4, fps=8, loop="pingpong"),
            ],
        }
        doc_path = sdir / "courier.stimmasprite.json"
        doc_path.write_text(json.dumps(doc))
        media = await create_media_item(
            session, file_path=doc_path, file_hash=_sha(doc_path), file_format="stimmasprite.json",
            width=0, height=0, raw_metadata=json.dumps(doc),
        )
        payload = await build_payload(session, media)

    sc = payload.structured_content
    assert payload.media_type == "sprite" and payload.file is None
    assert sc["version"] == 1 and sc["title"] == "Courier" and sc["pixelated"] is True
    assert sc["anchor"] == {"x": 0.5, "y": 1.0}
    assert [a["name"] for a in sc["animations"]] == ["run", "idle"]
    run_sc, idle_sc = sc["animations"]
    assert run_sc == {
        "name": "run", "direction": "east", "fps": 12.0, "loop": "loop", "loopStart": 0, "loopEnd": 5,
        "frameCount": 6, "durationsMs": [83] * 6, "member": 0,
    }
    assert idle_sc["member"] == 1 and idle_sc["loop"] == "pingpong" and idle_sc["durationsMs"] == [125] * 4
    assert [m.content_type for m in payload.members] == ["image/webp", "image/webp"]
    with Image.open(io.BytesIO(payload.members[0].data)) as im:
        assert getattr(im, "n_frames", 1) == 6
    with Image.open(io.BytesIO(payload.thumbnail)) as im:
        assert im.size == (1200, 630)
    assert_payload_private(payload, root)


async def test_package_payload(db_session, root):
    from packages.bundle import PackageBuilder

    master = root / "package" / "master.png"
    _png_with_secrets(master, str(root), size=(256, 256))
    async with db_session() as session:
        master_m = await _media(session, master, width=256, height=256)
        async with PackageBuilder(session, profile_id="default", title="Acme kit") as builder:
            await builder.add_member(master_m.id, role="master")
            media, _asset = await builder.save(materialize_asset=True)
        payload = await build_payload(session, media)

    assert payload.media_type == "package"
    assert payload.file.content_type == "text/html" and payload.file.filename == "index.html"
    assert len(payload.members) == 1
    zip_part = payload.members[0]
    assert zip_part.content_type == "application/zip" and zip_part.filename.endswith(".zip")
    sc = payload.structured_content
    assert sc == {"version": 1, "zip": zip_part.filename, "zipBytes": len(zip_part.data), "memberCount": 1}
    with zipfile.ZipFile(io.BytesIO(zip_part.data)) as zf:
        manifest_name = next(n for n in zf.namelist() if n.endswith("stimma-package.json"))
        assert "media_id" not in zf.read(manifest_name).decode()
    assert payload.thumbnail
    # The package zip deliberately carries the member file itself, so only
    # check the textual parts for paths.
    forbidden = [str(root), "file_path"]
    assert_private(payload.file.data, forbidden, "cover")
    assert_private(sc, forbidden, "structuredContent")
    with zipfile.ZipFile(io.BytesIO(zip_part.data)) as zf:
        for name in zf.namelist():
            if name.endswith((".json", ".html", ".md", ".txt")):
                assert_private(zf.read(name), forbidden, name)


async def _composite_fixture(session, root: Path, kind: str):
    cdir = root / kind
    a, b = cdir / "a.png", cdir / "nested" / "b.png"
    _png_with_secrets(a, str(root), color=(255, 0, 0))
    _png_with_secrets(b, str(root), color=(0, 255, 0))
    await _media(session, a)
    await _media(session, b)
    if kind == "set":
        content = {"version": 1, "title": "Picks", "items": [
            {"path": "a.png", "caption": "first"},
            {"path": str(root / "missing.png")},
            {"path": str(b), "caption": str(root / "leaky")},
        ]}
        name, fmt = "picks.stimmaset.json", "stimmaset.json"
    else:
        content = {"version": 1, "title": "Matrix", "rows": 2, "cols": 2,
                   "row_headers": ["r0", "r1"], "col_headers": ["c0", str(root)],
                   "cells": [
                       {"row": 0, "col": 0, "path": "a.png"},
                       {"row": 0, "col": 1, "path": str(root / "missing.png")},
                       {"row": 1, "col": 1, "path": str(b), "caption": "best"},
                   ]}
        name, fmt = "matrix.stimmagrid.json", "stimmagrid.json"
    path = cdir / name
    path.write_text(json.dumps(content))
    return await create_media_item(
        session, file_path=path, file_hash=_sha(path), file_format=fmt, width=0, height=0,
        raw_metadata=json.dumps(content),
    )


async def test_set_payload_members_by_index(db_session, root):
    async with db_session() as session:
        media = await _composite_fixture(session, root, "set")
        payload = await build_payload(session, media)
    sc = payload.structured_content
    assert payload.media_type == "set"
    assert sc["items"] == [{"member": 0, "caption": "first"}, {"member": 1}]
    assert sc["title"] == "Picks"
    assert [m.filename for m in payload.members] == ["0.png", "1.png"]
    assert payload.thumbnail
    assert_payload_private(payload, root)


async def test_grid_payload_cells_align_with_members(db_session, root):
    async with db_session() as session:
        media = await _composite_fixture(session, root, "grid")
        payload = await build_payload(session, media)
    sc = payload.structured_content
    assert sc["rows"] == 2 and sc["cols"] == 2
    assert sc["row_headers"] == ["r0", "r1"] and sc["col_headers"] == ["c0", ""]
    assert sc["cells"] == [{"row": 0, "col": 0, "member": 0}, {"row": 1, "col": 1, "member": 1, "caption": "best"}]
    assert len(payload.members) == 2
    assert payload.metadata["rowHeaders"] == ["r0", "r1"]
    assert_payload_private(payload, root)


async def test_layout_payload(db_session, root):
    bundle = root / "layout" / "poster.stimmalayout"
    bundle.mkdir(parents=True, exist_ok=True)
    _png_with_secrets(bundle / "hero.png", str(root))
    (bundle / "index.html").write_text(f'<img src="hero.png"><a href="file://{root}/x">x</a>', encoding="utf-8")
    async with db_session() as session:
        media = await create_media_item(session, file_path=bundle, file_format="stimmalayout", width=0, height=0)
        payload = await build_payload(session, media)
    assert payload.media_type == "layout"
    assert [m.filename for m in payload.members] == ["hero.png"]
    assert_payload_private(payload, root)


# Provenance ───────────────────────────────────────────────────────────────────

def test_provenance_rejects_bad_shapes():
    assert parse_provenance(None) is None
    for bad in ["text", {"version": 1, "steps": []}, {"version": 2, "steps": [{"model": "x"}]},
                {"version": 2, "steps": "nope"}]:
        with pytest.raises(ProvenanceError):
            parse_provenance(bad)


def test_looks_like_path():
    for s in ["/Users/x/a.png", "see /home/x/a", "C:\\Users\\x", "\\\\server\\share\\x", "file:///x"]:
        assert looks_like_path(s), s
    assert looks_like_path("/tmp/x/y.png")
    for s in ["a cat in a hat", "16:9", "https://example.com/a/b.png", "Crop", "black/white", "AC/DC", "24/7"]:
        assert not looks_like_path(s), s


async def test_provenance_sidecar_is_capped_and_anonymous(db_session, root):
    ref_img = root / "prov" / "ref.png"
    _png_with_secrets(ref_img, str(root), size=(300, 200))
    async with db_session() as session:
        ref = await _media(session, ref_img, width=300, height=200)
        raw = {
            "version": 2,
            "generationMetadata": {"secret": str(root)},
            "steps": [{
                "tool": "Flux 2 Pro",
                "model": "flux-2-pro",
                "date": "2026-10-01T12:00:00Z",
                "prompt": "p" * 9000,
                "negativePrompt": f"see {root}/neg.txt",
                "facts": [{"label": f"L{i}", "value": i} for i in range(50)]
                         + [{"label": "Path", "value": "/Users/x/model.safetensors"}],
                "loras": [{"name": f"lora{i}", "weight": 0.5} for i in range(25)],
                "inputs": [
                    {"role": "Reference", "ref": {"mediaId": ref.id, "hash": ref.file_hash}},
                    {"role": "Again", "ref": {"hash": ref.file_hash}},
                    {"role": "Gone", "ref": {"mediaId": 999999}},
                ],
                "edits": ["Crop", "Exposure"],
                "params": {"seed": 1},
            }, {"tool": "/home/x/tool"}],
        }
        sidecar = await build_public_sidecar(session, parse_provenance(raw))

    assert sidecar["version"] == 2 and len(sidecar["steps"]) == 1
    step = sidecar["steps"][0]
    assert len(step["prompt"]) == 8000
    assert "negativePrompt" not in step
    assert len(step["facts"]) == 40 and step["facts"][1] == {"label": "L1", "value": "1"}
    assert len(step["loras"]) == 20
    assert step["inputs"] == [{"role": "Reference", "thumb": "t0"}, {"role": "Again", "thumb": "t0"}, {"role": "Gone"}]
    assert list(sidecar["thumbnails"]) == ["t0"] and sidecar["thumbnails"]["t0"].startswith("data:image/webp;base64,")
    assert step["edits"] == ["Crop", "Exposure"]
    assert "params" not in step and "generationMetadata" not in sidecar
    text = json.dumps(sidecar)
    assert str(ref.id) not in json.dumps(step["inputs"]) and ref.file_hash not in text
    assert_private({k: v for k, v in sidecar.items() if k != "thumbnails"}, [str(root)], "sidecar")


# Create (end to end through the route) ────────────────────────────────────────

async def _image_media(db_session, root: Path, name: str):
    path = root / "post" / name
    _png_with_secrets(path, str(root))
    async with db_session() as session:
        return await _media(session, path)


async def test_share_sends_sidecar_and_source_hash(client, db_session, root, monkeypatch):
    media = await _image_media(db_session, root, "with-prov.png")
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch)
    resp = await client.post("/api/share", json={
        "media_id": media.id, "title": "Red box",
        "provenance": {"version": 2, "steps": [{"tool": "Flux 2 Pro", "prompt": "a red box",
                                               "inputs": [{"role": "Reference", "ref": {"mediaId": media.id}}]}]},
    })
    body = resp.json()
    assert body["success"] is True and body["shortcode"] == "abc123" and body["media_type"] == "image"
    fields, files = parse_multipart(cloud.requests[0])
    meta = json.loads(fields["metadata"])
    assert meta["sourceHash"] == media.file_hash and meta["title"] == "Red box"
    sidecar = json.loads(fields["historySidecar"])
    assert sidecar["version"] == 2 and sidecar["steps"][0]["inputs"] == [{"role": "Reference", "thumb": "t0"}]
    assert [(f[0], f[1]) for f in files] == [("file", "original.png"), ("thumbnail", "thumb.webp")]
    raw = cloud.requests[0].content.decode("latin-1")
    for needle in [str(root), "file_path", "generationMetadata", "safetensors"]:
        assert needle not in raw


async def test_share_without_provenance_sends_no_sidecar(client, db_session, root, monkeypatch):
    media = await _image_media(db_session, root, "no-prov.png")
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch)
    body = (await client.post("/api/share", json={"media_id": media.id, "provenance": None})).json()
    assert body["success"] is True
    fields, _ = parse_multipart(cloud.requests[0])
    assert "historySidecar" not in fields


async def test_share_invalid_provenance_is_friendly(client, db_session, root, monkeypatch):
    media = await _image_media(db_session, root, "bad-prov.png")
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch)
    body = (await client.post("/api/share", json={"media_id": media.id, "provenance": {"version": 2, "steps": [{}]}})).json()
    assert body["success"] is False and body["error_code"] == "invalid_provenance"
    assert cloud.requests == []


async def test_share_refuses_oversize(client, db_session, root, monkeypatch):
    media = await _image_media(db_session, root, "big.png")
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch)
    monkeypatch.setattr(share_route, "MAX_UPLOAD_BYTES", 100)
    body = (await client.post("/api/share", json={"media_id": media.id})).json()
    assert body["success"] is False and body["error_code"] == "too_large"
    assert "too large" in body["error"]
    assert cloud.requests == []


async def test_pre_check_reports_size_and_type(client, db_session, root, monkeypatch):
    media = await _image_media(db_session, root, "pre.png")
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch, lambda req: httpx.Response(200, json={"decision": "approved", "nsfw": False}))
    body = (await client.post("/api/share/pre-check", json={"media_id": media.id})).json()
    assert body["blocked"] is False and body["too_large"] is False
    assert body["media_type"] == "image" and body["size_bytes"] == media.file_size
    assert body["unsupported_reason"] is None
    assert len(cloud.requests) == 1

    monkeypatch.setattr(share_route, "MAX_UPLOAD_BYTES", 10)
    body = (await client.post("/api/share/pre-check", json={"media_id": media.id})).json()
    assert body["too_large"] is True and "too large" in body["reason"]
    assert len(cloud.requests) == 1, "an oversize item is not sent for moderation"


async def test_pre_check_unsupported_format(client, db_session, root):
    path = root / "doc.pdf"
    path.write_bytes(b"%PDF-1.4")
    async with db_session() as session:
        media = await create_media_item(session, file_path=path, file_format="pdf")
    body = (await client.post("/api/share/pre-check", json={"media_id": media.id})).json()
    assert body["unsupported_reason"] and body["media_type"] is None


@pytest.mark.parametrize("status,detail,expected", [
    (429, "Daily share limit (50) reached. Try again tomorrow.", "share limit"),
    (413, "Payload Too Large", "too large"),
    (403, "Your sharing privileges have been suspended", "suspended"),
    (400, "Unsupported file type: text/markdown", "can't be shared as a link"),
    (500, "Failed to create share", "temporarily unavailable"),
])
async def test_cloud_errors_are_friendly(client, db_session, root, monkeypatch, status, detail, expected):
    media = await _image_media(db_session, root, f"err-{status}.png")
    _fake_token(monkeypatch)
    Cloud(monkeypatch, lambda req: httpx.Response(status, json={"error": detail}))
    body = (await client.post("/api/share", json={"media_id": media.id})).json()
    assert body["success"] is False
    assert expected in body["error"]
    assert "Cloud API error" not in body["error"]
    if status != 403:  # the suspension text happens to be the same sentence
        assert detail not in body["error"]


# Links ────────────────────────────────────────────────────────────────────────

CLOUD_ROW = {
    "shortcode": "abc123", "status": "approved", "mediaType": "image", "title": "Red box",
    "viewCount": 7, "reactionCounts": {}, "thumbnailUrl": "https://share.example/media/shares/abc123/thumb.webp",
    "createdAt": "2026-10-12T10:00:00.000Z", "url": "https://share.example/abc123",
}


async def test_links_for_one_item_filter_by_source_hash(client, db_session, root, monkeypatch):
    media = await _image_media(db_session, root, "links.png")
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch, lambda req: httpx.Response(200, json={"shares": [CLOUD_ROW, {"bad": 1}], "total": 1, "limit": 5, "offset": 0}))
    body = (await client.get(f"/api/share/links?media_id={media.id}&limit=5")).json()
    params = cloud.requests[0].url.params
    assert cloud.requests[0].url.path == "/api/shares"
    assert params["sourceHash"] == media.file_hash and params["limit"] == "5" and params["offset"] == "0"
    assert body["error"] is None and body["total"] == 1
    assert body["links"] == [{
        "shortcode": "abc123", "url": "https://share.example/abc123", "title": "Red box", "status": "approved",
        "media_type": "image", "view_count": 7, "created_at": "2026-10-12T10:00:00.000Z",
        "thumbnail_url": "/api/share/links/abc123/thumbnail",
    }]


async def test_links_all_paginates(client, monkeypatch):
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch, lambda req: httpx.Response(200, json={"shares": [CLOUD_ROW], "total": 30, "limit": 10, "offset": 20}))
    body = (await client.get("/api/share/links?limit=10&offset=20")).json()
    params = cloud.requests[0].url.params
    assert "sourceHash" not in params and params["offset"] == "20"
    assert body["total"] == 30 and body["offset"] == 20 and len(body["links"]) == 1


async def test_links_signed_out(client, monkeypatch):
    _fake_token(monkeypatch, None)
    body = (await client.get("/api/share/links")).json()
    assert body["links"] == [] and body["error"]


async def test_update_link_forwards_only_sent_fields(client, monkeypatch):
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch, lambda req: httpx.Response(200, json={"shortcode": "abc123", "title": "New", "description": None}))
    body = (await client.patch("/api/share/links/abc123", json={"title": "New"})).json()
    assert body == {"success": True, "link": {"shortcode": "abc123", "title": "New", "description": None}, "error": None}
    req = cloud.requests[0]
    assert req.method == "PATCH" and req.url.path == "/api/shares/abc123"
    assert json.loads(req.content) == {"title": "New"}


async def test_update_link_error_is_friendly(client, monkeypatch):
    _fake_token(monkeypatch)
    Cloud(monkeypatch, lambda req: httpx.Response(404, json={"error": "Share not found"}))
    body = (await client.patch("/api/share/links/abc123", json={"title": "x"})).json()
    assert body["success"] is False and body["error"] == "That link no longer exists."


async def test_delete_link(client, monkeypatch):
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch, lambda req: httpx.Response(200, json={"deleted": True, "shortcode": "abc123"}))
    body = (await client.delete("/api/share/links/abc123")).json()
    assert body == {"success": True, "shortcode": "abc123", "error": None}
    assert cloud.requests[0].method == "DELETE"


async def test_delete_link_rejects_odd_shortcodes(client, monkeypatch):
    _fake_token(monkeypatch)
    cloud = Cloud(monkeypatch)
    body = (await client.delete("/api/share/links/a.b")).json()
    assert body["success"] is False and cloud.requests == []


def test_own_title_reads_markdown_sprite_and_package(tmp_path):
    from types import SimpleNamespace

    from routes.share import _own_title

    md = tmp_path / "notes.md"
    md.write_text("---\ntitle: Field notes\n---\n\n# Ignored heading\n")
    assert _own_title(SimpleNamespace(file_path=str(md)), "text") == "Field notes"
    md.write_text("Intro line\n\n# Harbor log\n\nBody")
    assert _own_title(SimpleNamespace(file_path=str(md)), "text") == "Harbor log"

    sprite = tmp_path / "c.stimmasprite.json"
    sprite.write_text('{"type": "sprite", "version": 1, "title": "Courier"}')
    assert _own_title(SimpleNamespace(file_path=str(sprite)), "sprite") == "Courier"

    pkg = tmp_path / "p.stimmapackage"
    pkg.mkdir()
    (pkg / "stimma-package.json").write_text('{"title": "Package"}')
    assert _own_title(SimpleNamespace(file_path=str(pkg)), "package") is None
    (pkg / "stimma-package.json").write_text('{"title": "Harbor delivery"}')
    assert _own_title(SimpleNamespace(file_path=str(pkg)), "package") == "Harbor delivery"

    grid = tmp_path / "g.stimmagrid.json"
    grid.write_text('{"version": 1, "title": "Palette x bloom", "rows": 1, "cols": 1, "cells": []}')
    assert _own_title(SimpleNamespace(file_path=str(grid)), "grid") == "Palette x bloom"

    assert _own_title(SimpleNamespace(file_path=str(tmp_path / "missing.md")), "text") is None
    assert _own_title(SimpleNamespace(file_path=str(md)), "image") is None


async def test_provenance_inputs_without_a_raster_use_the_library_thumbnail(db_session, root, monkeypatch):
    """A markdown or SVG input still gets a picture: rendered, or the cached tile."""
    import share_payloads
    from database import MediaThumbnailCache

    async def no_renderer(*args, **kwargs):
        return None

    monkeypatch.setattr(share_payloads, "rasterize_svg", no_renderer)
    doc = root / "inputs" / "notes.md"
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text("# Notes\n")
    vector = root / "inputs" / "mark.svg"
    vector.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"/>')
    tile = root / "cache" / "tile.png"
    tile.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (32, 32), (10, 200, 180)).save(tile)
    async with db_session() as session:
        md = await _media(session, doc, "md")
        svg = await _media(session, vector, "svg")
        session.add(MediaThumbnailCache(media_id=md.id, cache_path=str(tile)))
        session.add(MediaThumbnailCache(media_id=svg.id, cache_path=str(tile)))
        await session.commit()
        sidecar = await build_public_sidecar(session, parse_provenance({
            "version": 2,
            "steps": [{"tool": "Package", "inputs": [
                {"role": "Member", "ref": {"mediaId": md.id}},
                {"role": "Member", "ref": {"mediaId": svg.id}},
            ]}],
        }))
    inputs = sidecar["steps"][0]["inputs"]
    assert inputs == [{"role": "Member", "thumb": "t0"}, {"role": "Member", "thumb": "t1"}]
    assert all(v.startswith("data:image/webp;base64,") for v in sidecar["thumbnails"].values())


async def test_link_thumbnail_is_proxied_and_cached(client, monkeypatch):
    share_route._THUMB_CACHE.clear()
    cloud = Cloud(monkeypatch, lambda req: httpx.Response(200, content=b"RIFFwebp", headers={"content-type": "image/webp"}))
    first = await client.get("/api/share/links/abc123/thumbnail")
    second = await client.get("/api/share/links/abc123/thumbnail")
    assert first.status_code == 200 and first.content == b"RIFFwebp"
    assert first.headers["content-type"] == "image/webp" and second.content == b"RIFFwebp"
    assert len(cloud.requests) == 1
    assert cloud.requests[0].url.path == "/api/s/abc123/media/thumb.webp"
    assert "authorization" not in {k.lower() for k in cloud.requests[0].headers}

    Cloud(monkeypatch, lambda req: httpx.Response(404, json={"error": "nope"}))
    assert (await client.get("/api/share/links/zzz999/thumbnail")).status_code == 404
    assert (await client.get("/api/share/links/bad..code/thumbnail")).status_code == 404
