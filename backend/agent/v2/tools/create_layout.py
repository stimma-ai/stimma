"""Create a layout — renders HTML/CSS to a .stimmalayout bundle and saves it to the library."""

import json
import shutil
import uuid
from datetime import datetime
from pathlib import Path

from ..tools_registry import tool, ToolParameter

from config_version import get_config_version_manager
from core.logging import get_logger
from generation_metadata import build_generation_metadata
from flow_runtime.layout_bundle import (
    assemble_index_html,
    copy_referenced_images,
    extract_all_refs,
    lint_image_refs,
)

log = get_logger(__name__)


@tool(
    name="create_layout",
    description="Create a fixed-size layout from HTML/CSS and save it to the library. Think of width/height as your canvas/artboard — the HTML must fill this canvas exactly, like choosing dimensions for image generation. Returns the media_id of the saved layout. Preferred workflow: write HTML to a workspace file with write_file, then pass the file path here. Image src paths are resolved relative to the workspace directory only — use exact filenames for files already in the workspace. For library media, copy it into the workspace first via library(action='get', media_id=...). Do not use guessed filenames or absolute filesystem paths in img src.",
    parameters=[
        ToolParameter(
            name="file",
            type="string",
            description="Path to an HTML file in the workspace to render (e.g. 'layout.html'). Preferred over inline html — write once, iterate with edit_file, re-render.",
            required=False,
        ),
        ToolParameter(
            name="html",
            type="string",
            description="Inline HTML body content. Use for simple one-shot layouts. For iterative work, prefer writing to a file and using the 'file' parameter.",
            required=False,
        ),
        ToolParameter(
            name="css",
            type="string",
            description="Optional CSS stylesheet",
            required=False,
        ),
        ToolParameter(
            name="width",
            type="integer",
            description="Canvas width in pixels. Choose to match your intent: business card ~700, social card 1200, poster 900, etc.",
            required=False,
        ),
        ToolParameter(
            name="height",
            type="integer",
            description="Canvas height in pixels. Choose to match your intent: business card ~400, social card 630, poster 1600, etc.",
            required=False,
        ),
    ],
)
async def create_layout(
    file: str | None = None,
    html: str | None = None,
    css: str | None = None,
    width: int = 800,
    height: int | None = None,
    **kwargs,
) -> str:
    workspace_dir = kwargs.get("workspace_dir")
    if not workspace_dir:
        return "Error: No workspace directory available"

    # Resolve HTML source: file takes precedence
    if file:
        from ._workspace_files import resolve_workspace_path
        resolved, err = resolve_workspace_path(workspace_dir, file)
        if err:
            return err
        if not resolved.exists():
            return f"Error: File not found: {file}"
        try:
            html = resolved.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return f"Error: File is not a text file: {file}"

    if not html:
        return "Error: Provide either 'file' (path to HTML file in workspace) or 'html' (inline HTML string). Preferred: write_file then create_layout(file=...)."

    workspace_path = Path(workspace_dir).resolve()
    width = max(200, min(4096, width))
    if height is not None:
        height = max(100, min(10000, height))

    # Create .stimmalayout directory bundle
    bundle_name = f"layout_{uuid.uuid4().hex[:8]}.stimmalayout"
    bundle_path = Path(workspace_dir) / bundle_name
    bundle_path.mkdir(parents=True, exist_ok=True)

    # Lint image references — fail early with actionable errors
    missing = lint_image_refs(html, workspace_path)
    if missing:
        bundle_path.rmdir()  # clean up empty bundle
        available = sorted(
            f.name for f in workspace_path.iterdir()
            if f.is_file() and f.suffix.lower() in {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.svg'}
        )
        lines = [f"Error: {len(missing)} image(s) referenced in HTML not found in workspace:"]
        for src in missing:
            lines.append(f"  - {src}")
        if available:
            lines.append(f"Available image files in workspace: {', '.join(available)}")
        else:
            lines.append("No image files found in workspace. Generate or copy images to workspace first.")
        return "\n".join(lines)

    # Find and copy referenced images from workspace into the bundle
    html = copy_referenced_images(html, workspace_path, bundle_path)

    # Agent-tool behavior: default to square canvas when height not specified.
    # (The flow-level create_layout passes height=None through to support
    # content-measured rendering — see layout_bundle.assemble_index_html.)
    if height is None:
        height = width

    index_html = assemble_index_html(html, width=width, height=height, extra_css=css or "")
    index_path = bundle_path / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    # Auto-save to library
    session = kwargs.get("session")
    if session:
        try:
            media_id = await _save_to_library(
                session=session,
                bundle_path=bundle_path,
                index_path=index_path,
                session_media_ids=kwargs.get("session_media_ids"),
                project_id=kwargs.get("project_id"),
            )
            return json.dumps({"media_id": media_id, "bundle": bundle_name})
        except Exception as e:
            log.error(f"Failed to save layout to library: {e}")
            # Fall back to returning the path if library save fails
            return str(bundle_path)

    return str(bundle_path)


async def _save_to_library(
    session,
    bundle_path: Path,
    index_path: Path,
    session_media_ids: list[int] | None = None,
    project_id: int | None = None,
) -> int:
    """Save the layout bundle to the library and return the media_id."""
    import hashlib
    import os

    from sqlalchemy import select

    from config import get_settings
    from core.profile_context import get_current_profile
    from database import MediaItem, MediaLineage

    settings = get_settings()
    profile_id = get_current_profile()
    output_folder = settings.get_generation_folder_for_profile(profile_id).path
    os.makedirs(output_folder, exist_ok=True)

    dest = os.path.join(output_folder, bundle_path.name)
    if os.path.exists(dest):
        stem = bundle_path.name.rsplit('.stimmalayout', 1)[0]
        counter = 1
        while os.path.exists(dest):
            dest = os.path.join(output_folder, f"{stem}_{counter}.stimmalayout")
            counter += 1

    shutil.copytree(str(bundle_path), dest)

    # Hash the index.html for dedup
    file_hash = hashlib.sha256(index_path.read_bytes()).hexdigest()
    file_size = index_path.stat().st_size

    # Build provenance — start with explicit session media, then auto-detect
    # from image references in the HTML so lineage is tracked without relying
    # on the agent to declare them.
    source_ids = list(session_media_ids or [])
    source_id_set = set(source_ids)

    # Resolve image filenames referenced in the HTML to media_ids
    html_content = index_path.read_text(encoding="utf-8")
    for ref in extract_all_refs(html_content):
        basename = os.path.basename(ref)
        result = await session.execute(
            select(MediaItem.id)
            .where(MediaItem.file_path.like(f"%/{basename}"))
            .order_by(MediaItem.id.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row and row not in source_id_set:
            source_ids.append(row)
            source_id_set.add(row)
    gen_meta = build_generation_metadata(
        task_type="layout",
        source="agent_v2_create_layout",
        source_inputs=[
            {"media_id": mid, "role": "source_image"} for mid in source_ids
        ],
    )

    media_item = MediaItem(
        file_path=dest,
        file_hash=file_hash,
        file_size=file_size,
        file_format="stimmalayout",
        width=0,
        height=0,
        megapixels=0.0,
        metadata_status="completed",
        metadata_config_version=get_config_version_manager().get_version('metadata'),
        metadata_processed_at=datetime.utcnow(),
        clip_status="skipped",
        face_detection_status="skipped",
        vlm_caption_status="skipped",
        created_date=datetime.utcnow(),
        modified_date=datetime.utcnow(),
        indexed_date=datetime.utcnow(),
        generation_metadata=json.dumps(gen_meta),
    )
    session.add(media_item)
    await session.flush()

    # Record lineage from source media
    for idx, source_media_id in enumerate(source_ids):
        session.add(MediaLineage(
            media_id=media_item.id,
            source_media_id=source_media_id,
            source_order=idx,
            task_type="layout",
            relationship_type="derived",
        ))

    # Attach to project if in project context (before commit so it's in the same transaction)
    if project_id is not None:
        from project_service import attach_media_to_project
        await attach_media_to_project(session, project_id, media_item.id)
        log.info(f"[create_layout] Attached media {media_item.id} to project {project_id}")

    await session.commit()

    # Broadcast so the UI picks it up
    try:
        from utils.websocket import broadcast_media_updated
        await broadcast_media_updated(media_item, ["created"], session)
    except Exception as e:
        log.warning(f"[create_layout] Failed to broadcast media update: {e}")

    return media_item.id
