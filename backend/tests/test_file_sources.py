"""Lineage recorded at the SDK boundary: stimma.ffmpeg and join_video note which
library media went into each file, and library save inherits them."""
import hashlib
import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import select

from database import MediaItem, MediaLineage
from storage_service import stage_managed_media
from tests.helpers.media import create_media_item

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="ffmpeg and ffprobe required"),
]


def _sdk(session, workspace):
    from agent.v2.code_runtime import StimmaSDK
    return StimmaSDK(session=session, chat_id=None, workspace_dir=workspace,
                     project_workspace_dir=None, interrupt_checker=None)


async def _clip(sdk, session, name, *, color="red", frames=24, library=True):
    """A small video clip in the workspace; with library=True also a library item."""
    path = sdk.workspace_dir / name
    await sdk.ffmpeg("-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:size=64x48:rate=24",
                     "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", name)
    if not library:
        return path, None
    stored = sdk.workspace_dir / "library" / name
    stored.parent.mkdir(exist_ok=True)
    shutil.copyfile(path, stored)
    media = await create_media_item(session, file_path=stored, file_format="mp4",
                                    file_hash=hashlib.sha256(stored.read_bytes()).hexdigest())
    await stage_managed_media(session, media=media, profile_id="default", remove_source=False)
    await session.commit()
    return path, media.id


async def _lineage(session, media_id):
    rows = (await session.execute(select(MediaLineage).where(MediaLineage.media_id == media_id)
                                  .order_by(MediaLineage.source_order))).scalars().all()
    return [(r.source_media_id, r.relationship_type) for r in rows]


async def _meta(session, media_id):
    return json.loads((await session.get(MediaItem, media_id)).generation_metadata)


async def test_concat_of_library_clips_saves_as_a_stitch_of_those_clips(db_session, tmp_path):
    from agent.v2.tools.library import library
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        _, a = await _clip(sdk, session, "a.mp4", color="red")
        _, b = await _clip(sdk, session, "b.mp4", color="blue")
        (tmp_path / "list.txt").write_text("file 'a.mp4'\nfile 'b.mp4'\n")
        await sdk.ffmpeg("-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt", "-c", "copy", "long.mp4")

        # The agent's library tool, not the SDK: both read the same record.
        saved = json.loads(await library(action="save", path="long.mp4", session=session, workspace_dir=tmp_path))
        assert await _lineage(session, saved["media_id"]) == [(a, "derived"), (b, "derived")]
        meta = await _meta(session, saved["media_id"])
        assert meta["task_type"] == "video-stitch"
        assert [(s["media_id"], s["role"]) for s in meta["source_inputs"]] == [(a, "clip"), (b, "clip")]
        assert meta.get("tool_id") is None


async def test_chains_flatten_to_the_library_clips(db_session, tmp_path):
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        _, a = await _clip(sdk, session, "a.mp4", color="red")
        _, b = await _clip(sdk, session, "b.mp4", color="green")
        (tmp_path / "work").mkdir()
        await sdk.ffmpeg("-v", "error", "-y", "-i", "a.mp4", "-i", "b.mp4", "-filter_complex",
                         "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]", "work/joined.mp4")
        # B is made from A, which never went to the library.
        await sdk.ffmpeg("-v", "error", "-y", "-i", "work/joined.mp4", "-vf", "hflip", "final.mp4")
        saved = await sdk.library.save("final.mp4")
        assert await _lineage(session, saved["media_id"]) == [(a, "derived"), (b, "derived")]


async def test_declared_sources_add_to_recorded_ones(db_session, tmp_path):
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        _, a = await _clip(sdk, session, "a.mp4")
        logo_path = tmp_path / "logo.png"
        from PIL import Image
        Image.new("RGB", (8, 8), "white").save(logo_path)
        logo = await create_media_item(session, file_path=logo_path, file_format="png")
        await session.commit()
        await sdk.ffmpeg("-v", "error", "-y", "-i", "a.mp4", "-vf", "negate", "edit.mp4")
        saved = await sdk.library.save("edit.mp4", sources=[logo.id])
        assert await _lineage(session, saved["media_id"]) == [(logo.id, "derived"), (a, "derived")]
        # Two sources and no word on which it is a version of: made of both.
        meta = await _meta(session, saved["media_id"])
        assert meta["task_type"] == "agent_compose"
        assert meta["lineage_trace"] == []
        based = await sdk.library.save("edit.mp4", sources=[logo.id], based_on=a)
        assert await _lineage(session, based["media_id"]) == [(a, "derived"), (logo.id, "derived")]
        assert (await _meta(session, based["media_id"]))["task_type"] == "agent_edit"
        with pytest.raises(RuntimeError, match="not found"):
            await sdk.library.save("edit.mp4", sources=[999999])


async def test_files_without_library_inputs_save_as_plain_files(db_session, tmp_path):
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        await _clip(sdk, session, "fresh.mp4", color="yellow", frames=17, library=False)
        await sdk.ffmpeg("-v", "error", "-y", "-i", "fresh.mp4", "-vf", "hflip", "out.mp4")
        saved = await sdk.library.save("out.mp4")
        assert await _lineage(session, saved["media_id"]) == []
        assert (await _meta(session, saved["media_id"]))["task_type"] == "code"


