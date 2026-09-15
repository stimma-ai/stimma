"""Portable, deterministic sprite recipe inputs: PNG frames plus source.json.

This archive freezes approved pixels and editorial metadata, without workspace
paths, library IDs, or dependencies on an installed engine.
"""
from __future__ import annotations

import io
import json
import math
import re
import zipfile
from pathlib import Path

from PIL import Image

from sprite_export import ExportAnimation, SpriteExportError, SpriteSource

NAME = re.compile(r"[a-z][a-z0-9_-]{0,79}\Z")
MAX_PIXELS = 64 * 1024 * 1024


def validate_source(source: SpriteSource) -> None:
    if not NAME.fullmatch(source.base_name):
        raise SpriteExportError("Sprite name must be a lowercase identifier (letters, digits, - or _)")
    if len(source.anchor) != 2 or any(not math.isfinite(v) or not 0 <= v <= 1 for v in source.anchor):
        raise SpriteExportError("Anchor must be two normalized coordinates between 0 and 1, measured from top-left")
    if not source.animations:
        raise SpriteExportError("Source needs at least one animation or static frame")
    keys, sizes, pixels = set(), set(), 0
    for a in source.animations:
        if not NAME.fullmatch(a.name) or (a.direction is not None and not NAME.fullmatch(a.direction)) or a.key in keys:
            raise SpriteExportError("Animation names/directions must be unique lowercase identifiers")
        keys.add(a.key)
        if not a.frames or len(a.durations_ms) != len(a.frames):
            raise SpriteExportError(f"{a.key}: frame and duration counts must match and be nonempty")
        if not math.isfinite(a.fps) or not 0 < a.fps <= 1000:
            raise SpriteExportError(f"{a.key}: fps must be finite and between 0 and 1000")
        if any(isinstance(d, bool) or not isinstance(d, int) or d <= 0 for d in a.durations_ms):
            raise SpriteExportError(f"{a.key}: durations must be positive integer milliseconds")
        if a.loop not in ("once", "loop", "pingpong") or not 0 <= a.loop_start <= a.loop_end < len(a.frames):
            raise SpriteExportError(f"{a.key}: invalid loop mode or inclusive loop bounds")
        for f in a.frames:
            sizes.add(f.size)
            pixels += f.width * f.height
    if len(sizes) != 1:
        raise SpriteExportError("All moves of one sprite must share a canvas size and registration. Prepare them together; export does not resize poses independently.")
    if pixels > MAX_PIXELS:
        raise SpriteExportError("Sprite source exceeds the 64 megapixel decoded-frame budget; split unrelated actors into separate runs")


def write_source(source: SpriteSource, path: str | Path, *, usage: dict | None = None) -> Path:
    validate_source(source)
    data = {"sprite_source": 1, "name": source.base_name, "title": source.title,
            "anchor": list(source.anchor), "pixelated": source.pixelated,
            "usage": usage or {}, "animations": []}
    files = []
    for a in source.animations:
        names = []
        for i, frame in enumerate(a.frames):
            name = f"frames/{a.key}/{i:04d}.png"
            buf = io.BytesIO()
            frame.convert("RGBA").save(buf, format="PNG")
            files.append((name, buf.getvalue()))
            names.append(name)
        data["animations"].append({"name": a.name, "direction": a.direction,
            "fps": a.fps, "loop": a.loop, "loop_start": a.loop_start, "loop_end": a.loop_end,
            "mirrored_from": a.mirrored_from, "durations_ms": a.durations_ms, "frames": names})
    files.append(("source.json", (json.dumps(data, indent=2, allow_nan=False) + "\n").encode()))
    path = Path(path)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in files:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, payload)
    return path


def read_source(path: str | Path) -> tuple[SpriteSource, dict]:
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
            if len(infos) > 4097 or sum(i.file_size for i in infos) > 256 * 1024 * 1024:
                raise SpriteExportError("Sprite source archive is too large")
            names = [i.filename for i in infos]
            if len(set(names)) != len(names) or any(n.startswith('/') or '\\' in n or '..' in n.split('/') for n in names):
                raise SpriteExportError("Sprite source contains duplicate or unsafe paths")
            data = json.loads(archive.read("source.json"))
            if data.get("sprite_source") != 1:
                raise SpriteExportError("Expected sprite_source version 1")
            animations, pixels = [], 0
            for a in data["animations"]:
                frames = []
                for name in a["frames"]:
                    if not isinstance(name, str) or not name.startswith("frames/") or not name.endswith(".png"):
                        raise SpriteExportError("Frames must reference PNG files inside frames/")
                    with Image.open(io.BytesIO(archive.read(name))) as image:
                        pixels += image.width * image.height
                        if pixels > MAX_PIXELS:
                            raise SpriteExportError("Sprite source exceeds the decoded-frame budget")
                        frames.append(image.convert("RGBA"))
                animations.append(ExportAnimation(name=a["name"], direction=a.get("direction"),
                    fps=float(a["fps"]), loop=a["loop"], loop_start=a["loop_start"], loop_end=a["loop_end"],
                    durations_ms=a["durations_ms"], mirrored_from=a.get("mirrored_from"), frames=frames))
            source = SpriteSource(title=data["title"], base_name=data["name"], anchor=tuple(data["anchor"]),
                                  animations=animations, pixelated=bool(data.get("pixelated", True)))
            validate_source(source)
            usage = data.get("usage", {})
            if not isinstance(usage, dict):
                raise SpriteExportError("usage must be an object containing game-facing notes")
            return source, usage
    except SpriteExportError:
        raise
    except (KeyError, TypeError, ValueError, OSError, zipfile.BadZipFile) as exc:
        raise SpriteExportError(f"Invalid sprite source archive: {exc}") from exc
