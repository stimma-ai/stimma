"""Prepare immutable fragmented-MP4 assets for seamless MSE looping."""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
import uuid
from pathlib import Path

from app_dirs import get_cache_dir


MSE_LOOP_CACHE_VERSION = 2
_locks: dict[str, asyncio.Lock] = {}


def _cache_dir(file_hash: str) -> Path:
    return (
        get_cache_dir()
        / f"mse-loop-v{MSE_LOOP_CACHE_VERSION}"
        / file_hash[:2]
        / file_hash[2:4]
        / file_hash
    )


def _probe(source_path: Path) -> tuple[dict, dict | None, float]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v", "error",
            "-show_entries",
            "stream=index,codec_type,codec_name,pix_fmt,duration,sample_rate:format=duration",
            "-of", "json",
            str(source_path),
        ],
        capture_output=True,
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed: {result.stderr.decode(errors='replace')[:500]}")

    payload = json.loads(result.stdout)
    video = next((stream for stream in payload.get("streams", []) if stream.get("codec_type") == "video"), None)
    audio = next((stream for stream in payload.get("streams", []) if stream.get("codec_type") == "audio"), None)
    if not video:
        raise ValueError("Asset does not contain a video track")

    duration_value = video.get("duration") or payload.get("format", {}).get("duration")
    duration = float(duration_value or 0)
    if not duration > 0:
        raise ValueError("Video duration is unavailable")
    return video, audio, duration


def _avc_codec_string(init_bytes: bytes) -> str:
    marker = init_bytes.find(b"avcC")
    if marker < 0 or marker + 8 > len(init_bytes):
        raise RuntimeError("Prepared video is missing an AVC configuration record")
    configuration_version, profile, compatibility, level = init_bytes[marker + 4:marker + 8]
    if configuration_version != 1:
        raise RuntimeError("Unsupported AVC configuration record")
    return f"avc1.{profile:02x}{compatibility:02x}{level:02x}"


def _prepare_sync(source_path: Path, file_hash: str) -> dict:
    video, audio, duration = _probe(source_path)
    target_dir = _cache_dir(file_hash)
    manifest_path = target_dir / "manifest.json"
    init_path = target_dir / "init.mp4"
    segment_path = target_dir / "segment.m4s"

    if manifest_path.exists() and init_path.exists() and segment_path.exists():
        return json.loads(manifest_path.read_text())

    target_dir.parent.mkdir(parents=True, exist_ok=True)
    temp_dir = target_dir.parent / f".{file_hash}-{uuid.uuid4().hex}.tmp"
    temp_dir.mkdir(parents=True, exist_ok=False)
    fragmented_path = temp_dir / "fragmented.mp4"

    try:
        copy_video = video.get("codec_name") == "h264" and video.get("pix_fmt") in {"yuv420p", "yuvj420p"}
        command = [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-i", str(source_path),
            "-map", "0:v:0",
            "-map", "0:a:0?",
        ]
        if copy_video:
            command.extend(["-c:v", "copy"])
        else:
            command.extend([
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-profile:v", "high",
                "-preset", "veryfast",
                "-crf", "18",
            ])

        if audio:
            # AAC-LC adds one 1024-sample encoder-delay frame. Encode one frame
            # less source audio so the fragmented track itself ends exactly at
            # the video boundary. This lets WebKit sequence whole A/V fragments
            # without append-window clipping (which can drop an entire GOP).
            sample_rate = int(audio.get("sample_rate") or 48000)
            encoded_source_duration = max(0.001, duration - (1024 / sample_rate))
            duration_text = f"{encoded_source_duration:.9f}"
            command.extend([
                "-af", f"apad=whole_dur={duration_text},atrim=duration={duration_text},asetpts=PTS-STARTPTS",
                "-c:a", "aac",
                "-profile:a", "aac_low",
                "-b:a", "192k",
            ])

        command.extend([
            "-t", f"{duration:.9f}",
            "-movflags", "frag_keyframe+empty_moov+default_base_moof+negative_cts_offsets",
            "-f", "mp4",
            str(fragmented_path),
        ])

        result = subprocess.run(command, capture_output=True, check=False, timeout=600)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg MSE preparation failed: {result.stderr.decode(errors='replace')[:1000]}")

        payload = fragmented_path.read_bytes()
        moof_marker = payload.find(b"moof")
        moof_start = moof_marker - 4
        if moof_marker < 4 or moof_start <= 0:
            raise RuntimeError("Prepared video does not contain an MP4 movie fragment")

        init_bytes = payload[:moof_start]
        segment_bytes = payload[moof_start:]
        video_codec = _avc_codec_string(init_bytes)
        codecs = [video_codec]
        if audio:
            codecs.append("mp4a.40.2")

        manifest = {
            "version": MSE_LOOP_CACHE_VERSION,
            "duration": duration,
            "mime_type": f'video/mp4; codecs="{", ".join(codecs)}"',
            "has_audio": bool(audio),
            "init_size": len(init_bytes),
            "segment_size": len(segment_bytes),
        }
        (temp_dir / "init.mp4").write_bytes(init_bytes)
        (temp_dir / "segment.m4s").write_bytes(segment_bytes)
        (temp_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True))
        fragmented_path.unlink(missing_ok=True)

        if target_dir.exists():
            shutil.rmtree(target_dir)
        temp_dir.replace(target_dir)
        return manifest
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


async def prepare_mse_loop(source_path: Path, file_hash: str) -> tuple[dict, Path]:
    """Return manifest metadata and the immutable cache directory."""
    lock = _locks.setdefault(file_hash, asyncio.Lock())
    async with lock:
        manifest = await asyncio.to_thread(_prepare_sync, source_path, file_hash)
    return manifest, _cache_dir(file_hash)