async def test_join_video_output_lists_its_clips(db_session, tmp_path):
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        _, a = await _clip(sdk, session, "a.mp4", color="red")
        _, b = await _clip(sdk, session, "b.mp4", color="blue")
        report = await sdk.join_video([{"media_id": a}, {"path": "b.mp4", "overlap": 4}], out="joined.mp4")
        saved = await sdk.library.save(report["out"])
        assert await _lineage(session, saved["media_id"]) == [(a, "derived"), (b, "derived")]


def test_ffmpeg_inputs_reads_lists_protocols_and_sequences(tmp_path):
    from agent.v2.file_sources import FfmpegTrace, ffmpeg_inputs
    (tmp_path / "x.mp4").write_bytes(b"x")
    (tmp_path / "frames").mkdir()
    for i in range(3):
        (tmp_path / "frames" / f"{i:04d}.png").write_bytes(bytes([i]))
    (tmp_path / "clips.txt").write_text("ffconcat version 1.0\nfile 'x.mp4'\nfile \"sub/y.mp4\"\n")
    got = ffmpeg_inputs(["-f", "concat", "-i", "clips.txt", "-i", "concat:x.mp4|z.ts",
                         "-i", "frames/%04d.png", "-i", "anullsrc", "out.mp4"], tmp_path)
    assert [p.relative_to(tmp_path).as_posix() for p in got] == [
        "x.mp4", "sub/y.mp4", "x.mp4", "z.ts", "frames/0000.png", "frames/0001.png", "frames/0002.png", "anullsrc"]
    trace = FfmpegTrace(["-i", "x.mp4", "-vf", "scale=64:-2", "-c:v", "libx264", "out.mp4"], tmp_path)
    (tmp_path / "out.mp4").write_bytes(b"new")
    assert trace.outputs() == [tmp_path / "out.mp4"]


async def test_a_clip_loaded_with_library_get_is_its_library_item(db_session, tmp_path):
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        path, clip = await _clip(sdk, session, "teal.mp4", color="teal", frames=13)
        path.unlink()
        record = await sdk.library.get(clip)
        await sdk.ffmpeg("-v", "error", "-y", "-i", Path(record.path).name, "-vf", "vflip", "flipped.mp4")
        saved = await sdk.library.save("flipped.mp4")
        assert await _lineage(session, saved["media_id"]) == [(clip, "derived")]
        assert [s["role"] for s in (await _meta(session, saved["media_id"]))["source_inputs"]] == ["input_video"]


async def test_parallel_ffmpeg_calls_each_record_their_sources(db_session, tmp_path):
    import asyncio
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        clips = [await _clip(sdk, session, f"p{i}.mp4", color=c, frames=11) for i, c in enumerate(["navy", "olive", "maroon"])]
        await asyncio.gather(*(sdk.ffmpeg("-v", "error", "-y", "-i", p.name, "-vf", "hflip", f"q{i}.mp4")
                               for i, (p, _) in enumerate(clips)))
        for i, (_, clip) in enumerate(clips):
            saved = await sdk.library.save(f"q{i}.mp4")
            assert await _lineage(session, saved["media_id"]) == [(clip, "derived")]


async def test_a_file_encoded_from_raw_frames_keeps_the_sources_code_declares(db_session, tmp_path):
    """Raw frames hide the clips from the ffmpeg trace; record_sources names them."""
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        _, a = await _clip(sdk, session, "a.mp4", color="red")
        _, b = await _clip(sdk, session, "b.mp4", color="blue")
        (tmp_path / "frames.rgb").write_bytes(bytes(64 * 48 * 3 * 12))
        await sdk.ffmpeg("-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", "64x48",
                         "-framerate", "24", "-i", "frames.rgb", "-c:v", "libx264", "-pix_fmt", "yuv420p", "out.mp4")
        assert await sdk.record_sources("out.mp4", ["b.mp4", "a.mp4", "b.mp4"]) == [b, a]
        saved = await sdk.library.save("out.mp4")
        assert await _lineage(session, saved["media_id"]) == [(b, "derived"), (a, "derived")]
        assert (await _meta(session, saved["media_id"]))["task_type"] == "video-stitch"
        with pytest.raises(PermissionError):
            await sdk.record_sources("out.mp4", ["../elsewhere.mp4"])
        with pytest.raises(FileNotFoundError):
            await sdk.record_sources("missing.mp4", [a])


def _seamkit():
    """The video-production stimpack's seamkit, from STIMMA_SKILLS_DIR or a sibling checkout."""
    import importlib.util
    import os
    roots = [os.environ.get("STIMMA_SKILLS_DIR"), Path(__file__).resolve().parents[3] / "stimma-skills"]
    for root in filter(None, roots):
        path = Path(root) / "stimma-essentials/skills/video-production/lib/seamkit.py"
        if path.is_file():
            spec = importlib.util.spec_from_file_location("seamkit_lineage_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
    pytest.skip("seamkit (stimma-skills) not available")


async def test_a_seamkit_join_saves_with_its_clips_as_lineage(db_session, tmp_path, monkeypatch):
    seamkit = _seamkit()
    monkeypatch.chdir(tmp_path)  # run_code's cwd is the workspace
    async with db_session() as session:
        sdk = _sdk(session, tmp_path)
        _, a = await _clip(sdk, session, "a.mp4", color="gray")
        _, b = await _clip(sdk, session, "b.mp4", color="silver")
        report = await seamkit.join(sdk, ["a.mp4", "b.mp4"], "take.mp4", repair=False)
        saved = await sdk.library.save(report["out"])
        assert await _lineage(session, saved["media_id"]) == [(a, "derived"), (b, "derived")]
