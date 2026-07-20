"""View an image — sends pixels into the LLM context for multimodal reasoning."""

import json
import shutil
from pathlib import Path

from PIL import Image

from ..tools_registry import tool, ToolParameter

from core.logging import get_logger
from ..vision_payload import media_agent_jpeg_cache_path, write_agent_jpeg

log = get_logger(__name__)

MAX_LOW = 512
MAX_HIGH = 1024


def _downscale(img: Image.Image, max_side: int) -> Image.Image:
    """Downscale image so longest side <= max_side, preserving aspect ratio."""
    w, h = img.size
    if max(w, h) <= max_side:
        return img
    scale = max_side / max(w, h)
    return img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)


class _LayoutRenderBusyError(Exception):
    """The UI renderer was busy/unconnected — a transient miss, not a bad layout."""


async def _rasterize_layout(bundle_path: Path, max_side: int) -> Image.Image | None:
    """Rasterize a .stimmalayout bundle to a PIL Image via the UI client.

    Waits a few seconds for the render slot (the agent often calls this right
    after create_layout, while the thumbnail render is still holding the slot)
    and re-raises ``_LayoutRenderBusyError`` on a transient miss so the caller
    can report "renderer busy, retry" rather than "the layout failed" — the
    latter sends the agent off editing perfectly good HTML.
    """
    from routes.media_files import _generate_layout_preview
    from utils.ui_render import LayoutRenderBusy, LayoutRenderUnavailable
    try:
        return await _generate_layout_preview(
            str(bundle_path),
            max_side,
            wait_for_client_timeout_s=2.0,
            queue_timeout_s=5.0,
            render_timeout_s=30.0,
            raise_transient=True,
        )
    except (LayoutRenderBusy, LayoutRenderUnavailable) as e:
        log.debug(f"Layout render slot busy for {bundle_path}: {e}")
        raise _LayoutRenderBusyError(str(e)) from e
    except Exception as e:
        log.warning(f"Failed to rasterize layout {bundle_path}: {e}")
        return None


def _copy_layout_to_workspace(bundle_path: Path, workspace_dir: str) -> str | None:
    """Copy a .stimmalayout bundle into the workspace. Returns the workspace-relative bundle name."""
    ws = Path(workspace_dir)
    dest = ws / bundle_path.name
    if dest.exists():
        # Already in workspace
        if dest.resolve() == bundle_path.resolve():
            return bundle_path.name
        # Different bundle with same name — skip copy, it's already there
        return bundle_path.name
    try:
        shutil.copytree(str(bundle_path), str(dest))
        return bundle_path.name
    except Exception as e:
        log.warning(f"Failed to copy layout to workspace: {e}")
        return None


