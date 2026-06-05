"""Backend → UI request/response RPC for HTML layout rendering.

The Python backend hands off ``.stimmalayout`` HTML rasterization to whatever
UI client is connected via the ``/ws`` WebSocket. The UI uses its real browser
engine (WKWebView in Tauri or the user's browser) to render the HTML to a
canvas and ships the PNG bytes back. This avoids both shipping a Chromium and
the broken-CSS-rendering tax of WeasyPrint.

Protocol:
    backend → frontend: ``render_layout_request {request_id, html, width, height, dpr, assets}``
        where ``assets`` is ``{filename: b64_bytes}`` for each bundle image —
        sent separately so the frontend can wrap them in Blob/ObjectURLs
        instead of multi-MB data URIs in the HTML (which choke WebKit's
        foreignObject rendering and produce missing images in the output).
    frontend → backend: ``render_layout_response {request_id, png_b64}`` or
                         ``render_layout_response {request_id, error}``

This module is the coordinator: it generates request IDs, registers awaitable
futures, dispatches over the WS, and resolves them when the response arrives.

If no UI client is connected the call blocks (with timeout) until one appears.
Stimma is a UI-driven app — recipes, agent vision, and thumbnail generation
all assume someone has the app open. When that assumption breaks we fail
loudly rather than silently degrading.
"""
from __future__ import annotations

import asyncio
import base64
import re
import uuid
from pathlib import Path
from typing import Optional

from core.logging import get_logger

from .websocket import ws_manager

log = get_logger(__name__)


# Tunables. These are starting points based on how the agent typically behaves;
# tune from logs once the system has soak time.
WAIT_FOR_CLIENT_TIMEOUT_S = 60.0  # max time to wait for a UI client to appear
RENDER_TIMEOUT_S = 30.0           # max time for a single render once dispatched


_pending: dict[str, asyncio.Future] = {}
_render_slot = asyncio.Semaphore(1)


class LayoutRenderUnavailable(RuntimeError):
    """No UI client connected within timeout to service the render."""


class LayoutRenderBusy(RuntimeError):
    """The UI renderer is already occupied and the caller chose not to queue."""


class LayoutRenderFailed(RuntimeError):
    """The UI client returned an error or timed out mid-render."""


# Asset gathering ────────────────────────────────────────────────────────────

_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}


def _gather_bundle_assets(bundle_dir: Path) -> dict[str, str]:
    """Collect every image file in ``bundle_dir`` keyed by filename, b64 encoded.

    The frontend will wrap each entry in a Blob + ObjectURL and rewrite the
    HTML's ``src=`` and ``url(...)`` refs to the resulting blob URLs before
    injecting into the off-screen iframe. This is far more reliable than
    inlining data URIs into the HTML — multi-MB data URIs in WebKit
    foreignObject rendering produce intermittent missing images.
    """
    assets: dict[str, str] = {}
    for entry in bundle_dir.iterdir():
        if not entry.is_file():
            continue
        if entry.suffix.lower() not in _IMAGE_EXTS:
            continue
        try:
            data = entry.read_bytes()
        except OSError:
            continue
        assets[entry.name] = base64.b64encode(data).decode('ascii')
    return assets


# Request lifecycle ──────────────────────────────────────────────────────────

