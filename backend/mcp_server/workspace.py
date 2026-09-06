"""Workspace reads and execution adapters shared by both MCP transports."""

from __future__ import annotations
import base64
import hashlib
import io
import json
from pathlib import Path
from sqlalchemy import select
from database import Asset, AssetRevision, MediaItem
from .access import access, McpError
from .operations import Binding, present
from core.logging import get_logger

log = get_logger(__name__)

query_binding = Binding("assets", "browse_assets", "asset")
lineage_binding = Binding("media_files", "get_media_lineage_tree", "media")


async def refresh_custom_tools():
    from providers.registry import ProviderRegistry

    registry = ProviderRegistry()
    provider = registry.get_provider("user-tools")
    if provider:
        await registry.refresh_tools("user-tools", force_refresh=True)


async def tool_descriptor(caller, ref):
    from providers.registry import ProviderRegistry

    tool_id = access.resolve(caller, ref, "tool")
    if tool_id.startswith("user-tools:"):
        await refresh_custom_tools()
    await ProviderRegistry().wait_for_discovery()
    value = ProviderRegistry().get_tool(tool_id)
    if not value:
        raise McpError(
            "provider_unavailable",
            "Tool is not currently available. Refresh the catalog.",
        )
    return tool_id, *value


def tool_version(descriptor):
    return hashlib.sha256(
        json.dumps(
            {
                "parameters": descriptor.parameter_schema,
                "output": descriptor.output_schema,
                "definition": (descriptor.metadata or {}).get("definition_version"),
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()


async def tools_search(caller, query, task_type, offset, session):
    from providers.registry import ProviderRegistry
    from agent.v2.permissions import get_stp_permission_decision

    await ProviderRegistry().wait_for_discovery()
    from database import Chat

    await refresh_custom_tools()
    matches = []
    for tool_id, provider, tool in ProviderRegistry().list_all_tools():
        if query.lower() not in (tool.name + " " + (tool.description or "")).lower():
            continue
        if task_type and task_type not in (tool.task_types or [tool.task_type]):
            continue
        if await get_stp_permission_decision(tool_id, Chat(), session) == "deny":
            continue
        matches.append(
            {
                "tool_ref": access.ref(caller, "tool", tool_id),
                "tool_id": tool_id,
                "name": tool.name,
                "description": tool.description,
                "task_types": tool.task_types,
                "provider": provider.provider_name,
                "status": provider.status.value,
            }
        )
    matches.sort(key=lambda item: (item["name"], item["tool_ref"]))
    return {
        "items": matches[offset : offset + 50],
        "total": len(matches),
        "next_offset": offset + 50 if len(matches) > offset + 50 else None,
    }


async def tools_inspect(caller, ref):
    _, provider, tool = await tool_descriptor(caller, ref)
    return {
        "tool_ref": ref,
        "name": tool.name,
        "description": tool.description,
        "schema_version": tool_version(tool),
        "parameter_schema": tool.parameter_schema,
        "output_schema": tool.output_schema,
        "status": provider.status.value,
        "media_inputs": "For media inputs use media:<opaque-reference> returned by Stimma, never a server path.",
    }


async def tool_parameters(caller, descriptor, parameters, session):
    # Provider schemas retain their own types, so validate what the assistant
    # sent (refs are strings) before media fields are swapped for what the
    # executor wants. Only fields the schema marks as media inputs resolve
    # refs; arbitrary paths or URLs are never accepted.
    import jsonschema

    jsonschema.validate(parameters, descriptor.parameter_schema)
    result = dict(parameters)
    for name, schema in (descriptor.parameter_schema.get("properties") or {}).items():
        if name not in result:
            continue
        picker = schema.get("x-control") == "image_picker"
        if "x-accept-media" not in schema and not picker:
            continue
        many = isinstance(result[name], list)
        values = result[name] if many else [result[name]]
        resolved = []
        for ref in values:
            media = await media_row(caller, ref, session)
            # Image pickers take library media ids (exact lineage); other
            # media fields take the file path the provider reads.
            resolved.append(media.id if picker else str(media.file_path))
        result[name] = resolved if many else resolved[0]
    return result


async def media_row(caller, reference, session, *, preview_only=False):
    kind = reference.split(":", 1)[0]
    ephemeral_run = None
    if kind == "context_media" and preview_only:
        identifier, ephemeral_run = json.loads(
            access.resolve(caller, reference, "context_media")
        )
    elif kind == "asset":
        asset = await session.get(
            Asset, int(access.resolve(caller, reference, "asset"))
        )
        if not asset or asset.deleted_at:
            raise McpError("not_found", "Asset is unavailable.")
        revision = await session.get(AssetRevision, asset.current_revision_id)
        identifier = revision.primary_media_id
    elif kind == "revision":
        revision = await session.get(
            AssetRevision, int(access.resolve(caller, reference, "revision"))
        )
        if not revision:
            raise McpError("not_found", "Revision is unavailable.")
        identifier = revision.primary_media_id
    else:
        identifier = int(access.resolve(caller, reference, "media"))
    row = await session.get(MediaItem, identifier)
    if (
        not row
        or row.deleted_at
        or row.deletion_pending_at
        or row.ephemeral_run_id != ephemeral_run
    ):
        raise McpError("not_found", "Media is unavailable.")
    return row


async def preview(caller, reference, session):
    from mcp.types import ImageContent, TextContent

    row = await media_row(caller, reference, session, preview_only=True)
    path = Path(row.file_path)
    if not path.is_file():
        raise McpError(
            "preview_unavailable",
            "No inline preview for this format; download it with media_export.",
        )
    if row.file_format.lower() in ("png", "jpg", "jpeg", "webp", "gif", "bmp"):
        from PIL import Image, ImageOps

        with Image.open(path) as source:
            picture = ImageOps.exif_transpose(source)
            picture.thumbnail((1024, 1024))
            buffer = io.BytesIO()
            picture.convert("RGB").save(buffer, format="JPEG", quality=85)
        return [
            ImageContent(
                type="image",
                data=base64.b64encode(buffer.getvalue()).decode(),
                mimeType="image/jpeg",
            )
        ]
    if row.file_format.lower() in (
        "svg",
        "md",
        "txt",
        "json",
        "stimmaset.json",
        "stimmagrid.json",
    ):
        if path.stat().st_size > 128 * 1024:
            raise McpError(
                "transfer_required", "This document is too large to show inline; download it with media_export."
            )
        return [TextContent(type="text", text=path.read_text())]
    raise McpError(
        "preview_unavailable",
        "No inline preview for this format; download it with media_export.",
    )


async def assets_get(caller, references, session):
    from routes.assets import get_asset

    return {
        "items": [
            present(
                caller,
                await get_asset(int(access.resolve(caller, ref, "asset")), session),
                "asset",
            )
            for ref in references
        ]
    }


async def catalog(caller, kind, offset, session):
    from database import Marker, Tag, SavedView
    from config import get_settings

    if kind == "sources":
        profile = get_settings().get_profile(caller.profile_id)
        return {
            "items": [
                {
                    "ref": access.ref(
                        caller,
                        "source",
                        hashlib.sha256(folder.path.encode()).hexdigest(),
                    ),
                    "name": Path(folder.path).name,
                }
                for folder in profile.folders
            ][offset : offset + 100]
        }
    if kind == "skills":
        from routes.settings import list_skills_endpoint

        return {
            "items": present(caller, await list_skills_endpoint())[
                offset : offset + 100
            ]
        }
    if kind == "formats":
        return {
            "upload": [
                "png",
                "jpg",
                "jpeg",
                "webp",
                "gif",
                "svg",
                "mp4",
                "webm",
                "mov",
                "avi",
                "mkv",
                "mp3",
                "wav",
                "flac",
                "aac",
                "m4a",
                "ogg",
            ],
            "download": ["original", "bundle"],
            "preview": [
                "png",
                "jpg",
                "jpeg",
                "webp",
                "gif",
                "svg",
                "md",
                "txt",
                "json",
            ],
        }
    model = {"markers": Marker, "tags": Tag, "saved_views": SavedView}[kind]
    rows = list(
        (
            await session.scalars(
                select(model).order_by(model.id).offset(offset).limit(100)
            )
        ).all()
    )
    return {
        "items": present(
            caller,
            [row.to_dict() for row in rows],
            {"markers": "marker", "tags": "tag", "saved_views": "view"}[kind],
        ),
        "next_offset": offset + 100 if len(rows) == 100 else None,
    }


def _where(exc):
    import os, traceback

    frames = traceback.extract_tb(exc.__traceback__)
    return f"{os.path.basename(frames[-1].filename)}:{frames[-1].lineno}" if frames else "?"


def _public_reason(exc):
    import re

    text = str(exc).strip() or type(exc).__name__
    text = re.sub(r"(/[\w.\-]+){2,}", "<path>", text)
    return text[:300]


async def execute_tools(caller, args, session, chat, job):
    from agent.v2.code_runtime import StimmaSDK, ToolResult
    from agent.v2.workspace import get_workspace_dir, get_project_workspace
    from .jobs import check_execution

    sdk = StimmaSDK(
        session=session,
        chat_id=chat.id,
        workspace_dir=get_workspace_dir(chat.id, chat.project_id),
        project_workspace_dir=get_project_workspace(chat.project_id),
        interrupt_checker=check_execution,
        project_id=chat.project_id,
    )
    if args.get("batch") and args.get("chain"):
        raise McpError("invalid_arguments", "Choose a batch or a chain.")
    steps = [
        {
            "tool_ref": args["tool_ref"],
            "schema_version": args["schema_version"],
            "parameters": p,
        }
        for p in (args.get("batch") or [args["parameters"]])
    ]
    if args.get("chain"):
        steps.extend(args["chain"])
    manifest = {"items": [], **({"retry_of": args["_retry_of"]} if args.get("_retry_of") else {})}
    previous = None
    for index, step in enumerate(steps):
        identity = {
            "index": index,
            "original_index": args.get("_batch_indices", list(range(len(steps))))[index],
            **({"label": args["batch_labels"][index]} if "batch_labels" in args else {}),
        }
        check_execution()
        tool_id, _, descriptor = await tool_descriptor(caller, step["tool_ref"])
        if tool_version(descriptor) != step["schema_version"]:
            raise McpError(
                "schema_changed", "This tool's schema changed. Call tools_inspect again and use the new schema_version."
            )
        raw = dict(step["parameters"])
        if step.get("input_from_previous"):
            if not previous:
                raise McpError(
                    "missing_input", "The previous step did not produce media."
                )
            field = step["input_from_previous"]
            schema = descriptor.parameter_schema.get("properties", {}).get(field, {})
            if "x-accept-media" not in schema:
                raise McpError(
                    "invalid_arguments",
                    "Previous output must bind to a declared media parameter.",
                )
            raw[field] = [previous] if schema.get("type") == "array" else previous
        parameters = await tool_parameters(caller, descriptor, raw, session)
        try:
            output = await sdk._dispatch_tool(tool_id, _params_dict=parameters)
            if isinstance(output, ToolResult):
                saved = await sdk.library.save(output)
                previous = access.ref(caller, "media", saved["media_id"])
                output = present(caller, saved, "asset")
            else:
                output = present(caller, output)
            manifest["items"].append(
                {**identity, "state": "succeeded", "output": output}
            )
        except Exception as exc:
            from agent.v2.tool_permission_gate import ToolPermissionDenied

            known = isinstance(exc, ToolPermissionDenied)
            code = "forbidden" if known else "execution_outcome_unknown"
            log.warning(
                "MCP tools_run item failed",
                tool=tool_id,
                index=index,
                error=type(exc).__name__,
                location=_where(exc),
            )
            manifest["items"].append(
                {
                    **identity,
                    "state": "failed" if known else "interrupted",
                    "error": {
                        "code": code,
                        # The reason, with server paths removed, so the caller
                        # can fix its call instead of guessing. An unknown
                        # outcome still means: do not simply resubmit.
                        "message": _public_reason(exc)
                        + ("" if known else " Check the job's retained results before running this again."),
                    },
                }
            )
            job.result_json = json.dumps(manifest)
            await session.commit()
            if args.get("chain") or not known:
                break
        job.result_json = json.dumps(manifest)
        await session.commit()
    return manifest
