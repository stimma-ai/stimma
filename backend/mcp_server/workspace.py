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

query_binding = Binding("assets", "browse_assets", "asset")
lineage_binding = Binding("media_files", "get_media_lineage_tree", "media")
search_binding = Binding("search", "global_search", None)


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
    # Provider schemas retain their own types. Only negotiated media fields may
    # resolve refs into server paths; arbitrary paths/URLs are never accepted.
    import jsonschema

    result = dict(parameters)
    for name, schema in (descriptor.parameter_schema.get("properties") or {}).items():
        if "x-accept-media" not in schema or name not in result:
            continue
        many = isinstance(result[name], list)
        values = result[name] if many else [result[name]]
        resolved = []
        for ref in values:
            media = await media_row(caller, ref, session)
            resolved.append(str(media.file_path))
        result[name] = resolved if many else resolved[0]
    jsonschema.validate(result, descriptor.parameter_schema)
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
            "This format requires a renderer or complete bundle export.",
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
                "transfer_required", "Download this document through the bridge."
            )
        return [TextContent(type="text", text=path.read_text())]
    raise McpError(
        "preview_unavailable",
        "Download this media through the bridge to inspect it locally.",
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


async def flow_candidate(caller, value, shape, session):
    """Expose typed media choices as read-only previews until the run ends."""
    from flow_dsl.shapes import Scalar, ListShape, DictShape, TupleShape

    if isinstance(shape, Scalar) and shape.kind == "media" and isinstance(value, int):
        row = await session.get(MediaItem, value)
        if row is None:
            return {"available": False}
        reference = (
            access.ref(
                caller, "context_media", json.dumps([row.id, row.ephemeral_run_id])
            )
            if row.ephemeral_run_id
            else access.ref(caller, "media", row.id)
        )
        return {"preview_ref": reference}
    if isinstance(shape, ListShape) and isinstance(value, list):
        return [
            await flow_candidate(caller, item, shape.element, session) for item in value
        ]
    if isinstance(shape, DictShape) and isinstance(value, dict):
        return {
            key: await flow_candidate(caller, item, shape.field_map.get(key), session)
            for key, item in value.items()
        }
    if isinstance(shape, TupleShape) and isinstance(value, (list, tuple)):
        return [
            await flow_candidate(
                caller,
                item,
                shape.elements[index] if index < len(shape.elements) else None,
                session,
            )
            for index, item in enumerate(value)
        ]
    return present(caller, value)


async def execute_flow(caller, args, session, chat):
    from database import Flow
    from flow_runtime import get_flow_program_path
    from flow_runtime.oneshot import run_flow_once
    from upload_service import UploadService
    from .jobs import check_execution

    flow_id = int(access.resolve(caller, args["flow_ref"], "flow"))
    flow = await session.get(Flow, flow_id)
    if not flow or flow.deleted_at:
        raise McpError("not_found", "Flow is unavailable.")
    program = get_flow_program_path(flow_id).read_text()
    if hashlib.sha256(program.encode()).hexdigest() != args["program_version"]:
        raise McpError("schema_changed", "Inspect the Flow program again.")

    async def ask(eq, inputs):
        import asyncio, uuid
        from database import ChatItem
        from agent.v2.tool_permission_gate import _PENDING

        request_id = f"mcp-flow:{caller.profile_id}:{uuid.uuid4().hex}"
        future = asyncio.get_running_loop().create_future()
        _PENDING[request_id] = future
        metadata = {
            "type": "mcp_flow",
            "prompt": eq.definition.get("instructions") or eq.key,
            "candidates": present(caller, inputs.get("candidates", []), "media"),
            "v2_tool_args": {"_inprocess_request_id": request_id},
            "decision_type": eq.definition.get("hitl_type"),
        }
        from database_registry import get_database_registry

        async with (
            get_database_registry()
            .get_database(caller.profile_id)
            .async_session_maker() as question_session
        ):
            from flow_dsl.shapes import ListShape

            shape = getattr(
                eq.definition.get("_dynamic", {}).get("candidates"), "shape", None
            )
            if isinstance(shape, ListShape):
                shape = shape.element
            metadata["candidates"] = [
                await flow_candidate(caller, candidate, shape, question_session)
                for candidate in inputs.get("candidates", [])
            ]
            if "asset" in inputs:
                metadata["asset"] = await flow_candidate(
                    caller,
                    inputs["asset"],
                    getattr(
                        eq.definition.get("_dynamic", {}).get("asset"), "shape", None
                    ),
                    question_session,
                )
            question_session.add(
                ChatItem(
                    chat_id=chat.id,
                    item_type="hitl_request",
                    item_metadata=json.dumps(metadata),
                )
            )
            await question_session.commit()
        try:
            response = await future
            check_execution()
            if eq.definition.get("hitl_type") == "approve":
                return bool(response.get("approved"))
            candidates = inputs.get("candidates", [])
            indices = response.get("choice_indices", [])
            if not indices or any(i < 0 or i >= len(candidates) for i in indices):
                raise McpError(
                    "invalid_selection", "Choose one or more advertised candidates."
                )
            selected = [candidates[i] for i in indices]
            return selected[0] if int(eq.definition.get("count", 1)) == 1 else selected
        finally:
            _PENDING.pop(request_id, None)

    output = await run_flow_once(
        flow_id=flow_id,
        program_text=program,
        inputs=args.get("inputs", json.loads(flow.inputs or "{}")),
        project_id=flow.project_id,
        hitl_resolver=ask,
    )
    results = []
    for name, value in output.outputs.items():
        for media in value.media:
            row, _ = await UploadService(caller.profile_id).upload_file(
                media.data, f"{name}.{media.file_format}", project_id=flow.project_id
            )
            results.append(
                {"name": name, "media_ref": access.ref(caller, "media", row.id)}
            )
        if not value.media:
            results.append({"name": name, "value": present(caller, value.value)})
    return {"outputs": results}


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
    manifest = {"items": []}
    previous = None
    for index, step in enumerate(steps):
        check_execution()
        tool_id, _, descriptor = await tool_descriptor(caller, step["tool_ref"])
        if tool_version(descriptor) != step["schema_version"]:
            raise McpError(
                "schema_changed", "Inspect the changed tool before starting new work."
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
                {"index": index, "state": "succeeded", "output": output}
            )
        except Exception as exc:
            from agent.v2.tool_permission_gate import ToolPermissionDenied

            known = isinstance(exc, ToolPermissionDenied)
            code = "forbidden" if known else "execution_outcome_unknown"
            manifest["items"].append(
                {
                    "index": index,
                    "state": "failed" if known else "interrupted",
                    "error": {
                        "code": code,
                        "message": "Execution stopped; inspect retained results before starting more work.",
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


async def chat_history(caller, reference, after, session):
    from database import Chat, ChatItem

    chat_id = int(access.resolve(caller, reference, "chat"))
    chat = await session.get(Chat, chat_id)
    if not chat or chat.deleted_at:
        raise McpError("not_found", "Chat is unavailable.")
    rows = (
        await session.scalars(
            select(ChatItem)
            .where(
                ChatItem.chat_id == chat_id,
                ChatItem.id > after,
                ChatItem.item_type.in_(
                    [
                        "user_message",
                        "assistant_message",
                        "media_display",
                        "hitl_request",
                        "hitl_response",
                        "error",
                    ]
                ),
            )
            .order_by(ChatItem.id)
            .limit(100)
        )
    ).all()
    return {
        "items": [
            present(
                caller,
                {
                    "id": row.id,
                    "type": row.item_type,
                    "text": row.message_text,
                    "media_ids": json.loads(row.media_ids or "[]"),
                    "asset_ids": json.loads(row.asset_ids or "[]"),
                },
                "chat_item",
            )
            for row in rows
        ],
        "next_cursor": rows[-1].id if rows else after,
    }
