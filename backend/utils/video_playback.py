"""Content-addressed, progressively prepared fMP4 playback derivatives.

One encode per rendition keeps AAC priming and timestamps continuous. Publish
each complete fragment atomically while ffmpeg is still encoding the rest.
The same fragments serve both the loop-aware MSE player and native HLS.
"""
from __future__ import annotations

import asyncio
from concurrent.futures import Future, ThreadPoolExecutor
from fractions import Fraction
import json
import math
from pathlib import Path
import re
import struct
import subprocess
import threading
import time

from filelock import FileLock

import app_dirs
from core.logging import get_logger
from utils.mse_loop import _avc_codec_string

VERSION = 1
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="video-playback")
_jobs: dict[str, Future] = {}
_jobs_lock = threading.Lock()
_processes: set[subprocess.Popen] = set()
log = get_logger(__name__)


def needs_streaming(duration: float | None, size: int) -> bool:
    return (duration or 0) > 15 or size >= 5 * 1024 * 1024


def cache_dir(file_hash: str) -> Path:
    if not re.fullmatch(r"[a-fA-F0-9]{64}", file_hash):
        raise ValueError("Invalid video content hash")
    return app_dirs.get_cache_dir() / f"video-playback-v{VERSION}" / file_hash[:2] / file_hash


def _write(path: Path, data: bytes) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(data)
    temporary.replace(path)