async def render_layout_via_ui(
    html: str,
    width: int,
    height: int | None,
    dpr: float = 2.0,
    assets: Optional[dict[str, str]] = None,
    wait_for_client_timeout_s: float = WAIT_FOR_CLIENT_TIMEOUT_S,
    render_timeout_s: float = RENDER_TIMEOUT_S,
    queue_timeout_s: float | None = None,
) -> bytes:
    """Ask any connected UI client to rasterize ``html`` and return PNG bytes.

    ``height=None`` means content-measured (the frontend lets the off-screen
    container use ``height: auto`` and reads the resolved height after fonts
    and images settle).

    ``assets`` is an optional ``{filename: b64_bytes}`` map. The frontend wraps
    each entry in a Blob + ObjectURL and rewrites bundle-relative HTML refs.
    """
    acquired = False
    try:
        if queue_timeout_s is None:
            await _render_slot.acquire()
        elif queue_timeout_s <= 0:
            if _render_slot.locked():
                raise LayoutRenderBusy("UI layout renderer is busy")
            await _render_slot.acquire()
        else:
            try:
                await asyncio.wait_for(_render_slot.acquire(), timeout=queue_timeout_s)
            except asyncio.TimeoutError as exc:
                raise LayoutRenderBusy(
                    f"UI layout renderer still busy after {queue_timeout_s:.2f}s"
                ) from exc
        acquired = True

        if not await ws_manager.wait_for_client(timeout=wait_for_client_timeout_s):
            raise LayoutRenderUnavailable(
                f"No UI client connected within {wait_for_client_timeout_s:.0f}s — "
                f"layout rendering requires the Stimma UI to be open."
            )

        request_id = uuid.uuid4().hex
        loop = asyncio.get_running_loop()
        fut: asyncio.Future = loop.create_future()
        _pending[request_id] = fut

        payload = {
            "request_id": request_id,
            "html": html,
            "width": int(width),
            "height": "auto" if height is None else int(height),
            "dpr": float(dpr),
            "assets": assets or {},
        }

        try:
            sent = await ws_manager.send_to_any("render_layout_request", payload)
            if not sent:
                # Client disconnected between wait_for_client and send. One retry.
                if not await ws_manager.wait_for_client(timeout=wait_for_client_timeout_s):
                    raise LayoutRenderUnavailable(
                        "UI client disconnected before render dispatch could complete."
                    )
                sent = await ws_manager.send_to_any("render_layout_request", payload)
                if not sent:
                    raise LayoutRenderUnavailable(
                        "Failed to dispatch render request to any connected UI client."
                    )

            try:
                png_bytes = await asyncio.wait_for(fut, timeout=render_timeout_s)
            except asyncio.TimeoutError as exc:
                raise LayoutRenderFailed(
                    f"UI render timed out after {render_timeout_s:.0f}s "
                    f"(request_id={request_id})"
                ) from exc
            return png_bytes
        finally:
            _pending.pop(request_id, None)
    finally:
        if acquired:
            _render_slot.release()


def complete_request(
    request_id: str,
    png_b64: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    """Resolve a pending render. Called from the realtime WS route on response.

    A response for an unknown ``request_id`` is logged and dropped — that
    happens normally if a previous render timed out and the response arrives
    late, or if multiple clients all answer the same request.
    """
    fut = _pending.get(request_id)
    if fut is None or fut.done():
        log.debug(f"render response for unknown/completed request {request_id}")
        return
    if error:
        fut.set_exception(LayoutRenderFailed(f"UI render error: {error}"))
        return
    if not png_b64:
        fut.set_exception(LayoutRenderFailed("UI render returned empty payload"))
        return
    try:
        png_bytes = base64.b64decode(png_b64, validate=False)
    except Exception as exc:  # noqa: BLE001
        fut.set_exception(LayoutRenderFailed(f"could not decode PNG b64: {exc}"))
        return
    fut.set_result(png_bytes)


# Public bundle helper ───────────────────────────────────────────────────────

_DATA_W_RE = re.compile(r'data-stimma-width="(\d+)"')
_DATA_H_RE = re.compile(r'data-stimma-height="(\d+|auto)"')


async def render_layout_bundle(
    bundle_dir: Path,
    *,
    wait_for_client_timeout_s: float = WAIT_FOR_CLIENT_TIMEOUT_S,
    render_timeout_s: float = RENDER_TIMEOUT_S,
    queue_timeout_s: float | None = None,
) -> tuple[bytes, int, int]:
    """Render a ``.stimmalayout`` bundle to PNG bytes via the UI client.

    Returns ``(png_bytes, canvas_width, canvas_height)`` where the canvas
    dimensions are what the bundle declares (height is the *measured* height
    when the bundle declared ``auto``, else the declared height).
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

    assets = _gather_bundle_assets(bundle_dir)
    png_bytes = await render_layout_via_ui(
        html,
        width=width,
        height=height,
        dpr=2.0,
        assets=assets,
        wait_for_client_timeout_s=wait_for_client_timeout_s,
        render_timeout_s=render_timeout_s,
        queue_timeout_s=queue_timeout_s,
    )

    # The canvas dimensions returned to callers reflect the requested width and
    # the *declared* height (callers who care about measured height for auto
    # layouts can decode the PNG to inspect actual pixels).
    return png_bytes, width, (height or 0)
