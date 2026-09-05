"""Sprite export writers: one canonical input shape, one writer per target.

Every target reads a :class:`SpriteSource` (decoded RGBA frames, timing, loop
mode, direction, anchor) and returns files. Multi-file targets are zipped with a
``manifest.json`` that names the source asset and revision, the anchor, and
per-animation timing — the contract a game repo (or a coding agent working in
it) reads. Names are stable across revisions so regeneration changes pixels,
not code.

Used by the ``/media/{id}/sprite-export`` route and by ``stimma.library.export``
in the agent sandbox, so chat and UI share one implementation.
"""

from __future__ import annotations

import io
import json
import math
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from PIL import Image, ImageSequence
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import MediaItem

log = get_logger(__name__)

MAX_SCALE = 8
MAX_SHEET_SIDE = 8192

# --- targets -----------------------------------------------------------------

EXPORT_TARGETS: dict[str, dict[str, str]] = {
    # Engine-native
    "atlas-hash": {"label": "Atlas (JSON hash)", "group": "engines",
                   "description": "Sheet PNG + TexturePacker JSON hash. Phaser, PixiJS, Cocos Creator."},
    "atlas-array": {"label": "Atlas (JSON array)", "group": "engines",
                    "description": "Sheet PNG + TexturePacker JSON array."},
    "godot": {"label": "Godot", "group": "engines",
              "description": "Sheet PNG + SpriteFrames .tres (Godot 4)."},
    "unity": {"label": "Unity", "group": "engines",
              "description": "Sheet PNG + atlas JSON + editor import script that slices and builds AnimationClips."},
    "unreal": {"label": "Unreal", "group": "engines",
               "description": "Sheet PNG + .paper2dsprites for Paper2D flipbooks."},
    "gamemaker": {"label": "GameMaker", "group": "engines",
                  "description": "One horizontal strip per animation (name_stripN.png)."},
    "rpgmaker": {"label": "RPG Maker", "group": "engines",
                 "description": "$Name.png 3×4 charset. Needs a 4-direction walk."},
    "defold": {"label": "Defold", "group": "engines",
               "description": ".atlas text + per-frame PNGs with fps and playback."},
    "libgdx": {"label": "libGDX", "group": "engines",
               "description": "Sheet PNG + libGDX .atlas pack file."},
    "cocos2d": {"label": "Cocos2d", "group": "engines",
                "description": "Sheet PNG + .plist (TexturePacker cocos2d format)."},
    # Generic
    "frames": {"label": "Frames", "group": "generic",
               "description": "Zip of per-frame images with alpha (PNG, or JPG/WebP on a background)."},
    "grid-sheet": {"label": "Grid sheet", "group": "generic",
                   "description": "Uniform-cell sheet per animation + sidecar JSON."},
    "strips": {"label": "Strips", "group": "generic",
               "description": "One horizontal strip PNG per animation."},
    "stills": {"label": "Stills", "group": "generic",
               "description": "Base cut-out and portrait PNGs at requested sizes."},
    # Preview
    "gif": {"label": "GIF", "group": "preview", "description": "Animated GIF per animation."},
    "webp": {"label": "WebP", "group": "preview", "description": "Animated lossless WebP per animation."},
    "apng": {"label": "APNG", "group": "preview", "description": "Animated PNG per animation."},
    "mp4": {"label": "MP4", "group": "preview",
            "description": "Preview clip per animation composited on a background (needs FFmpeg)."},
}

GROUPS = ("engines", "generic", "preview")


class SpriteExportOptions(BaseModel):
    format: str = "atlas-hash"
    # Subsets: animation names or keys (``run`` or ``run_east``), directions.
    animations: Optional[list[str]] = None
    directions: Optional[list[str]] = None
    # Geometry.
    trim: bool = False
    padding: int = 0
    extrude: int = 0
    scale: int = 1
    power_of_two: bool = False
    max_sheet_size: Optional[int] = None
    # Opaque outputs (jpg frames, mp4) and grid/strip sheets when set.
    background: Optional[str] = None
    # ``frames`` only: png | jpg | webp.
    image_format: str = "png"
    # ``rpgmaker`` only: the walk animation's name.
    walk: str = "walk"
    # ``stills`` only: output heights; default is the source size.
    sizes: Optional[list[int]] = None


class SpriteExportError(ValueError):
    """A writer could not produce the target from this sprite (user-facing message)."""


@dataclass
class ExportAnimation:
    name: str
    direction: Optional[str]
    fps: float
    loop: str
    loop_start: int
    loop_end: int
    frames: list  # PIL RGBA images, uniform size within an animation
    durations_ms: list[int]
    mirrored_from: Optional[str] = None

    @property
    def key(self) -> str:
        return f"{self.name}_{self.direction}" if self.direction else self.name


@dataclass
class SpriteSource:
    title: str
    base_name: str
    anchor: tuple[float, float]
    animations: list[ExportAnimation]
    base_image: Optional[Image.Image] = None
    portrait: Optional[Image.Image] = None
    pixelated: bool = False
    asset_id: Optional[int] = None
    revision_number: Optional[int] = None
    media_id: Optional[int] = None
    production: dict = field(default_factory=dict)


@dataclass
class ExportResult:
    filename: str
    media_type: str
    payload: bytes


# --- loading -----------------------------------------------------------------

def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return slug or "sprite"


def _decode_animation(path: str) -> tuple[list, list[int]]:
    frames, durations = [], []
    with Image.open(path) as im:
        for frame in ImageSequence.Iterator(im):
            frames.append(frame.convert("RGBA"))
            durations.append(int(frame.info.get("duration", 0)) or 0)
    return frames, durations