@tool(
    name="view_image",
    description="View an image or layout — sends its pixels into your context so you can see it. Accepts a media_id (preferred after call_tool or create_layout) or a file path. Works with images and .stimmalayout bundles. For layouts, also copies the bundle into the workspace so you can read/edit the HTML source.",
    parameters=[
        ToolParameter(
            name="media_id",
            type="integer",
            description="Media ID to view (alternative to path)",
            required=False,
        ),
        ToolParameter(
            name="path",
            type="string",
            description="Path to the image file or .stimmalayout bundle (relative to workspace or absolute)",
            required=False,
        ),
        ToolParameter(
            name="detail",
            type="string",
            description="Resolution: 'low' (max 512px) or 'high' (max 1024px)",
            required=False,
            enum=["low", "high"],
        ),
    ],
    scope="both",
)
async def view_image(path: str = None, media_id: int = None, detail: str = "low", **kwargs) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    session = kwargs.get("session")

    # Resolve media_id to a file path via DB lookup
    media_item = None
    if media_id is not None and session:
        from database import MediaItem
        from sqlalchemy import select

        result = await session.execute(
            select(MediaItem).where(MediaItem.id == media_id)
        )
        media_item = result.scalar_one_or_none()
        if (
            not media_item
            or not media_item.file_path
            or media_item.deleted_at is not None
            or media_item.deletion_pending_at is not None
        ):
            return f"Error: Media {media_id} not found"
        resolved = Path(media_item.file_path)
    elif path:
        resolved = Path(path)
        if not resolved.is_absolute() and workspace_dir:
            resolved = Path(workspace_dir) / path
    else:
        return "Error: Provide either path or media_id"

    if not resolved.exists():
        return f"Error: File not found: {resolved}"

    max_side = MAX_HIGH if detail == "high" else MAX_LOW

    # Handle .stimmalayout bundles — rasterize via UI client + copy to workspace
    if resolved.is_dir() and resolved.name.lower().endswith('.stimmalayout'):
        try:
            img = await _rasterize_layout(resolved, max_side)
        except _LayoutRenderBusyError:
            return (
                f"The layout renderer was busy and {resolved.name} did not render "
                f"in time. This is transient — the bundle itself was not reported "
                f"invalid. Wait a moment and view it again."
            )
        if img is None:
            return f"Error: Failed to rasterize layout {resolved.name}"

        # Copy bundle to workspace so the agent can read/edit the HTML
        workspace_bundle = None
        if workspace_dir:
            workspace_bundle = _copy_layout_to_workspace(resolved, workspace_dir)

        # Layouts are mutable, so keep an immutable per-view JPEG snapshot.
        snapshot_path = write_agent_jpeg(img)
        w, h = img.size

        result_data = {
            "__view_image__": True,
            "path": str(snapshot_path),
            "size": [w, h],
            "detail": detail,
            "media_type": "image/jpeg",
        }
        if workspace_bundle:
            result_data["layout_source"] = f"{workspace_bundle}/index.html"

        return json.dumps(result_data)

    cache_path = None
    if media_item is not None:
        cache_path = media_agent_jpeg_cache_path(
            media_id=media_item.id,
            file_hash=media_item.file_hash,
            max_side=max_side,
        )

    try:
        if cache_path is not None and cache_path.exists():
            # Library Media is immutable, so this conversion is valid anywhere
            # the same Media is viewed and across every continuation turn.
            native_w, native_h = media_item.width, media_item.height
            with Image.open(cache_path) as cached:
                w, h = cached.size
            snapshot_path = cache_path
        else:
            from utils.image_ops import open_oriented
            img = open_oriented(resolved)
            native_w, native_h = img.size
            img = _downscale(img, max_side)
            w, h = img.size
            # Workspace paths can change in place, so they receive an immutable
            # per-view snapshot. Library Media uses a persistent content cache.
            snapshot_path = write_agent_jpeg(img, cache_path)
    except Exception as e:
        return f"Error opening image: {e}"

    if media_item is not None and session is not None:
        # Reuse the existing cache locator table so permanent Media deletion
        # also removes this derived vision payload from disk.
        from database import MediaThumbnailCache
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        await session.execute(
            sqlite_insert(MediaThumbnailCache)
            .values(media_id=media_item.id, cache_path=str(snapshot_path))
            .on_conflict_do_nothing(index_elements=["media_id", "cache_path"])
        )

    # Return a JSON marker — the conversation builder will read the file
    # and inject it as multimodal content at message-build time.
    result_data = {
        "__view_image__": True,
        "path": str(snapshot_path),
        "source_path": str(resolved),
        "size": [w, h],
        "native_size": [native_w, native_h],
        "detail": detail,
        "media_type": "image/jpeg",
    }

    # Include face bounding boxes if available (coordinates normalized 0-1)
    if media_item and session and media_item.face_detection_status == "completed":
        from database import Face
        from sqlalchemy import select as sa_select
        face_rows = (await session.execute(
            sa_select(Face).where(Face.media_id == media_id).order_by(Face.confidence.desc())
        )).scalars().all()
        if face_rows:
            result_data["faces"] = [
                {
                    "x": f.bbox_x, "y": f.bbox_y,
                    "width": f.bbox_width, "height": f.bbox_height,
                    "confidence": round(f.confidence, 3),
                }
                for f in face_rows
            ]

    return json.dumps(result_data)