def describe(source: Path, file_hash: str) -> dict:
    root = cache_dir(file_hash)
    root.mkdir(parents=True, exist_ok=True)
    with FileLock(str(root / "describe.lock")):
        path = root / "manifest.json"
        if path.exists():
            return json.loads(path.read_text())
        probe = subprocess.run([
            "ffprobe", "-v", "error", "-show_streams", "-show_format",
            "-of", "json", str(source),
        ], check=True, capture_output=True, timeout=30)
        metadata = json.loads(probe.stdout)
        video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
        audio = next((s for s in metadata["streams"] if s["codec_type"] == "audio"), None)
        fps = Fraction(video.get("avg_frame_rate") or "0/1")
        if not 0 < fps <= 120:
            fps = Fraction(30)
        source_duration = float(video.get("duration") or metadata["format"]["duration"])
        if not math.isfinite(source_duration) or source_duration <= 0:
            raise ValueError("Video duration is unavailable")
        frames = math.ceil(source_duration * fps - 0.000001)
        duration = float(frames / fps)
        gop = max(1, round(2 * fps))
        segment_duration = float(gop / fps)
        longest = max(int(video["width"]), int(video["height"]))
        variants = []
        for name, edge, bitrate in (("small", 640, 600_000), ("medium", 1280, 1_800_000), ("large", 1920, 4_500_000)):
            if variants and longest <= variants[-1]["edge"]:
                break
            scale = min(1, edge / longest)
            variants.append({
                "id": name, "edge": edge, "video_bitrate": bitrate,
                "bandwidth": bitrate * 2 + (128_000 if audio else 0),
                "width": max(2, int(int(video["width"]) * scale) // 2 * 2),
                "height": max(2, int(int(video["height"]) * scale) // 2 * 2),
            })
        manifest = {
            "version": VERSION, "streaming": True, "duration": duration,
            "fps": str(fps), "frames": frames, "gop": gop,
            "segment_duration": segment_duration, "segment_count": math.ceil(frames / gop),
            "has_audio": bool(audio), "sample_rate": int((audio or {}).get("sample_rate") or 48000),
            "renditions": variants,
        }
        _write(path, json.dumps(manifest, sort_keys=True).encode())
        return manifest


def _read_box(stream) -> tuple[bytes, bytes] | None:
    header = stream.read(8)
    if not header:
        return None
    if len(header) != 8:
        raise RuntimeError("Truncated MP4 box header")
    size, kind = struct.unpack(">I4s", header)
    if size == 1:
        extended = stream.read(8)
        if len(extended) != 8:
            raise RuntimeError("Truncated extended MP4 box header")
        header += extended
        size = struct.unpack(">Q", extended)[0]
    if size < len(header) or size > 32 * 1024 * 1024:
        raise RuntimeError("Invalid playback MP4 box size")
    payload = stream.read(size - len(header))
    if len(payload) != size - len(header):
        raise RuntimeError("Truncated playback MP4 box")
    return kind, header + payload


def _encode(source: Path, root: Path, manifest: dict, rendition: dict) -> None:
    target = root / rendition["id"]
    target.mkdir(exist_ok=True)
    # Ingestion runs in a separate process. Its prewarming and an interactive
    # request must share one encoder and never overwrite a published fragment.
    with FileLock(str(target / "encode.lock")):
        complete = target / "complete"
        if (root / "cancelled").exists():
            raise RuntimeError("Video preparation cancelled")
        if complete.exists():
            return
        duration = manifest["duration"]
        bitrate = rendition["video_bitrate"]
        edge = rendition["edge"]
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
            "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
            "-vf", f"fps={manifest['fps']},scale=w='min(iw,{edge})':h='min(ih,{edge})':force_original_aspect_ratio=decrease:force_divisible_by=2,tpad=stop_mode=clone:stop_duration=1",
            "-c:v", "libx264", "-threads", "2", "-preset", "veryfast", "-crf", "21",
            "-pix_fmt", "yuv420p", "-profile:v", "high", "-level:v", "4.2", "-bf", "0",
            "-g", str(manifest["gop"]), "-keyint_min", str(manifest["gop"]), "-sc_threshold", "0",
            "-maxrate", str(bitrate), "-bufsize", str(bitrate * 2),
        ]
        if manifest["has_audio"]:
            trimmed = max(0.001, duration - 1024 / manifest["sample_rate"])
            command += [
                "-af", f"apad=whole_dur={trimmed:.9f},atrim=duration={trimmed:.9f},asetpts=PTS-STARTPTS",
                "-c:a", "aac", "-ar", str(manifest["sample_rate"]), "-b:a", "128k",
            ]
        command += [
            "-t", f"{duration:.9f}", "-movflags", "frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets",
            "-f", "mp4", "pipe:1",
        ]
        # stderr goes to disk, never a pipe that can deadlock the encoder.
        with (target / "error.log").open("wb") as errors:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=errors)
            with _jobs_lock:
                _processes.add(process)
            watchdog = threading.Timer(max(120, duration * 4), process.kill)
            watchdog.start()
            try:
                init = bytearray()
                fragment = bytearray()
                index = 0
                while box := _read_box(process.stdout):
                    if (root / "cancelled").exists():
                        raise RuntimeError("Video preparation cancelled")
                    kind, data = box
                    if kind in {b"ftyp", b"moov"}:
                        init.extend(data)
                        if kind == b"moov":
                            _write(target / "init.mp4", init)
                    elif kind == b"moof":
                        fragment = bytearray(data)
                    elif kind == b"mdat":
                        fragment.extend(data)
                        _write(target / f"segment-{index}.m4s", fragment)
                        index += 1
                if process.wait() != 0 or index != manifest["segment_count"]:
                    raise RuntimeError("Video playback preparation failed")
                _write(complete, b"ok")
            finally:
                watchdog.cancel()
                if process.poll() is None:
                    process.kill()
                process.wait()
                process.stdout.close()
                with _jobs_lock:
                    _processes.discard(process)


def _submit(key: str, fn, *args) -> Future:
    with _jobs_lock:
        existing = _jobs.get(key)
        if existing and not existing.done():
            return existing
        # Completed futures retain exceptions/arguments; keep only live work.
        for old in [key for key, job in _jobs.items() if job.done()]:
            del _jobs[old]
        job = _pool.submit(fn, *args)
        _jobs[key] = job
        return job


async def register_cache(session, media_id: int, file_hash: str, manifest: dict) -> None:
    from database import MediaThumbnailCache
    from sqlalchemy import select
    from sqlalchemy.dialects.sqlite import insert
    root = cache_dir(file_hash)
    if await session.scalar(select(MediaThumbnailCache.media_id).where(
        MediaThumbnailCache.media_id == media_id,
        MediaThumbnailCache.cache_path == str(root / "manifest.json"),
    )) is not None:
        return
    paths = [root / "manifest.json", root / "describe.lock"]
    for rendition in manifest["renditions"]:
        target = root / rendition["id"]
        paths += [target / name for name in ("init.mp4", "init.mp4.tmp", "complete", "complete.tmp", "error.log", "encode.lock")]
        for i in range(manifest["segment_count"]):
            paths += [target / f"segment-{i}.m4s", target / f"segment-{i}.m4s.tmp"]
    for start in range(0, len(paths), 200):
        await session.execute(insert(MediaThumbnailCache).values([
            {"media_id": media_id, "cache_path": str(path)} for path in paths[start:start + 200]
        ]).on_conflict_do_nothing())