def _open_rgba(path: Optional[str]) -> Optional[Image.Image]:
    if not path or not Path(path).exists():
        return None
    with Image.open(path) as im:
        return im.convert("RGBA")


def _resolved_path(ref: Any) -> Optional[str]:
    if not isinstance(ref, dict):
        return None
    return (ref.get("resolved") or {}).get("file_path") or None


def source_from_content(content: dict, *, media_id: Optional[int] = None) -> SpriteSource:
    """Build a :class:`SpriteSource` from resolved content (refs carry ``resolved``)."""
    title = content.get("title") or "sprite"
    anchor = content.get("anchor") or {}
    try:
        anchor_xy = (float(anchor.get("x", 0.5)), float(anchor.get("y", 1.0)))
    except (TypeError, ValueError):
        anchor_xy = (0.5, 1.0)
    style = str(content.get("style") or "").lower()
    production = content.get("production") or {}
    preset = str((production.get("style") or {}).get("preset") or "").lower() if isinstance(production, dict) else ""
    pixelated = any(tok in style or tok in preset for tok in ("pixel", "8-bit", "16-bit", "1-bit", "retro"))

    animations: list[ExportAnimation] = []
    missing: list[str] = []
    for entry in content.get("animations") or []:
        if not isinstance(entry, dict):
            continue
        key = f"{entry.get('name')}_{entry.get('direction')}" if entry.get("direction") else str(entry.get("name"))
        path = _resolved_path(entry.get("animation"))
        if not path or not Path(path).exists():
            missing.append(key)
            continue
        from sprite_document import sprite_frame_indices

        frames, embedded = _decode_animation(path)
        if not frames:
            missing.append(key)
            continue
        try:
            frames = [frames[i] for i in sprite_frame_indices(entry, embedded)]
        except ValueError as exc:
            raise SpriteExportError(f"{key}: {exc}") from exc
        fps = float(entry.get("fps") or 12)
        base_ms = max(1, round(1000 / fps))
        overrides = [m.get("duration_ms") if isinstance(m, dict) else None for m in entry.get("frames") or []]
        durations = []
        for i in range(len(frames)):
            override = overrides[i] if i < len(overrides) else None
            durations.append(int(override) if override else base_ms)
        animations.append(
            ExportAnimation(
                name=str(entry.get("name")),
                direction=entry.get("direction"),
                fps=fps,
                loop=entry.get("loop") or "loop",
                loop_start=int(entry.get("loop_start") or 0),
                loop_end=int(entry.get("loop_end") if entry.get("loop_end") is not None else len(frames) - 1),
                frames=frames,
                durations_ms=durations,
                mirrored_from=entry.get("mirrored_from"),
            )
        )
    if missing and not animations:
        raise SpriteExportError(
            "No animation artifacts are available on disk: " + ", ".join(missing)
        )
    return SpriteSource(
        title=title,
        base_name=slugify(title),
        anchor=anchor_xy,
        animations=animations,
        base_image=_open_rgba(_resolved_path(content.get("base_image_nobg")))
        or _open_rgba(_resolved_path(content.get("base_image"))),
        portrait=_open_rgba(_resolved_path(content.get("portrait"))),
        pixelated=pixelated,
        media_id=media_id,
        production=production if isinstance(production, dict) else {},
    )


async def load_sprite_source(session: AsyncSession, media_item: MediaItem) -> SpriteSource:
    """Resolve a sprite media item into a decoded :class:`SpriteSource`."""
    from sqlalchemy import select

    from database import Asset, AssetRevision
    from sprite_document import is_sprite_format, resolved_sprite_content_for_media

    if not is_sprite_format(media_item.file_format):
        raise SpriteExportError("Not a sprite document")
    content = await resolved_sprite_content_for_media(session, media_item)
    if content is None:
        raise SpriteExportError("Sprite document could not be read")
    source = source_from_content(content, media_id=media_item.id)
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media_item.id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    if revision is not None:
        source.asset_id = revision.asset_id
        source.revision_number = revision.revision_number
        asset = await session.get(Asset, revision.asset_id)
        if asset is not None and asset.title:
            source.title = asset.title
            source.base_name = slugify(asset.title)
    return source


# --- geometry helpers --------------------------------------------------------

def _parse_color(value: Optional[str]) -> Optional[tuple[int, int, int]]:
    if not value:
        return None
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise SpriteExportError(f"background must be a hex colour like #202020, got {value!r}")
    try:
        return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]
    except ValueError as exc:
        raise SpriteExportError(f"background must be a hex colour like #202020, got {value!r}") from exc


def _flatten(img: Image.Image, color: Optional[tuple[int, int, int]]) -> Image.Image:
    if color is None:
        return img
    canvas = Image.new("RGBA", img.size, (*color, 255))
    canvas.alpha_composite(img)
    return canvas


def _select(source: SpriteSource, options: SpriteExportOptions) -> list[ExportAnimation]:
    chosen = list(source.animations)
    if options.animations:
        wanted = {a.lower() for a in options.animations}
        chosen = [a for a in chosen if a.key.lower() in wanted or a.name.lower() in wanted]
    if options.directions:
        wanted_dirs = {d.lower() for d in options.directions}
        chosen = [a for a in chosen if (a.direction or "").lower() in wanted_dirs]
    if not chosen:
        raise SpriteExportError("No animations match the requested subset")
    return chosen


def _union_bbox(frames: list) -> tuple[int, int, int, int]:
    box = None
    for f in frames:
        b = f.getbbox()
        if b is None:
            continue
        box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return box or (0, 0, frames[0].width, frames[0].height)


