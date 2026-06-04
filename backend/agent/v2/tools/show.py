"""Display media to the user in chat."""

import json
import shutil
import uuid
from hashlib import sha1
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter

from core.logging import get_logger

log = get_logger(__name__)


@tool(
    name="show",
    description="Display one or more images, videos, or layouts to the user in chat. Use media_id/media_ids for library items, or path/paths for workspace files (including .stimmalayout directories).",
    parameters=[
        ToolParameter(
            name="media_id",
            type="integer",
            description="Media ID from library to display",
            required=False,
        ),
        ToolParameter(
            name="media_ids",
            type="array",
            description="Media IDs from the library to display together in one panel",
            required=False,
            items={"type": "integer"},
        ),
        ToolParameter(
            name="path",
            type="string",
            description="Path to a workspace file to display",
            required=False,
        ),
        ToolParameter(
            name="paths",
            type="array",
            description="Workspace file paths to display together in one panel",
            required=False,
            items={"type": "string"},
        ),
        ToolParameter(
            name="title",
            type="string",
            description="Optional title for the display",
            required=False,
        ),
    ],
    scope="both",
)
async def show(
    media_id: int | None = None,
    media_ids: list[int] | None = None,
    path: str | None = None,
    paths: list[str] | None = None,
    title: str | None = None,
    **kwargs,
) -> str:
    from utils.websocket import ws_manager

    session: AsyncSession = kwargs.get("session")
    chat_id: int = kwargs.get("chat_id")

    if not session:
        return "Error: No database session available"
    normalized_media_ids = _normalize_media_ids(media_id, media_ids)
    normalized_paths = _normalize_paths(path, paths)

    if not normalized_media_ids and not normalized_paths:
        return "Error: Provide media_id/media_ids and/or path/paths"

    # Guard: skip media_ids that were already displayed this turn
    shown: set[int] | None = kwargs.get("_shown_media_ids")
    if shown is not None and normalized_media_ids and not normalized_paths:
        new_ids = [mid for mid in normalized_media_ids if mid not in shown]
        if not new_ids:
            return "These items were already displayed to the user."
        normalized_media_ids = new_ids

    workspace_dir = kwargs.get("workspace_dir")
    rows: list[dict[str, Any]] = []

    # Auto-save workspace paths to library so shown media is always persisted
    session_media_ids = kwargs.get("session_media_ids")
    for item_path in normalized_paths:
        saved_id = await _auto_save_path(item_path, workspace_dir, session, chat_id, session_media_ids)
        if saved_id is not None:
            normalized_media_ids.append(saved_id)
        else:
            # Fallback: display from workspace URL if save fails
            row_or_error = await _build_path_row(item_path, chat_id, workspace_dir)
            if isinstance(row_or_error, str):
                return row_or_error
            rows.append(row_or_error)

    # Look up file_format for each media item (needed for composite types like grids/sets)
    from database import MediaItem
    from sqlalchemy import select
    format_map: dict[int, str] = {}
    if normalized_media_ids:
        result = await session.execute(
            select(MediaItem.id, MediaItem.file_format)
            .where(MediaItem.id.in_(normalized_media_ids))
        )
        format_map = {row.id: row.file_format for row in result.all()}

    for item_media_id in normalized_media_ids:
        output: dict[str, Any] = {"status": "complete", "media_id": item_media_id}
        if item_media_id in format_map:
            output["file_format"] = format_map[item_media_id]
        rows.append({
            "id": f"show_{uuid.uuid4().hex[:8]}",
            "input": {"type": "output_only"},
            "output": output,
        })

    # Track what we displayed so duplicate show calls become no-ops
    if shown is not None:
        shown.update(normalized_media_ids)

    return await _create_display_item(
        session=session,
        chat_id=chat_id,
        rows=rows,
        title=title,
        ws_manager=ws_manager,
    )


