"""Saved-image transforms and structured-document writes, with revision guards."""

from pathlib import Path
import json
import uuid
from datetime import datetime
from sqlalchemy import select, text
from database import Asset, AssetRevision, MediaItem, MediaLineage, MediaOwner
from .access import access, McpError
from .workspace import media_row


async def update(caller, args, session, chat):
    from agent.v2.workspace import get_workspace_dir
    from agent.v2.tools.library import save_workspace_file
    from asset_service import commit_revision, create_asset_from_media

    folder = get_workspace_dir(chat.id, chat.project_id)
    folder.mkdir(parents=True, exist_ok=True)
    source = None
    if args.get("source_ref"):
        source = await media_row(caller, args["source_ref"], session)
    passthrough = args["format"] == "file" or (args["format"] == "image" and not args["transforms"])
    if passthrough:
        if source is None or not Path(source.file_path).is_file():
            raise McpError("invalid_arguments", "Saving a file requires a reference to an available media file.")
    elif args["format"] == "image":
        if source is None:
            raise McpError(
                "invalid_arguments",
                "Image transformations require an exact source reference.",
            )
        from PIL import Image, ImageOps

        with Image.open(source.file_path) as raw:
            image = ImageOps.exif_transpose(raw).copy()
        for operation in args["transforms"]:
            action = operation["action"]
            if action == "resize":
                image = image.resize(
                    (operation["width"], operation["height"]), Image.Resampling.LANCZOS
                )
            elif action == "crop":
                box = operation["box"]
                if not (
                    0 <= box[0] < box[2] <= image.width
                    and 0 <= box[1] < box[3] <= image.height
                ):
                    raise McpError(
                        "invalid_arguments",
                        "Crop coordinates must lie inside the image.",
                    )
                image = image.crop(box)
            elif action == "rotate":
                image = image.rotate(operation["degrees"], expand=True)
            elif action == "flip_horizontal":
                image = ImageOps.mirror(image)
            elif action == "flip_vertical":
                image = ImageOps.flip(image)
        path = folder / (uuid.uuid4().hex + ".png")
        image.save(path)
    else:
        extension = {"svg": "svg", "markdown": "md", "layout": "stimmalayout"}[
            args["format"]
        ]
        path = folder / (uuid.uuid4().hex + "." + extension)
        if args["format"] == "layout":
            path.mkdir()
            for entry in args["files"]:
                relative = Path(entry["name"])
                if (
                    relative.is_absolute()
                    or ".." in relative.parts
                    or "\\" in entry["name"]
                ):
                    raise McpError(
                        "invalid_arguments",
                        "Bundle members must have safe relative names.",
                    )
                destination = path / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_text(entry["text"])
            if not (path / "index.html").is_file():
                raise McpError("invalid_arguments", "A layout requires index.html.")
        else:
            content = args["text"]
            if args["format"] == "svg":
                from utils.svg_doc import prepare_text

                content, _ = prepare_text(content)
            path.write_text(content)
    # The assistant's own account of the change is the record: it heads the
    # lineage entry (as the prompt) and labels the version.
    note = (args.get("note") or "").strip()
    sources = [await media_row(caller, ref, session) for ref in args.get("source_refs", [])]
    source_ids = list(dict.fromkeys(
        [row.id for row in sources] if "source_refs" in args else [source.id] if source else []
    ))
    provenance = {
        "task_type": "edit",
        "tool_id": "stimma:assistant-edit",
        "prompt": note,
        "parameters": {
            "format": args["format"],
            **({"note": note} if note else {}),
            **({"transforms": args["transforms"]} if args["format"] == "image" else {}),
        },
        "source_media_ids": source_ids,
    }
    if not passthrough:
        saved = await save_workspace_file(
            session, str(path), folder, None, provenance=provenance,
            project_id=chat.project_id, metadata_source="mcp", materialize_asset=False,
        )
        if saved.startswith("Error:"):
            raise McpError("save_failed", "Could not save the edited document.")
        result = json.loads(saved)
    # The shared save helper finishes ingestion first. Lock and compare the
    # current revision in the transaction that acquires the new saved revision.
    await session.commit()
    await session.execute(text("BEGIN IMMEDIATE"))
    if passthrough:
        # New immutable provenance identity over the same stored bytes, as in
        # revision restoration. Do not decode images or discard AV metadata.
        from generation_metadata import build_parameters, dump_generation_metadata
        from utils.lineage import propagate_tool_lineage

        excluded = {"id", "indexed_date", "deleted_at", "deletion_pending_at", "ephemeral_run_id", "random_sort_value", "auto_delete_at"}
        media = MediaItem(**{
            column.name: getattr(source, column.name)
            for column in MediaItem.__table__.columns if column.name not in excluded
        })
        media.tool_id = provenance["tool_id"]
        media.extracted_prompt = note
        media.generation_metadata = dump_generation_metadata(
            task_type="edit", source="mcp", tool_id=media.tool_id, prompt=note,
            parameters=build_parameters(provenance["parameters"]),
            source_inputs=[{"media_id": mid, "role": "source"} for mid in source_ids],
        )
        session.add(media)
        await session.flush()
        for index, mid in enumerate(source_ids):
            session.add(MediaLineage(media_id=media.id, source_media_id=mid, source_order=index, task_type="edit", relationship_type="derived"))
        await propagate_tool_lineage(session, media.id, source_ids, own_tool_id=media.tool_id)
        result = {"media_id": media.id}
    if args.get("target_asset_ref"):
        asset_id = int(access.resolve(caller, args["target_asset_ref"], "asset"))
        expected = int(
            access.resolve(caller, args["expected_current_revision"], "revision")
        )
        asset = await session.get(Asset, asset_id, populate_existing=True)
        if not asset or asset.current_revision_id != expected:
            raise McpError(
                "revision_conflict",
                "The Asset changed. The new content has not replaced its current revision.",
            )
        revision = await commit_revision(
            session,
            asset_id=asset.id,
            media_id=result["media_id"],
            parent_revision_id=expected,
            note=note or "Edited by a connected assistant",
        )
    else:
        asset = await create_asset_from_media(
            session, media_id=result["media_id"], origin_type="mcp_edit"
        )
        revision = await session.get(AssetRevision, asset.current_revision_id)
        revision.note = note or "Saved by a connected assistant"
    if chat.project_id is not None:
        from asset_association_service import attach_asset_to_project

        await attach_asset_to_project(session, chat.project_id, asset.id)
    if source:
        # A successfully saved revision now retains the bytes. Release only
        # provisional upload ownership, never an existing library Asset.
        for owner in await session.scalars(select(MediaOwner).where(
            MediaOwner.media_id == source.id, MediaOwner.root_kind == "upload",
            MediaOwner.role == "provisional", MediaOwner.deleted_at.is_(None),
        )):
            owner.deleted_at = datetime.utcnow()
    await session.commit()
    from utils.websocket import ws_manager

    await ws_manager.broadcast(
        "asset_current_revision_changed" if args.get("target_asset_ref") else "asset_created",
        {"asset_id": asset.id, "revision_id": revision.id, "media_id": result["media_id"]},
    )
    return {
        "asset_ref": access.ref(caller, "asset", asset.id),
        "revision_ref": access.ref(caller, "revision", revision.id),
        "media_ref": access.ref(caller, "media", result["media_id"]),
    }