def _prepare(
    animations: list[ExportAnimation], source: SpriteSource, options: SpriteExportOptions
) -> tuple[list[ExportAnimation], tuple[float, float]]:
    """Apply trim and scale. Returns new animations and the (possibly shifted) anchor."""
    if not (1 <= options.scale <= MAX_SCALE):
        raise SpriteExportError(f"scale must be between 1 and {MAX_SCALE}")
    if options.padding < 0 or options.extrude < 0:
        raise SpriteExportError("padding and extrude must be >= 0")

    anchor = source.anchor
    prepared: list[ExportAnimation] = []
    # Trim to the union bbox across *all* selected animations so registration
    # between moves (and the shared anchor) survives.
    crop = None
    if options.trim:
        all_frames = [f for a in animations for f in a.frames]
        if len({f.size for f in all_frames}) == 1:
            left, top, right, bottom = _union_bbox(all_frames)
            w, h = all_frames[0].size
            crop = (left, top, right, bottom)
            ax = (anchor[0] * w - left) / max(1, right - left)
            ay = (anchor[1] * h - top) / max(1, bottom - top)
            anchor = (min(1.0, max(0.0, ax)), min(1.0, max(0.0, ay)))
    resample = Image.Resampling.NEAREST if source.pixelated else Image.Resampling.LANCZOS
    for anim in animations:
        frames = []
        for f in anim.frames:
            g = f.crop(crop) if crop else f
            if options.scale != 1:
                g = g.resize((g.width * options.scale, g.height * options.scale), resample)
            frames.append(g)
        prepared.append(
            ExportAnimation(
                name=anim.name, direction=anim.direction, fps=anim.fps, loop=anim.loop,
                loop_start=anim.loop_start, loop_end=anim.loop_end, frames=frames,
                durations_ms=list(anim.durations_ms), mirrored_from=anim.mirrored_from,
            )
        )
    return prepared, anchor


def _extrude(frame: Image.Image, n: int) -> Image.Image:
    """Grow a frame by ``n`` px on each side, replicating its edge pixels (atlas bleed)."""
    if n <= 0:
        return frame
    w, h = frame.size
    out = Image.new("RGBA", (w + 2 * n, h + 2 * n), (0, 0, 0, 0))
    out.paste(frame, (n, n))
    left = frame.crop((0, 0, 1, h))
    right = frame.crop((w - 1, 0, w, h))
    top = frame.crop((0, 0, w, 1))
    bottom = frame.crop((0, h - 1, w, h))
    for i in range(n):
        out.paste(left, (i, n))
        out.paste(right, (w + n + i, n))
        out.paste(top, (n, i))
        out.paste(bottom, (n, h + n + i))
    tl, tr = frame.getpixel((0, 0)), frame.getpixel((w - 1, 0))
    bl, br = frame.getpixel((0, h - 1)), frame.getpixel((w - 1, h - 1))
    for corner, color in (((0, 0), tl), ((w + n, 0), tr), ((0, h + n), bl), ((w + n, h + n), br)):
        out.paste(Image.new("RGBA", (n, n), color), corner)
    return out


def _next_pow2(n: int) -> int:
    return 1 << max(0, (n - 1).bit_length())


def _check_sheet(sheet: Image.Image, options: SpriteExportOptions) -> Image.Image:
    limit = options.max_sheet_size or MAX_SHEET_SIDE
    if options.power_of_two:
        w, h = _next_pow2(sheet.width), _next_pow2(sheet.height)
        if (w, h) != sheet.size:
            padded = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            padded.paste(sheet, (0, 0))
            sheet = padded
    if sheet.width > limit or sheet.height > limit:
        raise SpriteExportError(
            f"Sheet would be {sheet.width}×{sheet.height}px, over the {limit}px limit. "
            "Export fewer animations, lower the scale, or raise max_sheet_size."
        )
    return sheet


@dataclass
class PackedSheet:
    image: Image.Image
    rects: dict[str, list[dict[str, int]]]  # key -> per-frame {x,y,w,h} (inner region)
    cell: tuple[int, int]


def _pack_rows(animations: list[ExportAnimation], options: SpriteExportOptions) -> PackedSheet:
    """Uniform cells, one row per animation. Rects exclude the extrude bleed."""
    if not animations:
        raise SpriteExportError("no animations to pack")
    ex, pad = options.extrude, options.padding
    cell_w = max(f.width for a in animations for f in a.frames) + 2 * ex
    cell_h = max(f.height for a in animations for f in a.frames) + 2 * ex
    cols = max(len(a.frames) for a in animations)
    rows = len(animations)
    sheet = Image.new(
        "RGBA",
        (cols * cell_w + (cols - 1) * pad, rows * cell_h + (rows - 1) * pad),
        (0, 0, 0, 0),
    )
    rects: dict[str, list[dict[str, int]]] = {}
    for row, anim in enumerate(animations):
        rects[anim.key] = []
        for col, frame in enumerate(anim.frames):
            grown = _extrude(frame, ex)
            x = col * (cell_w + pad) + (cell_w - grown.width) // 2
            y = row * (cell_h + pad) + (cell_h - grown.height)
            sheet.paste(grown, (x, y))
            rects[anim.key].append({"x": x + ex, "y": y + ex, "w": frame.width, "h": frame.height})
    return PackedSheet(_check_sheet(sheet, options), rects, (cell_w, cell_h))