def _normalize_media_ids(media_id: int | None, media_ids: list[int] | None) -> list[int]:
    values: list[int] = []
    if media_id is not None:
        values.append(media_id)
    for value in media_ids or []:
        if isinstance(value, int):
            values.append(value)
    return values


def _normalize_paths(path: str | None, paths: list[str] | None) -> list[str]:
    values: list[str] = []
    if path:
        values.append(path)
    for value in paths or []:
        if isinstance(value, str) and value:
            values.append(value)
    return values


async def _build_path_row(path: str, chat_id: int, workspace_dir: str | None) -> dict[str, Any] | str:
    resolved = Path(path)
    if not resolved.is_absolute() and workspace_dir:
        resolved = Path(workspace_dir) / path

    if not resolved.exists():
        return f"Error: File not found: {resolved}"

    filename = resolved.name
    if workspace_dir:
        staged = _stage_for_workspace_url(resolved, Path(workspace_dir))
        if isinstance(staged, str):
            return staged
        filename = staged.name
    workspace_url = f"/api/chats/{chat_id}/workspace/{filename}"

    return {
        "id": f"show_{uuid.uuid4().hex[:8]}",
        "input": {"type": "output_only"},
        "output": {"status": "complete", "workspace_url": workspace_url},
    }


def _stage_for_workspace_url(resolved: Path, workspace_dir: Path) -> Path | str:
    workspace_root = workspace_dir.resolve()
    source = resolved.resolve()

    # Route only supports /workspace/{filename}, so stage anything not already
    # in the workspace root into the root with a collision-safe name.
    if source.parent == workspace_root:
        return source

    target_name = source.name
    target = workspace_root / target_name
    if target.exists():
        try:
            if source.samefile(target):
                return target
        except OSError:
            pass
        digest = sha1(str(source).encode("utf-8")).hexdigest()[:8]
        target = workspace_root / f"{source.stem}_{digest}{source.suffix}"

    try:
        shutil.copy2(source, target)
    except Exception as e:
        log.warning(f"Failed to stage file for show(): {e}")
        return f"Error: Could not prepare file for display: {e}"

    return target


async def _auto_save_path(
    path: str,
    workspace_dir: str | None,
    session: AsyncSession,
    chat_id: int | None = None,
    session_media_ids: list[int] | None = None,
) -> int | None:
    """Save a workspace file to library with lineage. Returns media_id on success, None on failure."""
    from .library import save_workspace_file
    from ..code_runtime import StimmaSDK

    try:
        # Build provenance with lineage from session-level media tracking
        provenance: dict[str, Any] = {"task_type": "agent_edit"}
        source_ids = list(session_media_ids or [])
        if source_ids and chat_id and session:
            sdk = StimmaSDK(
                session=session, chat_id=chat_id,
                workspace_dir=Path(workspace_dir) if workspace_dir else Path("."),
                interrupt_checker=lambda: False,
            )
            provenance = await sdk._build_edit_provenance(source_ids)

        raw = await save_workspace_file(
            session=session,
            path=path,
            workspace_dir=Path(workspace_dir) if workspace_dir else None,
            save_tags=None,
            provenance=provenance,
        )
        if isinstance(raw, str) and not raw.startswith("Error:"):
            return json.loads(raw)["media_id"]
    except Exception as e:
        log.warning(f"[show] Auto-save failed for {path}: {e}")
    return None


async def _create_display_item(session, chat_id, rows, title, ws_manager):
    from database import ChatItem

    display_title = title or (f"Showing {len(rows)} items" if len(rows) > 1 else None)
    display_data = {
        "title": display_title,
        "status": "complete",
        "rows": rows,
    }

    display_item = ChatItem(
        chat_id=chat_id,
        item_type="media_display",
        item_metadata=json.dumps({"display_data": display_data}),
    )
    session.add(display_item)
    await session.commit()

    await ws_manager.broadcast("chat_item_created", {
        "chat_id": chat_id,
        "item": display_item.to_dict(),
    })

    if len(rows) == 1:
        return "Displayed 1 item to user."
    return f"Displayed {len(rows)} items to user."
