"""Trusted frame-accurate assembly with model-independent companion coverage."""
import asyncio
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import shutil
import uuid

from sqlalchemy import select
from database import MediaItem
from media_sidecars import companions_for_media, trim_mapping, write_portable_manifest


async def join_video(sdk, segments, out="joined.mp4"):
    """Trim/concat only: no matching, scaling, blending, retiming or audio mixing."""
    from core.profile_context import get_current_profile
    if not segments:
        raise ValueError("At least one video segment is required")
    output = sdk._resolve_path(out)
    sdk._contain_av_token("ffmpeg", str(output))
    output.parent.mkdir(parents=True, exist_ok=True)
    work = sdk.workspace_dir / ".video-join" / uuid.uuid4().hex
    work.mkdir(parents=True)
    parts, records, files = [], [], []
    dimensions, fps = None, None
    total = 0
    for i, original in enumerate(segments):
        item = dict(original) if isinstance(original, dict) else {"path": original}
        value = item.get("media_id", item.get("path"))
        media_id = value if isinstance(value, int) else getattr(value, "media_id", None)
        value = getattr(value, "path", value)
        media = await sdk.session.get(MediaItem, media_id) if media_id is not None else None
        if media_id is not None and (media is None or media.deleted_at is not None or media.deletion_pending_at is not None):
            raise ValueError("Source media is unavailable")
        if media is not None:
            source = Path(media.file_path)
        else:
            source = sdk._resolve_path(value)
            sdk._contain_av_token("ffmpeg", str(source))
            # Workspace copies are bound by exact render hash, never ancestor lineage.
            digest = hashlib.sha256(await asyncio.to_thread(source.read_bytes)).hexdigest()
            media = await sdk.session.scalar(select(MediaItem).where(
                MediaItem.file_hash == digest, MediaItem.deleted_at.is_(None), MediaItem.deletion_pending_at.is_(None)).order_by(MediaItem.id.desc()).limit(1))
        local = work / f"source_{i}{source.suffix}"
        await asyncio.to_thread(shutil.copyfile, source, local)
        result = await sdk.ffprobe("-v", "error", "-show_streams", "-of", "json", str(local))
        streams = json.loads(result.stdout)["streams"]
        video = next(s for s in streams if s.get("codec_type") == "video")
        rate = Fraction(video["avg_frame_rate"])
        if rate <= 0 or rate != Fraction(video["r_frame_rate"]):
            raise ValueError("State-preserving assembly requires matching constant frame rates")
        size = (video["width"], video["height"])
        if fps is not None and (rate != fps or size != dimensions):
            raise ValueError("State-preserving assembly requires matching frame rates and dimensions")
        fps, dimensions = rate, size
        count = int(video.get("nb_frames") or 0)
        if count <= 0:
            raise ValueError("Exact source frame count is required")
        if any(not isinstance(item.get(k, 0), int) or isinstance(item.get(k, 0), bool) for k in ("trim_head", "trim_tail", "overlap")):
            raise ValueError("Trim and overlap values must be integer frame counts")
        start = item.get("trim_head", 0) + item.get("overlap", 0)
        end = count - item.get("trim_tail", 0)
        if start < 0 or start >= end or end > count:
            raise ValueError("Invalid trim range")
        has_audio = any(s.get("codec_type") == "audio" for s in streams)
        if media is not None:
            for record in await companions_for_media(sdk.session, media.id, get_current_profile()):
                mapped = trim_mapping(record.get("media_mapping"), start, end, fps, offset_frames=total,
                                      preserved_streams=["video", "audio"] if has_audio else ["video"])
                if mapped:
                    records.append({**record, "media_mapping": mapped})
        parts.append({"path": str(local), "trim_head": start, "trim_tail": count-end,
                      "lock": True, "frames": end-start, "has_audio": has_audio})
        files.extend(["-i", str(local)])
        total += end-start
    audio = all(p["has_audio"] for p in parts)
    if any(p["has_audio"] for p in parts) and not audio:
        raise ValueError("Use clips with matching audio presence for state-preserving assembly")
    filters, labels = [], []
    for i, part in enumerate(parts):
        start, end = part["trim_head"], part["trim_head"] + part["frames"]
        filters.append(f"[{i}:v]trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS[v{i}]")
        labels.append(f"[v{i}]")
        if audio:
            filters.append(f"[{i}:a]atrim=start={float(start/fps)}:end={float(end/fps)},asetpts=PTS-STARTPTS[a{i}]")
            labels.append(f"[a{i}]")
    filters.append("".join(labels) + f"concat=n={len(parts)}:v=1:a={int(audio)}[v]" + ("[a]" if audio else ""))
    args = ["-v", "error", "-y", *files, "-filter_complex", ";".join(filters), "-map", "[v]"]
    if audio:
        args += ["-map", "[a]", "-c:a", "aac", "-af", "apad"]
    args += ["-c:v", "libx264", "-crf", "18", "-preset", "fast", "-pix_fmt", "yuv420p",
             "-t", str(float(total/fps)), "-movflags", "+faststart", str(output)]
    await sdk.ffmpeg(*args)
    check = await sdk.ffprobe("-v", "error", "-select_streams", "v:0", "-show_entries", "stream=nb_frames", "-of", "json", str(output))
    actual = int(json.loads(check.stdout)["streams"][0]["nb_frames"])
    if actual != total:
        raise ValueError(f"Assembly frame count mismatch: expected {total}, received {actual}")
    await write_portable_manifest(output, records)
    return {"out": str(output), "frames": total, "fps": float(fps), "segments": parts,
            "companions": len(records), "mode": "preserve_state"}
