"""SVG document serving and export.

Two jobs:

- Serve the sanitized document for rendering. A scanned SVG that came from a
  watched Source was never rewritten (Stimma does not write into Sources), so
  sanitizing on the way out is the only point at which every render path is
  covered regardless of provenance.
- Export. An SVG is the *source* of finished artwork, so the useful outputs are
  not just "the file" — they are raster sizes, embeddable code, and the platform
  icon bundles someone actually needs when a logo becomes an app icon.
"""

import base64
import io
import json
import zipfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger
from database import MediaItem
from core.dependencies import get_db_session
from routes.media_files import get_db_session_by_guid
from utils.http_headers import content_disposition
from utils.svg_doc import (
    SvgParseError,
    intrinsic_size,
    lint,
    prepare_text,
    read_svg_file,
    serialize,
)

log = get_logger(__name__)

router = APIRouter(prefix="/api", tags=["svg"])


# Rendering an SVG needs no network, no scripts, and no plugins. Saying so
# explicitly means a direct navigation to this URL is inert even if the
# sanitizer ever misses something.
SVG_RENDER_HEADERS = {
    "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; img-src data:",
    "X-Content-Type-Options": "nosniff",
    "Access-Control-Allow-Origin": "*",
}


_IOS_ENTRIES = [
    ("iphone", "20x20", "2x", 40), ("iphone", "20x20", "3x", 60),
    ("iphone", "29x29", "2x", 58), ("iphone", "29x29", "3x", 87),
    ("iphone", "40x40", "2x", 80), ("iphone", "40x40", "3x", 120),
    ("iphone", "60x60", "2x", 120), ("iphone", "60x60", "3x", 180),
    ("ipad", "20x20", "1x", 20), ("ipad", "20x20", "2x", 40),
    ("ipad", "29x29", "1x", 29), ("ipad", "29x29", "2x", 58),
    ("ipad", "40x40", "1x", 40), ("ipad", "40x40", "2x", 80),
    ("ipad", "76x76", "2x", 152), ("ipad", "83.5x83.5", "2x", 167),
    ("ios-marketing", "1024x1024", "1x", 1024),
]

# Platform icon bundles ──────────────────────────────────────────────────────
#
# Each target renders the SVG once per size rather than downsampling one large
# raster: crisp small sizes are the whole reason to author an icon as vector.
#
# `safe_area` is the fraction of the canvas the artwork may occupy. Platforms
# disagree about this and getting it wrong is what makes an icon look amateur:
# macOS insets its artwork inside a rounded-rect grid, Android's adaptive icons
# crop aggressively to arbitrary masks, iOS and Windows bleed to the edge.
ICON_TARGETS = {
    "icon-macos": {
        "label": "macOS .icns",
        # The sizes an .icns container actually stores.
        "sizes": [32, 64, 128, 256, 512, 1024],
        "safe_area": 0.82,
        "opaque": False,
    },
    "icon-windows": {
        "label": "Windows .ico",
        "sizes": [16, 24, 32, 48, 64, 128, 256],
        "safe_area": 1.0,
        "opaque": False,
    },
    "icon-ios": {
        "label": "iOS app icon set",
        # Filled in below from _IOS_ENTRIES so the renders and the asset
        # catalog can never drift apart.
        "sizes": [],
        "safe_area": 1.0,
        # iOS rejects alpha in app icons outright.
        "opaque": True,
    },
    "icon-android": {
        "label": "Android launcher icons",
        # Launcher densities + the 432px adaptive foreground canvas + the
        # 512px Play Store listing icon.
        "sizes": [48, 72, 96, 144, 192, 432, 512],
        "safe_area": 0.66,
        "opaque": False,
    },
    "icon-web": {
        "label": "Web favicon set",
        "sizes": [16, 32, 48, 180, 192, 512],
        "safe_area": 1.0,
        "opaque": False,
    },
}

_ANDROID_DENSITIES = [("mdpi", 48), ("hdpi", 72), ("xhdpi", 96), ("xxhdpi", 144), ("xxxhdpi", 192)]

ICON_TARGETS["icon-ios"]["sizes"] = sorted({px for *_rest, px in _IOS_ENTRIES})

