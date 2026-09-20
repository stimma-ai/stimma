"""Creative document adapters over the same builders used by the chat SDK."""

import asyncio
import json
from pathlib import Path
from sqlalchemy import select
from database import Asset, AssetRevision
from .access import access, McpError
from .workspace import media_row


async def build(caller, args, session, chat, folder):
    """Return an existing Media id or a workspace output to ingest."""
    kind = args["format"]
    if kind in ("set", "grid"):
        members = [await media_row(caller, ref, session) for ref in args["members"]]
        common = dict(
            media_ids=[m.id for m in members],
            title=args.get("title", ""),
            description=args.get("description", ""),
            session=session,
            chat_id=chat.id,
            project_id=chat.project_id,
        )
        if kind == "set":
            from agent.v2.tools.assemble_set import assemble_set

            result = await assemble_set(**common)
        else:
            from agent.v2.tools.assemble_grid import create_parameter_sweep

            result = await create_parameter_sweep(
                **common,
                rows=len(args["row_headers"]),
                cols=len(args["col_headers"]),
                row_headers=args["row_headers"],
                col_headers=args["col_headers"],
            )
        if result.startswith("Error:"):
            raise McpError("invalid_arguments", result)
        import re

        return int(re.search(r"media_id=(\d+)", result).group(1)), None
    if kind == "sprite":
        from sprite_document import (
            DOCUMENT_REF_FIELDS,
            ANIMATION_REF_FIELDS,
            validate_sprite_document,
        )

        doc = json.loads(json.dumps(args["document"]))
        for record, fields in [(doc, DOCUMENT_REF_FIELDS)] + [
            (entry, ANIMATION_REF_FIELDS) for entry in doc.get("animations", [])
        ]:
            for field in fields:
                value = record.get(field)
                if value is None:
                    continue
                if not isinstance(value, dict) or not isinstance(value.get("ref"), str):
                    raise McpError(
                        "invalid_arguments",
                        f"{field} requires an opaque ref, not a server media id or hash.",
                    )
                media = await media_row(caller, value["ref"], session)
                record[field] = {
                    k: v
                    for k, v in value.items()
                    if k not in ("ref", "media_id", "hash", "resolved")
                }
                record[field].update(media_id=media.id, hash=media.file_hash)
        errors = validate_sprite_document(doc)
        if errors:
            raise McpError("invalid_arguments", "; ".join(errors[:5]))
        path = folder / "document.stimmasprite.json"
        path.write_text(json.dumps(doc))
        return None, path
    if kind == "package":
        from agent.v2.code_runtime import StimmaSDK
        from .jobs import check_execution

        sdk = StimmaSDK(
            session=session,
            chat_id=chat.id,
            workspace_dir=folder,
            project_workspace_dir=None,
            interrupt_checker=check_execution,
            project_id=chat.project_id,
        )
        draft = sdk.packages.new(args.get("title", "Package"))
        async with draft._builder as builder:
            if args.get("source_ref"):
                source = await media_row(caller, args["source_ref"], session)
                if source.file_format != "stimmapackage":
                    raise McpError("invalid_arguments", "source_ref must be a package.")
                await builder.load(source.id)
            if "title" in args:
                builder.title = args["title"]
            for member in args.get("members", []):
                media = await media_row(caller, member["ref"], session)
                if member.get("replace"):
                    await builder.replace_member(member["replace"], media.id)
                else:
                    await builder.add_member(
                        media.id, role=member.get("role"), member_id=member.get("id")
                    )
            for entry in args.get("files", []):
                path = await file_source(caller, entry, session, folder)
                if entry.get("replace"):
                    builder.replace_extra(entry["replace"], path)
                else:
                    builder.add_extra(path, name=entry["name"])
            for run in args.get("runs", []):
                if run.get("rerun"):
                    await builder.rerun(run["rerun"], run.get("params"))
                else:
                    await draft.run(run["recipe"], run["inputs"], run.get("params", {}))
            if args.get("tile_ref"):
                builder.set_tile(
                    Path((await media_row(caller, args["tile_ref"], session)).file_path)
                )
            if "cover" in args:
                builder.set_cover(args["cover"])
            if not builder.cover_source:
                raise McpError(
                    "invalid_arguments",
                    "A package needs an authored cover HTML string; use content_get to inspect recipes and existing packages.",
                )
            media, _ = await builder.save()
            return media.id, None
    if kind == "export":
        from agent.v2.code_runtime import StimmaSDK
        from .jobs import check_execution

        source = await media_row(caller, args["source_ref"], session)
        output = args["output_format"]
        path = folder / ("export." + output)
        sdk = StimmaSDK(
            session=session,
            chat_id=chat.id,
            workspace_dir=folder,
            project_workspace_dir=None,
            interrupt_checker=check_execution,
            project_id=chat.project_id,
        )
        if source.file_format == "stimmasprite.json":
            from sprite_export import (
                load_sprite_source,
                run_sprite_export,
                SpriteExportOptions,
            )

            sprite = await load_sprite_source(session, source)
            exported = await asyncio.to_thread(
                run_sprite_export,
                sprite,
                SpriteExportOptions(format=output, **args.get("options", {})),
            )
            path = folder / safe_name(exported.filename)
            path.write_bytes(exported.payload)
        elif source.file_format == "stimmalayout":
            if output == "html":
                await sdk.export_layout_html(source.id, out=path)
            elif output == "png":
                await sdk.rasterize_layout(source.id, out=path, dpi=args.get("dpi"))
            else:
                raise McpError("invalid_arguments", "Layouts export as html or png.")
        elif source.file_format == "stimmapackage":
            bundle = Path(source.file_path)
            if output == "html":
                from packages.export import export_single_html

                path.write_text(await asyncio.to_thread(export_single_html, bundle))
            elif output == "pdf":
                from packages.print_cover import export_pdf

                path.write_bytes(await asyncio.to_thread(export_pdf, bundle))
            elif output == "png":
                draft = await sdk.packages.open(source.id)
                try:
                    preview = await draft.preview_html(width=args.get("width", 1200))
                    path = folder / preview["image"]
                finally:
                    draft._builder.cleanup()
            else:
                raise McpError(
                    "invalid_arguments",
                    "Packages export as html, pdf or png; media_export downloads the full bundle ZIP.",
                )
        elif source.file_format == "svg" and output == "png":
            await sdk.rasterize_svg(Path(source.file_path).read_text(), out=path)
        else:
            raise McpError(
                "invalid_arguments",
                "Unsupported document export. Use media_export for original bytes.",
            )
        return None, path
    raise McpError("invalid_arguments", "Unknown document format.")