def warm(source: Path, file_hash: str, manifest: dict) -> None:
    # Never build an unbounded import queue or occupy both interactive slots.
    with _jobs_lock:
        if any(not job.done() for job in _jobs.values()):
            return
    rendition = manifest["renditions"][0]
    job = _submit(f"{file_hash}:{rendition['id']}", _encode, source, cache_dir(file_hash), manifest, rendition)
    def finished(future):
        if not future.cancelled() and future.exception():
            log.debug("Video prewarming deferred", error=type(future.exception()).__name__)
    job.add_done_callback(finished)


async def prewarm(session, item) -> None:
    if item.file_format.lower() not in {"mp4", "webm", "mov", "avi", "mkv", "ogg"}:
        return
    if not needs_streaming(item.duration, item.file_size or 0):
        return
    with _jobs_lock:
        if any(not job.done() for job in _jobs.values()):
            return
    try:
        source = Path(item.file_path)
        manifest = await asyncio.to_thread(describe, source, item.file_hash)
        await register_cache(session, item.id, item.file_hash, manifest)
        await session.commit()
        warm(source, item.file_hash, manifest)
    except Exception as exc:
        # Playback preparation is optional work, never an ingestion failure.
        await session.rollback()
        log.debug("Video prewarming deferred", error=type(exc).__name__)


def stop(file_hash: str) -> None:
    """Stop cross-process writers before permanent deletion unlinks the cache."""
    root = cache_dir(file_hash)
    if not root.exists():
        return
    (root / "cancelled").touch()
    for target in root.iterdir():
        if target.is_dir():
            with FileLock(str(target / "encode.lock"), timeout=15):
                pass


def shutdown() -> None:
    with _jobs_lock:
        for process in _processes:
            if process.poll() is None:
                process.kill()
    _pool.shutdown(wait=False, cancel_futures=True)


async def part(source: Path, file_hash: str, rendition_id: str, filename: str) -> Path:
    manifest = await asyncio.to_thread(describe, source, file_hash)
    rendition = next((r for r in manifest["renditions"] if r["id"] == rendition_id), None)
    match = re.fullmatch(r"segment-(\d+)\.m4s", filename)
    if not rendition or not (filename == "init.mp4" or match and int(match[1]) < manifest["segment_count"]):
        raise ValueError("Unknown video playback segment")
    root = cache_dir(file_hash)
    path = root / rendition_id / filename
    if path.exists():
        return path
    job = _submit(f"{file_hash}:{rendition_id}", _encode, source, root, manifest, rendition)
    # First fragments are available before a long encode completes. Requests
    # don't hold a DB transaction open while awaiting the rest of the rendition.
    started = time.monotonic()
    while not path.exists():
        if job.done():
            job.result()
            raise RuntimeError("Video playback segment is unavailable")
        if time.monotonic() - started > max(120, manifest["duration"] * 4):
            raise RuntimeError("Video playback preparation exceeded its budget")
        await asyncio.sleep(0.05)
    return path


def mime_type(init: bytes, has_audio: bool) -> str:
    codecs = [_avc_codec_string(init)]
    if has_audio:
        codecs.append("mp4a.40.2")
    return f'video/mp4; codecs="{", ".join(codecs)}"'


def playlist(manifest: dict, query: str = "") -> str:
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-PLAYLIST-TYPE:VOD",
             f"#EXT-X-TARGETDURATION:{math.ceil(manifest['segment_duration'])}",
             "#EXT-X-MEDIA-SEQUENCE:0", "#EXT-X-INDEPENDENT-SEGMENTS",
             f'#EXT-X-MAP:URI="init.mp4{query}"']
    for index in range(manifest["segment_count"]):
        duration = min(manifest["segment_duration"], manifest["duration"] - index * manifest["segment_duration"])
        lines += [f"#EXTINF:{duration:.9f},", f"segment-{index}.m4s{query}"]
    return "\n".join([*lines, "#EXT-X-ENDLIST", ""])