def _pack_grid(frames: list, options: SpriteExportOptions) -> tuple[Image.Image, int, int, int]:
    """Uniform-cell grid, near-square. Returns (sheet, columns, cell_w, cell_h)."""
    pad = options.padding
    cell_w = max(f.width for f in frames)
    cell_h = max(f.height for f in frames)
    cols = math.ceil(math.sqrt(len(frames)))
    rows = math.ceil(len(frames) / cols)
    sheet = Image.new(
        "RGBA", (cols * cell_w + (cols - 1) * pad, rows * cell_h + (rows - 1) * pad), (0, 0, 0, 0)
    )
    for i, frame in enumerate(frames):
        x = (i % cols) * (cell_w + pad) + (cell_w - frame.width) // 2
        y = (i // cols) * (cell_h + pad) + (cell_h - frame.height)
        sheet.paste(frame, (x, y))
    return _check_sheet(sheet, options), cols, cell_w, cell_h


def _png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _strip(anim: ExportAnimation) -> Image.Image:
    cell_w = max(f.width for f in anim.frames)
    cell_h = max(f.height for f in anim.frames)
    strip = Image.new("RGBA", (cell_w * len(anim.frames), cell_h), (0, 0, 0, 0))
    for i, frame in enumerate(anim.frames):
        strip.paste(frame, (i * cell_w + (cell_w - frame.width) // 2, cell_h - frame.height))
    return strip


# --- atlas json --------------------------------------------------------------

def _frame_tags(animations: list[ExportAnimation]) -> list[dict[str, Any]]:
    tags, index = [], 0
    for anim in animations:
        start = index
        index += len(anim.frames)
        tags.append({
            "name": anim.key,
            "from": start,
            "to": index - 1,
            "direction": "pingpong" if anim.loop == "pingpong" else "forward",
            "loop": anim.loop,
            "fps": anim.fps,
        })
    return tags


def _atlas_frames(packed: PackedSheet, animations: list[ExportAnimation], anchor: tuple[float, float]):
    entries = []
    for anim in animations:
        for i, rect in enumerate(packed.rects[anim.key]):
            entries.append({
                "filename": f"{anim.key}/{i}",
                "frame": dict(rect),
                "rotated": False,
                "trimmed": False,
                "spriteSourceSize": {"x": 0, "y": 0, "w": rect["w"], "h": rect["h"]},
                "sourceSize": {"w": rect["w"], "h": rect["h"]},
                "pivot": {"x": round(anchor[0], 4), "y": round(anchor[1], 4)},
                "duration": anim.durations_ms[i],
            })
    return entries


def _atlas_json(
    packed: PackedSheet, animations: list[ExportAnimation], anchor: tuple[float, float],
    sheet_name: str, *, array: bool,
) -> dict[str, Any]:
    entries = _atlas_frames(packed, animations, anchor)
    if array:
        frames: Any = entries
    else:
        frames = {e["filename"]: {k: v for k, v in e.items() if k != "filename"} for e in entries}
    return {
        "frames": frames,
        "meta": {
            "app": "stimma",
            "version": "1.0",
            "image": sheet_name,
            "format": "RGBA8888",
            "size": {"w": packed.image.width, "h": packed.image.height},
            "scale": "1",
            "frameTags": _frame_tags(animations),
        },
    }


# --- writers -----------------------------------------------------------------
# Each returns a list of (filename, bytes).

def _write_atlas(source, animations, anchor, options, *, array: bool):
    packed = _pack_rows(animations, options)
    sheet_name = f"{source.base_name}.png"
    atlas = _atlas_json(packed, animations, anchor, sheet_name, array=array)
    return [(sheet_name, _png(packed.image)), (f"{source.base_name}.json", _json_bytes(atlas))]


def _write_godot(source, animations, anchor, options):
    packed = _pack_rows(animations, options)
    sheet_name = f"{source.base_name}.png"
    total = sum(len(packed.rects[a.key]) for a in animations)
    lines = [
        f'[gd_resource type="SpriteFrames" load_steps={total + 2} format=3]',
        "",
        f'[ext_resource type="Texture2D" path="{sheet_name}" id="1"]',
        "",
    ]
    sub_id = 0
    blocks = []
    for anim in animations:
        entries = []
        base_ms = max(1, round(1000 / anim.fps))
        for rect, duration in zip(packed.rects[anim.key], anim.durations_ms):
            sub_id += 1
            lines += [
                f'[sub_resource type="AtlasTexture" id="AtlasTexture_{sub_id}"]',
                'atlas = ExtResource("1")',
                f'region = Rect2({rect["x"]}, {rect["y"]}, {rect["w"]}, {rect["h"]})',
                "",
            ]
            entries.append(
                '{\n"duration": %s,\n"texture": SubResource("AtlasTexture_%d")\n}'
                % (round(duration / base_ms, 4), sub_id)
            )
        loop = "true" if anim.loop == "loop" else "false"
        blocks.append(
            '{\n"frames": [%s],\n"loop": %s,\n"name": &"%s",\n"speed": %s\n}'
            % (", ".join(entries), loop, anim.key, anim.fps)
        )
    lines += ["[resource]", "animations = [%s]" % ", ".join(blocks), ""]
    return [(sheet_name, _png(packed.image)), (f"{source.base_name}.tres", "\n".join(lines).encode("utf-8"))]


UNITY_IMPORTER = r'''// Stimma sprite importer for Unity (Editor only).
// Place this file under an "Editor" folder. Select the exported sheet PNG (its
// atlas .json must sit beside it) and run Assets > Stimma > Import Sprite Sheet.
// It slices the sheet with the atlas pivots and builds one AnimationClip per
// frame tag. Re-running on a regenerated sheet keeps sprite names stable.
#if UNITY_EDITOR
using System.Collections.Generic;
using System.IO;
using UnityEditor;
using UnityEngine;

public static class StimmaSpriteImporter
{
    [System.Serializable] class Rect2 { public int x, y, w, h; }
    [System.Serializable] class Vec2 { public float x, y; }
    [System.Serializable] class Frame { public string filename; public Rect2 frame; public Vec2 pivot; public int duration; }
    [System.Serializable] class Tag { public string name; public int from, to; public string direction; public string loop; public float fps; }
    [System.Serializable] class Size { public int w, h; }
    [System.Serializable] class Meta { public string image; public Size size; public Tag[] frameTags; }
    [System.Serializable] class Atlas { public Frame[] frames; public Meta meta; }

    [MenuItem("Assets/Stimma/Import Sprite Sheet")]
    static void Import()
    {
        var texture = Selection.activeObject as Texture2D;
        if (texture == null) { Debug.LogError("Select the exported sheet PNG first."); return; }
        var texPath = AssetDatabase.GetAssetPath(texture);
        var jsonPath = Path.ChangeExtension(texPath, ".json");
        if (!File.Exists(jsonPath)) { Debug.LogError("Atlas JSON not found beside " + texPath); return; }
        // The hash-format atlas is converted to the array form JsonUtility can read.
        var atlas = JsonUtility.FromJson<Atlas>(ToArrayForm(File.ReadAllText(jsonPath)));

        var importer = (TextureImporter)AssetImporter.GetAtPath(texPath);
        importer.textureType = TextureImporterType.Sprite;
        importer.spriteImportMode = SpriteImportMode.Multiple;
        importer.filterMode = FilterMode.Point;
        importer.textureCompression = TextureImporterCompression.Uncompressed;
        importer.mipmapEnabled = false;
        var metas = new List<SpriteMetaData>();
        int sheetH = atlas.meta.size.h;
        foreach (var f in atlas.frames)
        {
            var m = new SpriteMetaData();
            m.name = f.filename.Replace('/', '_');
            m.rect = new Rect(f.frame.x, sheetH - f.frame.y - f.frame.h, f.frame.w, f.frame.h);
            m.alignment = (int)SpriteAlignment.Custom;
            m.pivot = new Vector2(f.pivot.x, 1f - f.pivot.y);
            metas.Add(m);
        }
        importer.spritesheet = metas.ToArray();
        EditorUtility.SetDirty(importer);
        importer.SaveAndReimport();

        var sprites = new Dictionary<string, Sprite>();
        foreach (var obj in AssetDatabase.LoadAllAssetsAtPath(texPath))
            if (obj is Sprite s) sprites[s.name] = s;

        var dir = Path.GetDirectoryName(texPath);
        foreach (var tag in atlas.meta.frameTags)
        {
            var clip = new AnimationClip();
            clip.frameRate = tag.fps > 0 ? tag.fps : 12f;
            var binding = new EditorCurveBinding { type = typeof(SpriteRenderer), path = "", propertyName = "m_Sprite" };
            var keys = new List<ObjectReferenceKeyframe>();
            float t = 0f;
            for (int i = tag.from; i <= tag.to; i++)
            {
                var f = atlas.frames[i];
                Sprite sprite;
                if (!sprites.TryGetValue(f.filename.Replace('/', '_'), out sprite)) continue;
                keys.Add(new ObjectReferenceKeyframe { time = t, value = sprite });
                t += Mathf.Max(1, f.duration) / 1000f;
            }
            AnimationUtility.SetObjectReferenceCurve(clip, binding, keys.ToArray());
            var settings = AnimationUtility.GetAnimationClipSettings(clip);
            settings.loopTime = tag.loop == "loop" || tag.loop == "pingpong";
            AnimationUtility.SetAnimationClipSettings(clip, settings);
            var clipPath = Path.Combine(dir, Path.GetFileNameWithoutExtension(texPath) + "_" + tag.name + ".anim");
            AssetDatabase.CreateAsset(clip, clipPath);
        }
        AssetDatabase.SaveAssets();
        Debug.Log("Stimma: imported " + atlas.frames.Length + " frames, " + atlas.meta.frameTags.Length + " clips.");
    }

    // JsonUtility cannot read a dictionary; rewrite {"frames": {"name": {...}}} as an array with "filename".
    static string ToArrayForm(string json)
    {
        int start = json.IndexOf("\"frames\"");
        int brace = json.IndexOf('{', start + 8);
        if (json.IndexOf('[', start + 8) >= 0 && json.IndexOf('[', start + 8) < brace) return json;
        int depth = 0, end = brace;
        for (int i = brace; i < json.Length; i++) { if (json[i] == '{') depth++; else if (json[i] == '}' && --depth == 0) { end = i; break; } }
        string body = json.Substring(brace + 1, end - brace - 1);
        var sb = new System.Text.StringBuilder("[");
        int pos = 0; bool first = true;
        while (true)
        {
            int q1 = body.IndexOf('"', pos); if (q1 < 0) break;
            int q2 = body.IndexOf('"', q1 + 1);
            string name = body.Substring(q1 + 1, q2 - q1 - 1);
            int ob = body.IndexOf('{', q2); int d = 0, oe = ob;
            for (int i = ob; i < body.Length; i++) { if (body[i] == '{') d++; else if (body[i] == '}' && --d == 0) { oe = i; break; } }
            if (!first) sb.Append(','); first = false;
            sb.Append("{\"filename\":\"" + name + "\"," + body.Substring(ob + 1, oe - ob - 1) + "}");
            pos = oe + 1;
        }
        sb.Append("]");
        return json.Substring(0, brace) + sb.ToString() + json.Substring(end + 1);
    }
}
#endif
'''


def _write_unity(source, animations, anchor, options):
    files = _write_atlas(source, animations, anchor, options, array=False)
    files.append(("Editor/StimmaSpriteImporter.cs", UNITY_IMPORTER.encode("utf-8")))
    files.append((
        "README-unity.txt",
        (
            f"1. Copy {source.base_name}.png and {source.base_name}.json into your project's Assets.\n"
            "2. Copy Editor/StimmaSpriteImporter.cs under any Assets/**/Editor folder.\n"
            f"3. Select {source.base_name}.png and run Assets > Stimma > Import Sprite Sheet.\n"
            "The sheet is sliced with the atlas pivots and one AnimationClip is created per animation.\n"
        ).encode("utf-8"),
    ))
    return files


def _write_unreal(source, animations, anchor, options):
    packed = _pack_rows(animations, options)
    sheet_name = f"{source.base_name}.png"
    atlas = _atlas_json(packed, animations, anchor, sheet_name, array=True)
    return [(sheet_name, _png(packed.image)), (f"{source.base_name}.paper2dsprites", _json_bytes(atlas))]


def _write_gamemaker(source, animations, anchor, options):
    return [
        (f"{source.base_name}_{a.key}_strip{len(a.frames)}.png", _png(_strip(a)))
        for a in animations
    ]


def _write_strips(source, animations, anchor, options):
    color = _parse_color(options.background)
    return [(f"{source.base_name}_{a.key}.png", _png(_flatten(_strip(a), color))) for a in animations]


def _write_rpgmaker(source, animations, anchor, options):
    row_order = ("south", "west", "east", "north")
    move = options.walk or "walk"
    by_direction = {a.direction: a for a in animations if a.name == move and a.direction in row_order}
    missing = [d for d in row_order if d not in by_direction]
    if missing:
        present = [d for d in row_order if d in by_direction]
        raise SpriteExportError(
            f"RPG Maker needs the {move!r} animation facing south, west, east and north"
            f" — {len(present)} of 4 present; missing: {', '.join(missing)}"
        )
    cell_w = max(f.width for a in by_direction.values() for f in a.frames)
    cell_h = max(f.height for a in by_direction.values() for f in a.frames)
    sheet = Image.new("RGBA", (cell_w * 3, cell_h * 4), (0, 0, 0, 0))
    for row, direction in enumerate(row_order):
        frames = by_direction[direction].frames
        picks = [frames[min(round(i * (len(frames) - 1) / 2), len(frames) - 1)] for i in range(3)]
        for col, frame in enumerate(picks):
            sheet.paste(frame, (col * cell_w + (cell_w - frame.width) // 2, row * cell_h + (cell_h - frame.height)))
    return [(f"${source.base_name}.png", _png(_check_sheet(sheet, options)))]


def _write_defold(source, animations, anchor, options):
    files = []
    lines = []
    playback = {"loop": "PLAYBACK_LOOP_FORWARD", "once": "PLAYBACK_ONCE_FORWARD", "pingpong": "PLAYBACK_LOOP_PINGPONG"}
    for anim in animations:
        lines.append("animations {")
        lines.append(f'  id: "{anim.key}"')
        for i, frame in enumerate(anim.frames):
            name = f"{source.base_name}/{anim.key}_{i:03d}.png"
            files.append((name, _png(frame)))
            lines.append("  images {")
            lines.append(f'    image: "/{name}"')
            lines.append("  }")
        lines.append(f"  playback: {playback.get(anim.loop, 'PLAYBACK_LOOP_FORWARD')}")
        lines.append(f"  fps: {int(round(anim.fps))}")
        lines.append("  flip_horizontal: 0")
        lines.append("  flip_vertical: 0")
        lines.append("}")
    lines += [f"extrude_borders: {max(1, options.extrude)}", f"inner_padding: {options.padding}", ""]
    files.append((f"{source.base_name}.atlas", "\n".join(lines).encode("utf-8")))
    return files


def _write_libgdx(source, animations, anchor, options):
    packed = _pack_rows(animations, options)
    sheet_name = f"{source.base_name}.png"
    lines = [
        "", sheet_name,
        f"size: {packed.image.width}, {packed.image.height}",
        "format: RGBA8888", "filter: Nearest, Nearest" if source.pixelated else "filter: Linear, Linear",
        "repeat: none",
    ]
    for anim in animations:
        for i, rect in enumerate(packed.rects[anim.key]):
            lines += [
                anim.key,
                "  rotate: false",
                f"  xy: {rect['x']}, {rect['y']}",
                f"  size: {rect['w']}, {rect['h']}",
                f"  orig: {rect['w']}, {rect['h']}",
                "  offset: 0, 0",
                f"  index: {i}",
            ]
    lines.append("")
    return [(sheet_name, _png(packed.image)), (f"{source.base_name}.atlas", "\n".join(lines).encode("utf-8"))]


def _plist_escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write_cocos2d(source, animations, anchor, options):
    packed = _pack_rows(animations, options)
    sheet_name = f"{source.base_name}.png"
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple Computer//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        '<plist version="1.0">', "<dict>", "  <key>frames</key>", "  <dict>",
    ]
    for anim in animations:
        for i, rect in enumerate(packed.rects[anim.key]):
            name = f"{anim.key}_{i:03d}.png"
            out += [
                f"    <key>{_plist_escape(name)}</key>", "    <dict>",
                "      <key>frame</key>",
                f"      <string>{{{{{rect['x']},{rect['y']}}},{{{rect['w']},{rect['h']}}}}}</string>",
                "      <key>offset</key>", "      <string>{0,0}</string>",
                "      <key>rotated</key>", "      <false/>",
                "      <key>sourceColorRect</key>",
                f"      <string>{{{{0,0}},{{{rect['w']},{rect['h']}}}}}</string>",
                "      <key>sourceSize</key>", f"      <string>{{{rect['w']},{rect['h']}}}</string>",
                "    </dict>",
            ]
    out += [
        "  </dict>", "  <key>metadata</key>", "  <dict>",
        "    <key>format</key>", "    <integer>2</integer>",
        "    <key>realTextureFileName</key>", f"    <string>{sheet_name}</string>",
        "    <key>size</key>", f"    <string>{{{packed.image.width},{packed.image.height}}}</string>",
        "    <key>textureFileName</key>", f"    <string>{sheet_name}</string>",
        "  </dict>", "</dict>", "</plist>", "",
    ]
    return [(sheet_name, _png(packed.image)), (f"{source.base_name}.plist", "\n".join(out).encode("utf-8"))]


def _write_frames(source, animations, anchor, options):
    fmt = (options.image_format or "png").lower()
    if fmt not in ("png", "jpg", "jpeg", "webp"):
        raise SpriteExportError("image_format must be png, jpg, or webp")
    color = _parse_color(options.background)
    if fmt in ("jpg", "jpeg") and color is None:
        color = (0, 0, 0)
    files = []
    for anim in animations:
        for i, frame in enumerate(anim.frames):
            img = _flatten(frame, color)
            buf = io.BytesIO()
            if fmt in ("jpg", "jpeg"):
                img.convert("RGB").save(buf, format="JPEG", quality=92)
                ext = "jpg"
            elif fmt == "webp":
                img.save(buf, format="WEBP", lossless=True)
                ext = "webp"
            else:
                img.save(buf, format="PNG", optimize=True)
                ext = "png"
            files.append((f"{anim.key}/frame_{i:03d}.{ext}", buf.getvalue()))
    return files


def _write_grid_sheet(source, animations, anchor, options):
    color = _parse_color(options.background)
    files = []
    for anim in animations:
        sheet, cols, cell_w, cell_h = _pack_grid(anim.frames, options)
        files.append((f"{source.base_name}_{anim.key}.png", _png(_flatten(sheet, color))))
        sidecar = {
            "animation": anim.key,
            "name": anim.name,
            "direction": anim.direction,
            "cell_w": cell_w,
            "cell_h": cell_h,
            "columns": cols,
            "rows": math.ceil(len(anim.frames) / cols),
            "frame_count": len(anim.frames),
            "padding": options.padding,
            "fps": anim.fps,
            "loop": anim.loop,
            "loop_start": anim.loop_start,
            "loop_end": anim.loop_end,
            "durations_ms": anim.durations_ms,
            "anchor": {"x": anchor[0], "y": anchor[1]},
        }
        files.append((f"{source.base_name}_{anim.key}.json", _json_bytes(sidecar)))
    return files


def _write_animated(source, animations, anchor, options, *, kind: str):
    files = []
    for anim in animations:
        buf = io.BytesIO()
        frames = anim.frames
        durations = anim.durations_ms
        loop_count = 0 if anim.loop != "once" else 1
        if kind == "gif":
            converted = []
            for f in frames:
                alpha = f.getchannel("A")
                p = f.convert("RGB").quantize(colors=255, method=Image.Quantize.FASTOCTREE)
                mask = alpha.point(lambda a: 255 if a < 128 else 0)
                p.paste(255, mask=mask)
                converted.append(p)
            converted[0].save(
                buf, format="GIF", save_all=True, append_images=converted[1:],
                duration=durations, loop=loop_count, transparency=255, disposal=2, optimize=False,
            )
            ext = "gif"
        elif kind == "webp":
            frames[0].save(
                buf, format="WEBP", save_all=True, append_images=frames[1:],
                duration=durations, loop=loop_count, lossless=True, quality=100, method=6,
            )
            ext = "webp"
        else:  # apng
            frames[0].save(
                buf, format="PNG", save_all=True, append_images=frames[1:],
                duration=durations, loop=loop_count, disposal=1,
            )
            ext = "png"
        files.append((f"{source.base_name}_{anim.key}.{ext}", buf.getvalue()))
    return files


def _ffmpeg_path() -> Optional[str]:
    return shutil.which("ffmpeg")


def _write_mp4(source, animations, anchor, options):
    ffmpeg = _ffmpeg_path()
    if not ffmpeg:
        raise SpriteExportError("MP4 export needs FFmpeg on PATH")
    color = _parse_color(options.background) or (32, 32, 32)
    files = []
    for anim in animations:
        fps = max(1, int(round(anim.fps)))
        base_ms = 1000 / fps
        # Constant-rate video: repeat frames in proportion to their duration.
        sequence = []
        for frame, ms in zip(anim.frames, anim.durations_ms):
            sequence.extend([frame] * max(1, int(round(ms / base_ms))))
        w = max(f.width for f in anim.frames)
        h = max(f.height for f in anim.frames)
        w += w % 2
        h += h % 2
        with tempfile.TemporaryDirectory(prefix="sprite-mp4-") as tmp:
            for i, frame in enumerate(sequence):
                canvas = Image.new("RGBA", (w, h), (*color, 255))
                canvas.alpha_composite(frame, ((w - frame.width) // 2, h - frame.height))
                canvas.convert("RGB").save(Path(tmp) / f"f_{i:05d}.png")
            out_path = Path(tmp) / "out.mp4"
            cmd = [
                ffmpeg, "-y", "-loglevel", "error", "-framerate", str(fps),
                "-i", str(Path(tmp) / "f_%05d.png"),
                "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path),
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            if proc.returncode != 0:
                raise SpriteExportError(f"FFmpeg failed: {proc.stderr.strip()[-400:]}")
            files.append((f"{source.base_name}_{anim.key}.mp4", out_path.read_bytes()))
    return files


def _write_stills(source, animations, anchor, options):
    images = [("base", source.base_image), ("portrait", source.portrait)]
    images = [(name, img) for name, img in images if img is not None]
    if not images:
        raise SpriteExportError("This sprite has no base image or portrait to export")
    sizes = [s for s in (options.sizes or []) if isinstance(s, int) and s > 0]
    resample = Image.Resampling.NEAREST if source.pixelated else Image.Resampling.LANCZOS
    files = []
    for name, img in images:
        if not sizes:
            files.append((f"{source.base_name}_{name}.png", _png(img)))
            continue
        for height in sizes:
            if height > MAX_SHEET_SIDE:
                raise SpriteExportError(f"sizes must be at most {MAX_SHEET_SIDE}px")
            width = max(1, round(img.width * height / max(1, img.height)))
            files.append((f"{source.base_name}_{name}_{height}.png", _png(img.resize((width, height), resample))))
    return files


WRITERS = {
    "atlas-hash": lambda s, a, an, o: _write_atlas(s, a, an, o, array=False),
    "atlas-array": lambda s, a, an, o: _write_atlas(s, a, an, o, array=True),
    "godot": _write_godot,
    "unity": _write_unity,
    "unreal": _write_unreal,
    "gamemaker": _write_gamemaker,
    "rpgmaker": _write_rpgmaker,
    "defold": _write_defold,
    "libgdx": _write_libgdx,
    "cocos2d": _write_cocos2d,
    "frames": _write_frames,
    "grid-sheet": _write_grid_sheet,
    "strips": _write_strips,
    "stills": _write_stills,
    "gif": lambda s, a, an, o: _write_animated(s, a, an, o, kind="gif"),
    "webp": lambda s, a, an, o: _write_animated(s, a, an, o, kind="webp"),
    "apng": lambda s, a, an, o: _write_animated(s, a, an, o, kind="apng"),
    "mp4": _write_mp4,
}

# Targets that must be delivered as a single file when they produce exactly one.
_SINGLE_FILE_OK = {"rpgmaker", "gif", "webp", "apng", "mp4", "gamemaker", "strips", "stills"}

_MEDIA_TYPES = {
    ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp", ".mp4": "video/mp4",
    ".zip": "application/zip",
}


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, indent=2) + "\n").encode("utf-8")


def build_manifest(
    source: SpriteSource, animations: list[ExportAnimation], anchor: tuple[float, float],
    target: str, files: list[tuple[str, bytes]], options: SpriteExportOptions,
) -> dict[str, Any]:
    return {
        "stimma_sprite_export": 1,
        "title": source.title,
        "name": source.base_name,
        "target": target,
        "source": {
            "media_id": source.media_id,
            "asset_id": source.asset_id,
            "revision_number": source.revision_number,
        },
        "anchor": {"x": round(anchor[0], 4), "y": round(anchor[1], 4)},
        "scale": options.scale,
        "trimmed": options.trim,
        "animations": [
            {
                "name": a.name,
                "direction": a.direction,
                "key": a.key,
                "fps": a.fps,
                "loop": a.loop,
                "loop_start": a.loop_start,
                "loop_end": a.loop_end,
                "frame_count": len(a.frames),
                "frame_size": {"w": max(f.width for f in a.frames), "h": max(f.height for f in a.frames)},
                "durations_ms": a.durations_ms,
                "mirrored_from": a.mirrored_from,
            }
            for a in animations
        ],
        "files": [name for name, _ in files],
    }


def run_sprite_export(source: SpriteSource, options: SpriteExportOptions) -> ExportResult:
    """Run one writer. Returns a single file, or a zip with ``manifest.json``."""
    target = (options.format or "").lower()
    if target not in WRITERS:
        raise SpriteExportError(
            f"Unsupported export format: {options.format!r}. Expected one of: {', '.join(EXPORT_TARGETS)}"
        )
    if target == "stills":
        animations, anchor = [], source.anchor
    else:
        if not source.animations:
            raise SpriteExportError("This sprite has no animations to export")
        animations, anchor = _prepare(_select(source, options), source, options)
    files = WRITERS[target](source, animations, anchor, options)
    if not files:
        raise SpriteExportError("The writer produced no files")
    if len(files) == 1 and target in _SINGLE_FILE_OK:
        name, payload = files[0]
        return ExportResult(name, _MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream"), payload)
    manifest = build_manifest(source, animations, anchor, target, files, options)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, payload in files:
            zf.writestr(name, payload)
        zf.writestr("manifest.json", _json_bytes(manifest))
    return ExportResult(f"{source.base_name}-{target}.zip", "application/zip", buf.getvalue())


def unpack_export(result: ExportResult, out_dir: str | Path) -> list[Path]:
    """Write an export result into a directory; zips are expanded. Returns the paths."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    if result.media_type == "application/zip":
        written = []
        with zipfile.ZipFile(io.BytesIO(result.payload)) as zf:
            for info in zf.infolist():
                target = (out / info.filename).resolve()
                if out.resolve() not in target.parents and target != out.resolve():
                    continue  # never write outside out_dir
                if info.is_dir():
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(info))
                written.append(target)
        return written
    path = out / result.filename
    path.write_bytes(result.payload)
    return [path]
