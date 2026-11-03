"""Exports retain temporary files until the response has been sent."""
import asyncio
import io
import shutil
import subprocess
import zipfile
import tempfile
from pathlib import Path

import pytest
from PIL import Image

from routes.media_files import BulkDownloadRequest, ExportOptions, ExportRequest, bulk_download_media, export_media
from tests.helpers.media import create_media_item


@pytest.mark.asyncio
async def test_converted_exports_survive_send_and_cleanup(client, db_session, tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg is required")
    video = tmp_path / "clip.mp4"
    audio = tmp_path / "tone.wav"
    for path, source, codec in [
        (video, "color=c=red:s=16x16:r=10:d=0.2", "libx264"),
        (audio, "sine=frequency=440:duration=0.2", "pcm_s16le"),
    ]:
        await asyncio.to_thread(
            subprocess.run,
            ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", source,
             "-c", codec, str(path)], check=True, capture_output=True,
        )
    async with db_session() as session:
        items = [await create_media_item(session, file_path=path, file_format=path.suffix[1:])
                 for path in (video, audio)]
        for item, fmt, content_type in zip(items, ("mp4", "mp3"), ("video/mp4", "audio/mpeg")):
            response = await export_media(
                ExportRequest(media_ids=[item.id], options=ExportOptions(format=fmt)), session,
            )
            output = response.path
            assert output.exists(), "converted file was deleted before send"
            result = await client.post("/api/media/export", json={
                "media_ids": [item.id], "options": {"format": fmt},
            })
            assert result.status_code == 200
            assert result.headers["content-type"] == content_type
            assert result.content
            messages = []

            async def send(message):
                messages.append(message)
                assert output.exists(), "cleanup ran before the last body chunk"

            await response({"type": "http", "method": "GET", "headers": []}, None, send)
            assert messages[-1]["more_body"] is False
            assert not output.parent.exists()

        image = tmp_path / "image.png"
        Image.new("RGB", (16, 16), "blue").save(image)
        image_item = await create_media_item(session, file_path=image)
        result = await client.post("/api/media/export", json={"media_ids": [items[0].id, image_item.id]})
        assert result.status_code == 200
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert archive.namelist() == [video.name, image.name]

        for ids in ([items[0].id, image_item.id],):
            result = await client.post("/api/media/download", json={"media_ids": ids})
            assert result.status_code == 200
            with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
                assert archive.read(video.name) == video.read_bytes()
                assert archive.read(image.name) == image.read_bytes()

        bundle = tmp_path / "bundle.stimmalayout"
        bundle.mkdir()
        (bundle / "content.txt").write_text("bundle content")
        bundle_item = await create_media_item(session, file_path=bundle, file_format="stimmalayout")
        result = await client.post("/api/media/download", json={"media_ids": [bundle_item.id]})
        with zipfile.ZipFile(io.BytesIO(result.content)) as archive:
            assert archive.read("bundle.stimmalayout/content.txt") == b"bundle content"
        assert result.headers["access-control-allow-origin"] == "*"

        before = set(Path(tempfile.gettempdir()).glob("stimma-export-*"))
        audio.write_bytes(b"invalid audio")
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            await export_media(ExportRequest(media_ids=[items[1].id]), session)
        assert set(Path(tempfile.gettempdir()).glob("stimma-export-*")) == before


@pytest.mark.asyncio
@pytest.mark.parametrize("interruption", [OSError, asyncio.CancelledError])
@pytest.mark.parametrize("kind", ["video", "audio", "export_zip", "download_zip"])
async def test_temporary_responses_cleanup_after_interrupted_send(db_session, tmp_path, monkeypatch, kind, interruption):
    import routes.media_files as media_files

    def convert(source, options, directory):
        output = Path(directory) / source.name
        output.write_bytes(b"converted payload")
        return output, output.name, "application/octet-stream"

    monkeypatch.setattr(media_files, "_convert_video", convert)
    monkeypatch.setattr(media_files, "_convert_audio", convert)
    async with db_session() as session:
        items = []
        for name in ("video.mp4", "audio.wav"):
            path = tmp_path / name
            path.write_bytes(b"original payload")
            items.append(await create_media_item(session, file_path=path, file_format=path.suffix[1:]))
        if kind == "download_zip":
            response = await bulk_download_media(BulkDownloadRequest(media_ids=[item.id for item in items]), session)
        else:
            ids = [item.id for item in items] if kind == "export_zip" else [items[kind == "audio"].id]
            response = await export_media(ExportRequest(media_ids=ids), session)
        output = Path(response.path)

        async def send(message):
            assert output.exists()
            if message["type"] == "http.response.body":
                raise interruption("interrupted send")

        with pytest.raises(interruption, match="interrupted send"):
            await response({"type": "http", "method": "GET", "headers": []}, None, send)
        assert not output.parent.exists()
