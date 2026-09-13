"""Rasterize layout bundles and self-contained SVG using the local browser."""
from __future__ import annotations
import base64
import re
from pathlib import Path
from .local_render import (
    LayoutRenderBusy, LayoutRenderFailed, LayoutRenderUnavailable,
    RENDER_TIMEOUT_S, gather_bundle_assets, render_html,
)

# Public bundle helper ───────────────────────────────────────────────────────

_DATA_W_RE = re.compile(r'data-stimma-width="(\d+)"')
_DATA_H_RE = re.compile(r'data-stimma-height="(\d+|auto)"')


def _dpr_for_target(width: int, height: int | None, target_long_side: int | None) -> float:
    """Choose bounded supersampling for thumbnails and agent vision."""
    if not target_long_side:
        return 2.0
    long_side = max(width, height or width)
    if long_side <= 0:
        return 2.0
    return max(0.5, min(2.0, target_long_side / long_side))


async def render_svg_document(
    svg_text: str,
    width: int,
    height: int,
    *,
    render_timeout_s: float = RENDER_TIMEOUT_S,
    queue_timeout_s: float | None = None,
    target_long_side: int | None = None,
) -> bytes:
    """Render SVG as an image, preserving alpha and standalone font semantics."""
    html = svg_to_html_img(width, height)
    assets = {_SVG_ASSET_NAME: base64.b64encode(svg_text.encode("utf-8")).decode("ascii")}
    return await render_html(
        html,
        width=width,
        height=height,
        dpr=_dpr_for_target(width, height, target_long_side),
        assets=assets,
        render_timeout_s=render_timeout_s,
        queue_timeout_s=queue_timeout_s,
    )


_SVG_ASSET_NAME = "document.svg"


def svg_to_html_img(width: int, height: int) -> str:
    """Minimal HTML canvas holding a single ``<img>`` pointed at the SVG asset."""
    return (
        f'<!DOCTYPE html><html data-stimma-width="{width}" data-stimma-height="{height}">'
        '<head><meta charset="utf-8"><style>'
        'html,body{margin:0;padding:0;background:transparent;}'
        f'body{{width:{width}px;height:{height}px;overflow:hidden;}}'
        f'img{{display:block;width:{width}px;height:{height}px;}}'
        '</style></head>'
        f'<body><img src="{_SVG_ASSET_NAME}"></body></html>'
    )


async def render_layout_bundle(
    bundle_dir: Path,
    *,
    render_timeout_s: float = RENDER_TIMEOUT_S,
    queue_timeout_s: float | None = None,
    target_long_side: int | None = None,
) -> tuple[bytes, int, int]:
    """Render a ``.stimmalayout`` bundle to PNG bytes using the local browser.

    Returns ``(png_bytes, canvas_width, canvas_height)`` where the canvas
    dimensions are what the bundle declares (height is the *measured* height
    when the bundle declared ``auto``, else the declared height).

    ``target_long_side`` caps the render resolution: dpr is chosen so the
    canvas's long side is roughly that many pixels. Pass it for thumbnails and
    agent-vision so we don't pay to rasterize a full 2x canvas we'll only
    downscale anyway.
    """
    bundle_dir = Path(bundle_dir)
    index = bundle_dir / "index.html"
    if not index.exists():
        raise FileNotFoundError(f"layout bundle missing index.html: {bundle_dir}")

    html = index.read_text(encoding="utf-8")

    width = 800
    height: int | None = None
    if (m := _DATA_W_RE.search(html)):
        width = int(m.group(1))
    if (m := _DATA_H_RE.search(html)):
        v = m.group(1)
        height = None if v == "auto" else int(v)

    assets = gather_bundle_assets(bundle_dir)
    png_bytes = await render_html(
        html,
        width=width,
        height=height,
        dpr=_dpr_for_target(width, height, target_long_side),
        assets=assets,
        render_timeout_s=render_timeout_s,
        queue_timeout_s=queue_timeout_s,
    )

    import io
    from PIL import Image
    with Image.open(io.BytesIO(png_bytes)) as image:
        measured_height = round(image.height / _dpr_for_target(width, height, target_long_side))
    return png_bytes, width, height or measured_height
