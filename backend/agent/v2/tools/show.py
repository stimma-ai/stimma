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
    description="Display media in chat and declare whether it is an intermediate for inspection or a final committed result. Viewing an intermediate never makes it an Asset; final results do.",
    parameters=[
        ToolParameter(
            name="role",
            type="string",
            description="intermediate for work-in-progress/inspection, final for a committed result",
            enum=["intermediate", "final"],
            required=True,
        ),
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
    role: str,
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
    if role not in {"intermediate", "final"}:
        return "Error: role must be 'intermediate' or 'final'"
    normalized_media_ids = _normalize_media_ids(media_id, media_ids)
    normalized_paths = _normalize_paths(path, paths)

    if not normalized_media_ids and not normalized_paths:
        return "Error: Provide media_id/media_ids and/or path/paths"

    # Guard: skip media_ids that were already displayed this turn
    shown: set[int] | None = kwargs.get("_shown_media_ids")
    if role == "intermediate" and shown is not None and normalized_media_ids and not normalized_paths:
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

    asset_ids = await _apply_show_disposition(
        session=session,
        chat_id=chat_id,
        media_ids=normalized_media_ids,
        role=role,
    )
    asset_by_media = dict(zip(normalized_media_ids, asset_ids))
    for row in rows:
        row_media_id = row.get("output", {}).get("media_id")
        asset_id = asset_by_media.get(row_media_id)
        if asset_id is not None:
            row["output"]["asset_id"] = asset_id

    return await _create_display_item(
        session=session,
        chat_id=chat_id,
        rows=rows,
        title=title,
        role=role,
        media_ids=normalized_media_ids,
        asset_ids=[asset_id for asset_id in asset_ids if asset_id is not None],
        ws_manager=ws_manager,
    )


async def _apply_show_disposition(
    *,
    session: AsyncSession,
    chat_id: int,
    media_ids: list[int],
    role: str,
) -> list[int | None]:
    """Retain intermediates or atomically promote finals for this chat."""
    from datetime import datetime

    from sqlalchemy import select

    from asset_association_service import mirror_media_associations_to_asset
    from asset_service import acquire_media_owner, create_asset_from_media
    from database import AssetRevision, MediaItem, MediaOwner

    results: list[int | None] = []
    for media_id in media_ids:
        media = await session.get(MediaItem, media_id)
        if media is None or media.deleted_at is not None:
            results.append(None)
            continue
        existing_revision = await session.scalar(
            select(AssetRevision).where(
                AssetRevision.primary_media_id == media_id,
                AssetRevision.deleted_at.is_(None),
            )
        )
        if role == "intermediate":
            if existing_revision is None:
                await acquire_media_owner(
                    session,
                    media_id=media_id,
                    root_kind="chat",
                    root_id=chat_id,
                    role="intermediate",
                    idempotency_key=f"chat:{chat_id}:media:{media_id}:intermediate",
                )
            results.append(existing_revision.asset_id if existing_revision else None)
            continue

        embedded_media_ids: list[int] = []
        if media.file_format in {"stimmaset.json", "stimmagrid.json"}:
            from container_service import (
                create_container_asset_from_media,
                infer_structured_member_specs,
            )
            member_specs = await infer_structured_member_specs(
                session, container_media=media
            )
            embedded_media_ids = [
                int(spec["embedded_media_id"])
                for spec in member_specs
                if spec.get("embedded_media_id") is not None
            ]
            asset = await create_container_asset_from_media(
                session,
                media_id=media_id,
                container_type="set" if media.file_format == "stimmaset.json" else "grid",
                members=member_specs,
                origin_type="chat_final",
                origin_id=str(chat_id),
                idempotency_key=f"chat:{chat_id}:media:{media_id}:final",
            )
        else:
            asset = await create_asset_from_media(
                session,
                media_id=media_id,
                origin_type="chat_final",
                origin_id=str(chat_id),
                idempotency_key=f"chat:{chat_id}:media:{media_id}:final",
            )
        await mirror_media_associations_to_asset(
            session, media_id=media_id, asset_id=asset.id
        )
        # The AssetRevision is now the strong root. Release every provisional
        # ownership edge held by this chat for the exact Media.
        owners = list(
            await session.scalars(
                select(MediaOwner).where(
                    MediaOwner.media_id.in_([media_id, *embedded_media_ids]),
                    MediaOwner.root_kind == "chat",
                    MediaOwner.root_id == str(chat_id),
                    MediaOwner.deleted_at.is_(None),
                )
            )
        )
        now = datetime.utcnow()
        for owner in owners:
            owner.deleted_at = now
        results.append(asset.id)
    await session.flush()
    return results


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


async def _create_display_item(
    session, chat_id, rows, title, role, media_ids, asset_ids, ws_manager
):
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
        media_id=media_ids[0] if len(media_ids) == 1 else None,
        media_ids=json.dumps(media_ids) if media_ids else None,
        asset_id=asset_ids[0] if len(asset_ids) == 1 else None,
        asset_ids=json.dumps(asset_ids) if asset_ids else None,
        show_role=role,
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
