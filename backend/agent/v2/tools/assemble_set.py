"""Assemble generated images into a set (simple grouping without parameter axes)."""

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter

import app_dirs
from config_version import get_config_version_manager
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import MediaItem
from generation_metadata import dump_generation_metadata
from utils.lineage import record_lineage, propagate_tool_lineage
from utils.websocket import ws_manager

log = get_logger(__name__)


@tool(
    name="assemble_set",
    description=(
        "Group previously generated images into a set. Creates a .stimmaset.json "
        "MediaItem for display. Members remain independent; final show() promotion "
        "records linked Assets or exact embedded Media."
    ),
    parameters=[
        ToolParameter(
            name="media_ids",
            type="array",
            description="Media IDs to group into the set, in display order.",
            items={"type": "integer"},
        ),
        ToolParameter(
            name="title",
            type="string",
            description="Title for the set",
            required=False,
        ),
        ToolParameter(
            name="description",
            type="string",
            description="Optional description of the set",
            required=False,
        ),
    ],
)
async def assemble_set(
    media_ids: List,
    title: str = "",
    description: str = "",
    **kwargs,
) -> str:
    session: AsyncSession = kwargs.get("session")
    if not session:
        return "Error: No database session available"

    # Normalize media_ids
    normalized_ids = []
    for item in media_ids:
        if isinstance(item, dict) and "media_id" in item:
            normalized_ids.append(item["media_id"])
        elif isinstance(item, (int, str)):
            normalized_ids.append(int(item))
        else:
            normalized_ids.append(item)
    media_ids = normalized_ids

    if not media_ids:
        return "Error: No media IDs provided"

    log.info(f"[assemble_set] Assembling set '{title}' from {len(media_ids)} media items")

    # Query all MediaItem records
    result = await session.execute(
        select(MediaItem).where(MediaItem.id.in_(media_ids))
    )
    media_items_by_id = {m.id: m for m in result.scalars().all()}

    missing = [mid for mid in media_ids if mid not in media_items_by_id]
    if missing:
        return f"Error: Media items not found: {missing}"

    # Validate no structured media types (no nesting)
    for mid, item in media_items_by_id.items():
        if item.file_format in ('stimmaset.json', 'stimmagrid.json'):
            return f"Error: Cannot add structured media to a set (item {mid} is a {item.file_format})"

    # Build set file path
    profile_id = get_current_profile()
    output_folder = app_dirs.get_managed_staging_dir(profile_id, "generated")
    output_folder.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = title.replace(" ", "_").replace("/", "-")[:50] if title else "set"
    filename = f"{base_name}_{timestamp}.stimmaset.json"
    set_file_path = output_folder / filename

    counter = 1
    while set_file_path.exists():
        filename = f"{base_name}_{timestamp}_{counter}.stimmaset.json"
        set_file_path = output_folder / filename
        counter += 1

    # Build set JSON with relative paths where possible
    import os
    set_items = []
    for mid in media_ids:
        media_item = media_items_by_id[mid]
        item_path = Path(media_item.file_path)
        try:
            path_str = os.path.relpath(item_path, output_folder)
        except ValueError:
            path_str = str(item_path)
        set_items.append({"path": path_str})

    set_data = {
        "version": 1,
        "items": set_items,
    }
    if title:
        set_data["title"] = title
    if description:
        set_data["description"] = description

    # Write the file
    with open(set_file_path, 'w', encoding='utf-8') as f:
        json.dump(set_data, f, indent=2)

    # Compute hash
    with open(set_file_path, 'rb') as f:
        file_hash = hashlib.sha256(f.read()).hexdigest()
    stat_info = set_file_path.stat()

    # Create MediaItem for the set
    set_media_item = MediaItem(
        file_path=str(set_file_path),
        file_hash=file_hash,
        file_size=stat_info.st_size,
        file_format='stimmaset.json',
        created_date=datetime.utcfromtimestamp(stat_info.st_ctime),
        modified_date=datetime.utcfromtimestamp(stat_info.st_mtime),
        indexed_date=datetime.utcnow(),
        metadata_status='completed',
        metadata_processed_at=datetime.utcnow(),
        metadata_config_version=get_config_version_manager().get_version('metadata'),
        width=0,
        height=0,
        megapixels=0,
        raw_metadata=json.dumps(set_data),
        generation_metadata=dump_generation_metadata(
            task_type='set-creation',
            source='agent_v2_assemble_set',
            source_inputs=[{'media_id': mid, 'role': 'item'} for mid in media_ids],
            extra={'item_count': len(media_ids)},
        ),
    )

    session.add(set_media_item)
    await session.flush()
    from storage_service import stage_managed_media

    await stage_managed_media(
        session,
        media=set_media_item,
        profile_id=profile_id,
        remove_source=True,
    )

    output_context_kind = kwargs.get("output_context_kind")
    output_context_id = kwargs.get("output_context_id")
    if output_context_kind and output_context_id:
        from asset_service import acquire_media_owner
        await acquire_media_owner(
            session,
            media_id=set_media_item.id,
            root_kind=output_context_kind,
            root_id=output_context_id,
            role="result",
            idempotency_key=(
                f"flow:{output_context_id}:media:{set_media_item.id}"
                if output_context_kind == "flow_equation"
                else f"{output_context_kind}:{output_context_id}:assembled-set:{set_media_item.id}"
            ),
        )

    chat_id = kwargs.get("chat_id")
    if chat_id is not None:
        from asset_service import acquire_media_owner
        await acquire_media_owner(
            session,
            media_id=set_media_item.id,
            root_kind="chat",
            root_id=chat_id,
            role="result",
            idempotency_key=f"chat:{chat_id}:assembled-set:{set_media_item.id}",
        )

    # Attach to project if in project context
    project_id = kwargs.get("project_id")
    if project_id is not None:
        from project_service import attach_media_to_project
        await attach_media_to_project(session, project_id, set_media_item.id)

    await session.commit()
    await session.refresh(set_media_item)
    from storage_service import cleanup_staged_source

    await cleanup_staged_source(session, media_id=set_media_item.id)

    # Record Media lineage. Container membership is normalized when show(role="final")
    # promotes the assembled result; members are never hidden or replaced.
    source_ids = [mid for mid in media_ids if mid in media_items_by_id]
    if source_ids:
        await record_lineage(session, set_media_item.id, source_ids, "set-creation")
        await propagate_tool_lineage(session, set_media_item.id, source_ids)

        await session.commit()

    from telemetry import get_telemetry_client
    get_telemetry_client().track("set_created", {
        "count": len(media_ids),
        "actor": "agent",
    }, category="library")

    log.info(f"[assemble_set] Created set media item {set_media_item.id}: {set_file_path}")

    # Broadcast media_added
    await ws_manager.broadcast('media_added', {
        'media_id': set_media_item.id,
        'count': 1,
    })

    # Trigger rescan
    try:
        from database import ControlFlag
        from sqlalchemy.dialects.sqlite import insert
        from core.app import get_rescan_event

        stmt = insert(ControlFlag).values(
            key='rescan_requested', value='true', updated_at=datetime.utcnow()
        ).on_conflict_do_update(
            index_elements=['key'],
            set_=dict(value='true', updated_at=datetime.utcnow())
        )
        await session.execute(stmt)
        await session.commit()

        rescan_event = get_rescan_event()
        if rescan_event:
            rescan_event.set()
    except Exception as e:
        log.warning(f"[assemble_set] Failed to trigger rescan: {e}")

    return (
        f"<result media_id={set_media_item.id} />"
        f"Set '{title or 'Untitled'}' created ({len(media_ids)} images). "
        f"Media ID: {set_media_item.id}. Member images remain independent."
    )