def safe_name(name):
    path = Path(name)
    if (
        not name
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in name
        or path == Path(".")
    ):
        raise McpError("invalid_arguments", "Bundle files require safe relative names.")
    return path


async def file_source(caller, entry, session, folder):
    safe_name(entry["name"])
    if "source_ref" in entry:
        path = Path((await media_row(caller, entry["source_ref"], session)).file_path)
        if not path.is_file():
            raise McpError("invalid_arguments", "Bundle file source must be a file.")
        return path
    import uuid

    path = folder / (uuid.uuid4().hex + Path(entry["name"]).suffix)
    path.write_text(entry["text"])
    return path


async def inspect(caller, args, session):
    if args.get("action") == "recipes":
        from packages.recipes import list_recipes

        return {
            "recipes": [
                {**spec.to_dict(), "guidance": spec.guidance}
                for spec in list_recipes(caller.profile_id)
            ]
        }
    media = await media_row(caller, args["ref"], session)
    revision = await session.scalar(
        select(AssetRevision).where(
            AssetRevision.primary_media_id == media.id,
            AssetRevision.deleted_at.is_(None),
        )
    )
    result = {
        "media_ref": access.ref(caller, "media", media.id),
        "format": media.file_format,
    }
    if revision:
        result.update(
            asset_ref=access.ref(caller, "asset", revision.asset_id),
            revision_ref=access.ref(caller, "revision", revision.id),
        )
    if args.get("action") == "revisions":
        if not revision:
            return {**result, "revisions": []}
        versions = await session.scalars(
            select(AssetRevision)
            .where(
                AssetRevision.asset_id == revision.asset_id,
                AssetRevision.deleted_at.is_(None),
            )
            .order_by(AssetRevision.revision_number.desc())
        )
        return {
            **result,
            "revisions": [
                {
                    "revision_ref": access.ref(caller, "revision", r.id),
                    "media_ref": access.ref(caller, "media", r.primary_media_id),
                    "number": r.revision_number,
                    "note": r.note,
                }
                for r in versions
            ],
        }
    if media.file_format in ("stimmaset.json", "stimmagrid.json"):
        from container_service import resolve_container_members

        content = json.loads(media.raw_metadata or "{}")
        result.update(
            {
                k: content[k]
                for k in (
                    "title",
                    "description",
                    "rows",
                    "cols",
                    "row_headers",
                    "col_headers",
                )
                if k in content
            }
        )
        result["members"] = []
        if revision:
            owner = await session.get(Asset, revision.asset_id)
            result["title"] = owner.title if owner else result.get("title")
            for item in await resolve_container_members(
                session, revision_id=revision.id
            ):
                result["members"].append(
                    {
                        "ref": access.ref(caller, "asset", item["linked_asset_id"])
                        if item["linked_asset_id"]
                        else access.ref(caller, "media", item["media_id"])
                        if item["media_id"]
                        else None,
                        "media_ref": access.ref(caller, "media", item["media_id"])
                        if item["media_id"]
                        else None,
                        "row": item["row_index"],
                        "col": item["column_index"],
                        "unavailable": item["unavailable"],
                    }
                )
    elif media.file_format == "stimmapackage":
        from packages.bundle import manifest_for_media, package_status

        result["manifest"] = await manifest_for_media(session, media)
        for member in result["manifest"].get("members", []):
            if member.get("media_id") is not None:
                member["media_ref"] = access.ref(
                    caller, "media", member.pop("media_id")
                )
        status = await package_status(session, media)
        for member in status.get("members", []):
            for field, kind in [
                ("media_id", "media"),
                ("current_media_id", "media"),
                ("linked_asset_id", "asset"),
            ]:
                value = member.pop(field, None)
                member[field[:-3] + "_ref"] = (
                    access.ref(caller, kind, value) if value is not None else None
                )
        result["status"] = {"stale": status["stale"], "members": status["members"]}
        cover = Path(media.file_path) / "_stimma/cover.src.html"
        if cover.is_file():
            result["cover"] = cover.read_text()[:512000]
    elif media.file_format == "stimmasprite.json":
        from sprite_document import iter_sprite_refs

        doc = json.loads(media.raw_metadata or "{}")
        for _, value in iter_sprite_refs(doc):
            if value.get("media_id") is not None:
                value["ref"] = access.ref(caller, "media", value.pop("media_id"))
            value.pop("hash", None)
            value.pop("resolved", None)
        result["document"] = doc
    elif media.file_format == "stimmalayout":
        folder = Path(media.file_path)
        result["files"] = [
            {
                "name": p.relative_to(folder).as_posix(),
                **(
                    {"text": p.read_text()[:128000]}
                    if p.suffix in (".html", ".css", ".js", ".json", ".svg", ".txt")
                    and p.stat().st_size <= 128000
                    else {}
                ),
            }
            for p in sorted(folder.rglob("*"))
            if p.is_file() and not p.is_symlink()
        ][:100]
    elif media.file_format in ("svg", "md", "markdown", "html"):
        result["text"] = Path(media.file_path).read_text()[:512000]
    return result
