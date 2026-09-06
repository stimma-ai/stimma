"""Saved-image transforms and structured-document writes, with revision guards."""

from pathlib import Path
import json
import uuid
from sqlalchemy import text
from database import Asset
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
    if args["format"] == "image":
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
    provenance = {
        "task_type": "edit",
        "tool_id": "stimma:mcp-content",
        "parameters": {"format": args["format"]},
        "source_media_ids": [source.id] if source else [],
    }
    saved = await save_workspace_file(
        session,
        str(path),
        folder,
        None,
        provenance=provenance,
        project_id=chat.project_id,
        metadata_source="mcp",
        materialize_asset=False,
    )
    if saved.startswith("Error:"):
        raise McpError("save_failed", "Could not save the edited document.")
    result = json.loads(saved)
    # The shared save helper finishes ingestion first. Lock and compare the
    # current revision in the transaction that acquires the new saved revision.
    await session.commit()
    await session.execute(text("BEGIN IMMEDIATE"))
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
            note="MCP edit",
        )
    else:
        asset = await create_asset_from_media(
            session, media_id=result["media_id"], origin_type="mcp_edit"
        )
        from database import AssetRevision

        revision = await session.get(AssetRevision, asset.current_revision_id)
    await session.commit()
    from utils.websocket import ws_manager

    await ws_manager.broadcast(
        "asset_current_revision_changed",
        {"asset_id": asset.id, "revision_id": revision.id},
    )
    return {
        "asset_ref": access.ref(caller, "asset", asset.id),
        "revision_ref": access.ref(caller, "revision", revision.id),
        "media_ref": access.ref(caller, "media", result["media_id"]),
    }