MAX_RASTER_DIMENSION = 4096
MAX_PNG_SET_SIZES = 12


class SvgExportOptions(BaseModel):
    format: str = "svg"
    # Raster options: a scale multiplier or an explicit width.
    scale: Optional[float] = None
    width: Optional[int] = None
    # png-set only.
    sizes: Optional[list[int]] = None
    # html only: "inline" | "data-uri" | "symbol"
    variant: str = "inline"
    # Background for opaque targets and flattened rasters.
    background: str = "#ffffff"


async def _load_svg(media_id: int, session: AsyncSession) -> tuple[MediaItem, str]:
    result = await session.execute(
        select(MediaItem).where(MediaItem.id == media_id, MediaItem.ephemeral_run_id.is_(None))
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Asset not found")
    if (item.file_format or "").lower() != "svg":
        raise HTTPException(status_code=400, detail="Not an SVG asset")

    path = Path(item.file_path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Asset file not found on disk")

    try:
        clean, _doc = prepare_text(read_svg_file(path))
    except SvgParseError as e:
        raise HTTPException(status_code=422, detail=f"SVG could not be parsed: {e}")
    return item, clean


def _base_name(item: MediaItem, media_id: int) -> str:
    stem = Path(item.file_path).stem
    if item.original_filename:
        stem = Path(item.original_filename).stem
    return stem or f"svg-{media_id}"


@router.get("/media/{media_id}/svg")
async def get_svg_document(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """Serve the sanitized SVG for rendering."""
    _item, clean = await _load_svg(media_id, session)
    return Response(content=clean, media_type="image/svg+xml", headers=SVG_RENDER_HEADERS)


@router.get("/db/{db_guid}/media/{media_id}/svg")
async def get_svg_document_by_db_guid(
    db_guid: str,
    media_id: int,
    session: AsyncSession = Depends(get_db_session_by_guid),
):
    """Serve the sanitized SVG addressed by db_guid.

    This is the form the viewer uses. An ``<img>`` cannot send the
    ``X-Profile-ID`` (or PIN) header the profile middleware requires, so any URL
    that lands in an image element has to carry its database in the path — the
    same reason the thumbnail and file endpoints have db_guid twins.
    """
    _item, clean = await _load_svg(media_id, session)
    return Response(content=clean, media_type="image/svg+xml", headers=SVG_RENDER_HEADERS)


@router.get("/media/{media_id}/svg-info")
async def get_svg_info(media_id: int, session: AsyncSession = Depends(get_db_session)):
    """Nominal size, node count, ink tone, and portability warnings for the viewer.

    ``ink`` is what the viewer's Auto ground reads: a black mark on a dark
    backdrop is an empty rectangle, and transparency means the document itself
    cannot answer the question.
    """
    _item, clean = await _load_svg(media_id, session)
    from utils.svg_doc import ink_tone, parse_svg

    root = parse_svg(clean)
    width, height = intrinsic_size(root)
    return {
        "width": width,
        "height": height,
        "byte_size": len(clean.encode("utf-8")),
        "node_count": sum(1 for _ in root.iter()),
        "ink": ink_tone(root),
        "warnings": lint(root),
    }


# Rasterization ──────────────────────────────────────────────────────────────

async def _rasterize(
    svg_text: str,
    width: int,
    height: int,
    *,
    safe_area: float = 1.0,
    opaque: bool = False,
    background: str = "#ffffff",
):
    """Render the SVG to a PIL image at exactly ``width`` x ``height``.

    ``safe_area`` insets the artwork inside the canvas, which is what platform
    icon grids require. The inset is applied by rendering smaller and pasting
    centered, so the artwork keeps its own aspect ratio instead of being
    stretched into the box.
    """
    from PIL import Image

    from utils.document_render import (
        LayoutRenderBusy,
        LayoutRenderFailed,
        LayoutRenderUnavailable,
        render_svg_document,
    )

    inner_w = max(1, int(round(width * safe_area)))
    inner_h = max(1, int(round(height * safe_area)))

    try:
        png_bytes = await render_svg_document(
            svg_text,
            inner_w,
            inner_h,
            queue_timeout_s=30.0,
        )
    except (LayoutRenderBusy, LayoutRenderUnavailable) as e:
        raise HTTPException(
            status_code=503,
            detail=f"Local rendering is unavailable: {e}",
            headers={"Retry-After": "2"},
        )
    except LayoutRenderFailed as e:
        raise HTTPException(status_code=500, detail=f"SVG render failed: {e}")

    art = Image.open(io.BytesIO(png_bytes))
    art.load()
    if art.mode != "RGBA":
        art = art.convert("RGBA")
    if art.size != (inner_w, inner_h):
        art = art.resize((inner_w, inner_h), Image.LANCZOS)

    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    canvas.paste(art, ((width - inner_w) // 2, (height - inner_h) // 2), art)

    if opaque:
        flat = Image.new("RGBA", (width, height), background)
        flat.alpha_composite(canvas)
        canvas = flat.convert("RGB")
    return canvas


def _png_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _resolve_raster_size(width: int, height: int, opts: SvgExportOptions) -> tuple[int, int]:
    if opts.width:
        target_w = opts.width
        target_h = max(1, int(round(opts.width * height / width)))
    else:
        scale = opts.scale or 1.0
        target_w = max(1, int(round(width * scale)))
        target_h = max(1, int(round(height * scale)))
    if max(target_w, target_h) > MAX_RASTER_DIMENSION:
        raise HTTPException(
            status_code=400,
            detail=f"Requested raster exceeds {MAX_RASTER_DIMENSION}px on its long side",
        )
    return target_w, target_h


# Embeddable code ────────────────────────────────────────────────────────────

def _embed_code(svg_text: str, variant: str, base_name: str, width: int, height: int) -> str:
    if variant == "data-uri":
        b64 = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
        return (
            f'<img src="data:image/svg+xml;base64,{b64}"\n'
            f'     width="{width}" height="{height}" alt="{base_name}">\n'
        )

    if variant == "symbol":
        import xml.etree.ElementTree as ET

        from utils.svg_doc import SVG_NS, parse_svg

        root = parse_svg(svg_text)
        symbol_id = base_name.replace(" ", "-").lower() or "icon"

        # Rebuild the tree as <svg><symbol>…</symbol></svg> and serialize once, so
        # the namespace is declared on the wrapper instead of on every child.
        sprite = ET.Element(f"{{{SVG_NS}}}svg", {"style": "display:none"})
        symbol = ET.SubElement(sprite, f"{{{SVG_NS}}}symbol", {
            "id": symbol_id,
            "viewBox": root.get("viewBox") or f"0 0 {width} {height}",
        })
        for child in list(root):
            symbol.append(child)

        return (
            "<!-- Sprite: paste once per page -->\n"
            f"{serialize(sprite)}\n\n"
            "<!-- Use: repeat per instance -->\n"
            f'<svg width="{width}" height="{height}"><use href="#{symbol_id}"/></svg>\n'
        )

    return svg_text if svg_text.endswith("\n") else svg_text + "\n"


# Icon bundles ───────────────────────────────────────────────────────────────

async def _render_icon_sizes(svg_text: str, target: dict, background: str) -> dict[int, object]:
    """Render one image per required size. Each size gets its own render pass."""
    images = {}
    for size in target["sizes"]:
        images[size] = await _rasterize(
            svg_text,
            size,
            size,
            safe_area=target["safe_area"],
            opaque=target["opaque"],
            background=background,
        )
    return images


def _build_icns(images: dict[int, object]) -> bytes:
    """Write a .icns container from per-size renders.

    Pillow's ICNS writer is pure Python (it packs PNG streams), so this works on
    every platform — no `iconutil`, no macOS requirement.
    """
    largest = images[max(images)]
    appended = [img.convert("RGBA") for size, img in sorted(images.items()) if size != max(images)]
    buf = io.BytesIO()
    base = largest.convert("RGBA")
    # Pillow's ICNS writer requires a seekable, real file-like object.
    base.save(buf, "ICNS", append_images=appended)
    return buf.getvalue()


def _build_ico(images: dict[int, object]) -> bytes:
    sizes = sorted(images)
    largest = images[max(sizes)].convert("RGBA")
    buf = io.BytesIO()
    largest.save(
        buf,
        "ICO",
        sizes=[(s, s) for s in sizes],
        append_images=[images[s].convert("RGBA") for s in sizes if s != max(sizes)],
    )
    return buf.getvalue()


def _ios_contents_json(name_for: dict[int, str]) -> str:
    images = []
    for idiom, size, scale, px in _IOS_ENTRIES:
        entry = {"idiom": idiom, "size": size, "scale": scale}
        if px in name_for:
            entry["filename"] = name_for[px]
        images.append(entry)
    return json.dumps({"images": images, "info": {"version": 1, "author": "stimma"}}, indent=2)


def _web_manifest(base_name: str) -> str:
    return json.dumps(
        {
            "name": base_name,
            "short_name": base_name,
            "icons": [
                {"src": "/icon-192.png", "sizes": "192x192", "type": "image/png"},
                {"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"},
            ],
        },
        indent=2,
    )


_WEB_SNIPPET = """<link rel="icon" href="/favicon.ico" sizes="any">
<link rel="icon" type="image/png" sizes="32x32" href="/icon-32.png">
<link rel="icon" type="image/png" sizes="16x16" href="/icon-16.png">
<link rel="apple-touch-icon" sizes="180x180" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
"""


async def _build_icon_bundle(
    svg_text: str, fmt: str, base_name: str, background: str
) -> tuple[bytes, str, str]:
    """Return (payload, filename, media_type) for one icon target."""
    target = ICON_TARGETS[fmt]
    images = await _render_icon_sizes(svg_text, target, background)

    if fmt == "icon-macos":
        return _build_icns(images), f"{base_name}.icns", "image/icns"

    if fmt == "icon-windows":
        return _build_ico(images), f"{base_name}.ico", "image/x-icon"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if fmt == "icon-ios":
            name_for = {px: f"icon-{px}.png" for *_rest, px in _IOS_ENTRIES if px in images}
            for px, name in name_for.items():
                zf.writestr(f"AppIcon.appiconset/{name}", _png_bytes(images[px]))
            zf.writestr("AppIcon.appiconset/Contents.json", _ios_contents_json(name_for))

        elif fmt == "icon-android":
            for density, px in _ANDROID_DENSITIES:
                zf.writestr(f"mipmap-{density}/ic_launcher.png", _png_bytes(images[px]))
                # Adaptive icons composite a foreground layer over a background
                # layer; shipping the artwork as the foreground with the safe
                # area already respected is what keeps masks from clipping it.
                zf.writestr(f"mipmap-{density}/ic_launcher_foreground.png", _png_bytes(images[px]))
            zf.writestr("mipmap-anydpi-v26/ic_launcher.xml", (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                '    <background android:drawable="@color/ic_launcher_background"/>\n'
                '    <foreground android:drawable="@mipmap/ic_launcher_foreground"/>\n'
                '</adaptive-icon>\n'
            ))
            zf.writestr("values/ic_launcher_background.xml", (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<resources>\n'
                f'    <color name="ic_launcher_background">{background}</color>\n'
                '</resources>\n'
            ))
            zf.writestr("play-store-icon-512.png", _png_bytes(images[512]))

        elif fmt == "icon-web":
            zf.writestr("favicon.ico", _build_ico({s: images[s] for s in (16, 32, 48)}))
            for px in (16, 32, 192, 512):
                zf.writestr(f"icon-{px}.png", _png_bytes(images[px]))
            zf.writestr("apple-touch-icon.png", _png_bytes(images[180]))
            zf.writestr("site.webmanifest", _web_manifest(base_name))
            zf.writestr("head-snippet.html", _WEB_SNIPPET)

        zf.writestr("README.txt", (
            f"{target['label']} generated by Stimma from {base_name}.svg\n"
            f"Every size is an independent render of the vector source, not a\n"
            f"resample of one raster.\n"
        ))

    return buf.getvalue(), f"{base_name}-{fmt.removeprefix('icon-')}.zip", "application/zip"


# Export ─────────────────────────────────────────────────────────────────────

@router.post("/media/{media_id}/svg-export")
async def export_svg(
    media_id: int,
    request: SvgExportOptions = SvgExportOptions(),
    session: AsyncSession = Depends(get_db_session),
):
    """Export an SVG as vector, raster, embeddable code, or an icon bundle."""
    from utils.svg_doc import parse_svg

    item, svg_text = await _load_svg(media_id, session)
    base_name = _base_name(item, media_id)
    width, height = intrinsic_size(parse_svg(svg_text))
    fmt = request.format.lower()

    def _attachment(payload: bytes, filename: str, media_type: str):
        return StreamingResponse(
            io.BytesIO(payload),
            media_type=media_type,
            headers={
                "Content-Disposition": content_disposition("attachment", filename),
                "Access-Control-Allow-Origin": "*",
            },
        )

    if fmt == "svg":
        text = _optimize(svg_text)
        return _attachment(text.encode("utf-8"), f"{base_name}.svg", "image/svg+xml")

    if fmt == "html":
        source = _optimize(svg_text)
        code = _embed_code(source, request.variant, base_name, width, height)
        # Code is meant to be copied, so return it as text the client can put on
        # the clipboard rather than as a download of a snippet.
        return Response(
            content=code,
            media_type="text/plain; charset=utf-8",
            headers={"Access-Control-Allow-Origin": "*"},
        )

    if fmt == "png":
        target_w, target_h = _resolve_raster_size(width, height, request)
        img = await _rasterize(svg_text, target_w, target_h)
        return _attachment(_png_bytes(img), f"{base_name}-{target_w}x{target_h}.png", "image/png")

    if fmt == "png-set":
        sizes = sorted({s for s in (request.sizes or [16, 32, 64, 128, 256, 512, 1024]) if s > 0})
        if not sizes:
            raise HTTPException(status_code=400, detail="No sizes requested")
        if len(sizes) > MAX_PNG_SET_SIZES:
            raise HTTPException(
                status_code=400, detail=f"At most {MAX_PNG_SET_SIZES} sizes per export"
            )
        if max(sizes) > MAX_RASTER_DIMENSION:
            raise HTTPException(
                status_code=400, detail=f"Sizes must be at most {MAX_RASTER_DIMENSION}px"
            )
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for size in sizes:
                target_h = max(1, int(round(size * height / width)))
                img = await _rasterize(svg_text, size, target_h)
                zf.writestr(f"{base_name}-{size}.png", _png_bytes(img))
        return _attachment(buf.getvalue(), f"{base_name}-png.zip", "application/zip")

    if fmt == "pdf":
        return _attachment(
            _svg_to_pdf(svg_text, width, height), f"{base_name}.pdf", "application/pdf"
        )

    if fmt in ICON_TARGETS:
        payload, filename, media_type = await _build_icon_bundle(
            svg_text, fmt, base_name, request.background
        )
        return _attachment(payload, filename, media_type)

    raise HTTPException(status_code=400, detail=f"Unsupported export format: {request.format}")


def _svg_to_pdf(svg_text: str, width: int, height: int) -> bytes:
    """Embed the SVG in a single PDF page at its native size, vector preserved."""
    try:
        from weasyprint import CSS, HTML
    except ImportError:
        raise HTTPException(status_code=500, detail="WeasyPrint not available")

    b64 = base64.b64encode(svg_text.encode("utf-8")).decode("ascii")
    html = (
        "<html><body>"
        f'<img src="data:image/svg+xml;base64,{b64}" '
        f'style="display:block;width:{width}px;height:{height}px">'
        "</body></html>"
    )
    page_css = CSS(string=f"@page {{ size: {width}px {height}px; margin: 0; }} "
                          "body { margin: 0; padding: 0; }")
    return HTML(string=html).write_pdf(stylesheets=[page_css])


def _optimize(svg_text: str) -> str:
    """Drop editor cruft and collapse whitespace.

    Deliberately conservative: it re-serializes the parsed tree (which already
    discards comments and processing instructions) and trims inter-tag
    whitespace. It does not touch path data — rounding coordinates is a
    judgement call about visual fidelity, not a mechanical win.
    """
    import re

    from utils.svg_doc import parse_svg

    root = parse_svg(svg_text)
    for el in root.iter():
        for attr in list(el.attrib):
            # Inkscape/Illustrator scratch attributes, always namespaced.
            if attr.startswith("{") and "svg" not in attr and "xlink" not in attr:
                del el.attrib[attr]
    out = serialize(root)
    return re.sub(r">\s+<", "><", out).strip()
