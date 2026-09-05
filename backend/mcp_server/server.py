"""Official MCP SDK transport with an immutable authenticated profile context."""

from __future__ import annotations
import json
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import jsonschema
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, ToolAnnotations, TextContent, CallToolResult
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.profile_context import ProfileScope
from database_registry import get_database_registry
from .access import access, McpError
from . import jobs, workspace
from .operations import descriptors, FAMILIES, ACCESS_HELP

from .logging import protect_sdk_logs

protect_sdk_logs()

server = Server(
    "Stimma",
    instructions="Operate the bound creative workspace. Use direct tools for known searches, organization and exact tool execution. Delegate creative judgment or iteration to agent_start. Inspect lineage before reproducing a multi-step result. Poll jobs_get for accepted work; never resubmit to get progress."
    + ACCESS_HELP,
)
manager = StreamableHTTPSessionManager(
    server,
    json_response=True,
    stateless=True,
    security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=False),
)
# The gateway below validates Origin before every request, including file transfer.


def obj(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def string(description="", **kw):
    return {"type": "string", "description": description, **kw}


def array(items, maximum=200):
    return {"type": "array", "items": items, "maxItems": maximum}


KEY = string(
    "Retry identity. Reuse after a lost response; change for intentionally new work.",
    minLength=1,
    maxLength=128,
)
REF = string("Opaque reference returned by Stimma.")
TOOLS = {
    "workspace_get": (
        "Inspect this connection’s lock status and bound profile.",
        obj({}),
        False,
    ),
    "access_open": (
        "Unlock this configured client with the PIN explicitly supplied by the user. Never guess or retry a failed PIN.",
        obj({"pin": string(maxLength=72)}),
        True,
    ),
    "access_lock": (
        "Lock this configured client across all its transport sessions and cancel its external jobs.",
        obj({}),
        True,
    ),
    "chat_history": (
        "Read visible chat messages and saved media references, with checkpoint references for a deliberate fork.",
        obj(
            {"chat_ref": REF, "after": {"type": "integer", "minimum": 0, "default": 0}},
            ["chat_ref"],
        ),
        False,
    ),
    "assets_get": (
        "Inspect exact Assets without changing them.",
        obj({"refs": array(REF)}, ["refs"]),
        False,
    ),
    "catalog_get": (
        "Discover marker/tag/source/skill/format catalogs.",
        obj(
            {
                "kind": {
                    "enum": [
                        "markers",
                        "tags",
                        "sources",
                        "skills",
                        "formats",
                        "saved_views",
                    ]
                },
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            },
            ["kind"],
        ),
        False,
    ),
    "tools_search": (
        "Find available permitted provider tools by description or task type.",
        obj(
            {
                "query": string(),
                "task_type": string(),
                "offset": {"type": "integer", "minimum": 0, "default": 0},
            }
        ),
        False,
    ),
    "tools_inspect": (
        "Inspect a tool’s current input/output schemas and version before executing it.",
        obj({"tool_ref": REF}, ["tool_ref"]),
        False,
    ),
    "tools_run": (
        "Run an exact provider tool without the planning agent. Uses normal spend permissions. Returns a durable job; poll jobs_get.",
        obj(
            {
                "tool_ref": REF,
                "schema_version": string(),
                "parameters": {"type": "object"},
                "project_ref": REF,
                "request_key": KEY,
            },
            ["tool_ref", "schema_version", "parameters", "request_key"],
        ),
        True,
    ),
    "agent_start": (
        "Delegate creative judgment, technique selection, visual review or iteration to the existing Stimma agent. Creates a visible chat and durable job.",
        obj(
            {
                "brief": string(minLength=1, maxLength=32000),
                "media_refs": array(REF),
                "project_ref": REF,
                "request_key": KEY,
            },
            ["brief", "request_key"],
        ),
        True,
    ),
    "agent_continue": (
        "Continue the same delegated chat after its current turn. Follow-ups use ordinary permissions.",
        obj(
            {
                "job_ref": REF,
                "controller_version": {"type": "integer", "minimum": 1},
                "message": string(minLength=1, maxLength=32000),
                "request_key": KEY,
            },
            ["job_ref", "controller_version", "message", "request_key"],
        ),
        True,
    ),
    "jobs_get": (
        "Retrieve job status, visible events and outstanding questions. Polling does not extend PIN unlock.",
        obj(
            {"job_ref": REF, "after": {"type": "integer", "minimum": 0, "default": 0}},
            ["job_ref"],
        ),
        False,
    ),
    "jobs_cancel": (
        "Cancel external work. Cancellation is not a rollback or refund.",
        obj({"job_ref": REF}, ["job_ref"]),
        True,
    ),
    "interaction_respond": (
        "Answer the exact outstanding question. Put permission questions to the human; this server trusts the connected assistant to relay their answer. No blanket approval.",
        obj(
            {
                "job_ref": REF,
                "controller_version": {"type": "integer", "minimum": 1},
                "interaction_ref": REF,
                "version": {"const": 1},
                "response": obj(
                    {
                        "approved": {"type": "boolean"},
                        "answer": string(maxLength=32000),
                        "choice_indices": array({"type": "integer", "minimum": 0}),
                    }
                ),
                "request_key": KEY,
            },
            [
                "job_ref",
                "controller_version",
                "interaction_ref",
                "version",
                "response",
                "request_key",
            ],
        ),
        True,
    ),
    "media_read": (
        "See a bounded preview or structured document directly in the tool result. Does not promote media or open an editor.",
        obj({"ref": REF}, ["ref"]),
        False,
    ),
    "media_export": (
        "Request an authenticated original or complete bundle download. The local bridge saves it on the assistant’s machine. Never publishes publicly.",
        obj({"ref": REF}, ["ref"]),
        False,
    ),
    "flows_run": (
        "Run a known Flow once with its inspected program version. Decisions remain pending until answered; no automatic first-candidate selection.",
        obj(
            {
                "flow_ref": REF,
                "program_version": string(),
                "inputs": {"type": "object"},
                "project_ref": REF,
                "request_key": KEY,
            },
            ["flow_ref", "program_version", "request_key"],
        ),
        True,
    ),
    "ui_context_get": (
        "Read the selection explicitly shared from Stimma’s context menu. Returns no ambient desktop state; snapshots expire after ten minutes.",
        obj({}),
        False,
    ),
    "ui_open": (
        "Return a profile-aware link to review an entity in Stimma. Does not silently switch a desktop window.",
        obj({"ref": REF}, ["ref"]),
        False,
    ),
}

# References pin media at acceptance; labels and deliverables become ordinary
# task context for the existing agent, never an independent planning runtime.
TOOLS["agent_start"][1]["properties"].update(
    {
        "references": array(
            obj(
                {
                    "ref": REF,
                    "role": string(maxLength=80),
                    "note": string(maxLength=2000),
                },
                ["ref"],
            )
        ),
        "skills": array(string(), 50),
        "deliverables": obj(
            {
                "kind": string(maxLength=80),
                "count": {"type": "integer", "minimum": 1, "maximum": 1000},
                "width": {"type": "integer", "minimum": 1},
                "height": {"type": "integer", "minimum": 1},
                "formats": array(string(), 20),
                "preserve": string(maxLength=4000),
            }
        ),
        "interaction": {
            "enum": ["ask_when_needed", "unattended"],
            "default": "ask_when_needed",
        },
        "source_chat": obj(
            {"chat_ref": REF, "mode": {"const": "fork"}, "checkpoint_ref": REF},
            ["chat_ref", "mode", "checkpoint_ref"],
        ),
    }
)
TOOLS["tools_options"] = (
    "Search a tool’s paginated parameter options after inspecting its schema.",
    obj(
        {
            "tool_ref": REF,
            "parameter": string(),
            "query": string(maxLength=100),
            "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
        },
        ["tool_ref", "parameter", "query"],
    ),
    False,
)
transform = {
    "oneOf": [
        obj(
            {
                "action": {"const": "resize"},
                "width": {"type": "integer", "minimum": 1, "maximum": 16384},
                "height": {"type": "integer", "minimum": 1, "maximum": 16384},
            },
            ["action", "width", "height"],
        ),
        obj(
            {
                "action": {"const": "crop"},
                "box": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "minItems": 4,
                    "maxItems": 4,
                },
            },
            ["action", "box"],
        ),
        obj(
            {"action": {"const": "rotate"}, "degrees": {"enum": [90, 180, 270]}},
            ["action", "degrees"],
        ),
        obj({"action": {"enum": ["flip_horizontal", "flip_vertical"]}}, ["action"]),
    ]
}
content_common = {
    "source_ref": REF,
    "target_asset_ref": REF,
    "expected_current_revision": REF,
    "project_ref": REF,
    "request_key": KEY,
}
content_variants = [
    obj(
        {
            **content_common,
            "format": {"const": "image"},
            "transforms": array(transform, 20),
        },
        ["format", "source_ref", "transforms", "request_key"],
    ),
    obj(
        {
            **content_common,
            "format": {"enum": ["svg", "markdown"]},
            "text": string(maxLength=512000),
        },
        ["format", "text", "request_key"],
    ),
    obj(
        {
            **content_common,
            "format": {"const": "layout"},
            "files": array(
                obj(
                    {"name": string(maxLength=200), "text": string(maxLength=128000)},
                    ["name", "text"],
                ),
                100,
            ),
        },
        ["format", "files", "request_key"],
    ),
]
TOOLS["content_update"] = (
    "Save image transforms or a structured document. Supply target_asset_ref and expected_current_revision to revise an existing Asset; otherwise create a new Asset. Does not modify a working editor stack.",
    {"type": "object", "oneOf": content_variants},
    True,
)

TOOLS["assets_select"] = (
    "Snapshot all matching Assets and exact revisions for stable bulk work. New matches arriving later are excluded.",
    obj({"query": workspace.query_binding.schema()}, ["query"]),
    False,
)
TOOLS["selections_get"] = (
    "Read a page of a stable selection’s pinned targets. Any unlocked connection on this profile can recover it.",
    obj(
        {
            "selection_ref": REF,
            "offset": {"type": "integer", "minimum": 0, "default": 0},
        },
        ["selection_ref"],
    ),
    False,
)

TOOLS["tools_run"][1]["properties"].update(
    {
        "batch": array({"type": "object"}, 200),
        "chain": array(
            obj(
                {
                    "tool_ref": REF,
                    "schema_version": string(),
                    "parameters": {"type": "object"},
                    "input_from_previous": string(
                        "Media parameter receiving the previous step’s saved output."
                    ),
                },
                ["tool_ref", "schema_version", "parameters"],
            ),
            30,
        ),
    }
)
TOOLS["jobs_retry"] = (
    "Retry only explicitly failed items from a tool batch. Successful items are preserved; unknown dispatch outcomes are never automatically repeated.",
    obj({"job_ref": REF, "request_key": KEY}, ["job_ref", "request_key"]),
    True,
)

_catalog = None


def catalog():
    global _catalog
    if _catalog is None:
        result = descriptors()
        for name, (description, schema, write) in TOOLS.items():
            result.append(
                Tool(
                    name=name,
                    description=description
                    + (
                        ACCESS_HELP
                        if name not in ("access_open", "access_lock")
                        else ""
                    ),
                    inputSchema=schema,
                    annotations=ToolAnnotations(
                        readOnlyHint=not write,
                        destructiveHint=write,
                        idempotentHint=name != "access_open",
                        openWorldHint=name
                        in ("agent_start", "agent_continue", "tools_run", "flows_run"),
                    ),
                )
            )
        for name, binding, description in [
            (
                "assets_query",
                workspace.query_binding,
                "Find and count Assets using browser filters. Use this directly for known criteria, not an agent.",
            ),
            (
                "lineage_get",
                workspace.lineage_binding,
                "Inspect the bounded Media derivation graph before reproducing or varying a result.",
            ),
            (
                "entities_search",
                workspace.search_binding,
                "Search named chats, Flows, boards, projects and presets.",
            ),
        ]:
            result.append(
                Tool(
                    name=name,
                    description=description + ACCESS_HELP,
                    inputSchema=binding.schema(),
                    annotations=ToolAnnotations(readOnlyHint=True),
                )
            )
        _catalog = {tool.name: tool for tool in result}
    return _catalog


@server.list_tools()
async def list_tools():
    return list(catalog().values())


async def dispatch(caller, name, arguments):
    if name not in catalog():
        raise McpError("unknown_tool", "Unknown tool.")
    jsonschema.validate(arguments, catalog()[name].inputSchema)
    if name == "access_open":
        return await access.open(caller, arguments.get("pin"))
    if name == "access_lock":
        await jobs.revoke(caller.profile_id, caller.client_id)
        return access.status(caller)
    if name == "workspace_get":
        from config import get_settings

        profile = get_settings().get_profile(caller.profile_id)
        return {
            "profile_name": profile.name,
            "profile_id": profile.id,
            **access.status(caller),
            "connection_boundary": "configured client credential + profile",
            "transfer": "authenticated HTTP; packaged bridge handles local files",
        }
    access.require(caller, activity=name != "jobs_get")
    db = get_database_registry().get_database(caller.profile_id)
    args = dict(arguments)
    with ProfileScope(caller.profile_id):
        if name in ("agent_start", "tools_run", "flows_run", "content_update"):
            return await jobs.accept(caller, name, args.pop("request_key"), args)
        if name == "jobs_get":
            return await jobs.get(caller, args["job_ref"], args.get("after", 0))
        if name == "jobs_retry":
            return await jobs.retry(caller, args["job_ref"], args["request_key"])
        if name == "jobs_cancel":
            return await jobs.cancel(caller, args["job_ref"])
        if name in ("agent_continue", "interaction_respond"):
            response = args.get("response")
            if response is not None:
                response = {**response, "scope": "once"}
            return await jobs.control(
                caller,
                args["job_ref"],
                args["controller_version"],
                args["request_key"],
                message=args.get("message"),
                interaction_ref=args.get("interaction_ref"),
                response=response,
            )
        if name in FAMILIES:
            _, variants = FAMILIES[name]
            binding = variants[args.pop("action")]
            key = args.pop("request_key", None)
            if binding.write and name in (
                "custom_tools_update",
                "flows_update",
                "assets_delete_permanently",
                "share_publish",
                "containers_create",
            ):
                return await jobs.accept(
                    caller, f"bound:{name}:{arguments['action']}", key, args
                )
            if binding.write:
                return await jobs.mutate(
                    caller,
                    name + ":" + binding.function,
                    key,
                    args,
                    lambda session: binding.run(caller, args, session),
                )
            async with db.async_session_maker() as session:
                value = await binding.run(caller, args, session)
                if name == "flows_get" and binding.function == "get_flow_program":
                    import hashlib

                    value["program_version"] = hashlib.sha256(
                        value["code"].encode()
                    ).hexdigest()
                return value
        async with db.async_session_maker() as session:
            if name == "assets_select":
                from .selections import create

                return await create(caller, args["query"], session)
            if name == "selections_get":
                from .selections import read

                return await read(
                    caller, args["selection_ref"], args.get("offset", 0), session
                )
            if name == "chat_history":
                return await workspace.chat_history(
                    caller, args["chat_ref"], args.get("after", 0), session
                )
            if name == "assets_get":
                return await workspace.assets_get(caller, args["refs"], session)
            if name == "catalog_get":
                return await workspace.catalog(
                    caller, args["kind"], args.get("offset", 0), session
                )
            if name == "tools_search":
                return await workspace.tools_search(
                    caller,
                    args.get("query", ""),
                    args.get("task_type"),
                    args.get("offset", 0),
                    session,
                )
            if name == "tools_options":
                tool_id, _, _ = await workspace.tool_descriptor(
                    caller, args["tool_ref"]
                )
                from routes.tools import search_tool_options, SearchToolOptionsRequest

                return await search_tool_options(
                    SearchToolOptionsRequest(
                        full_tool_id=tool_id,
                        parameter=args["parameter"],
                        query=args["query"],
                        limit=args.get("limit", 50),
                    )
                )
            if name == "tools_inspect":
                return await workspace.tools_inspect(caller, args["tool_ref"])
            if name in ("assets_query", "entities_search", "lineage_get"):
                binding = {
                    "assets_query": workspace.query_binding,
                    "entities_search": workspace.search_binding,
                    "lineage_get": workspace.lineage_binding,
                }[name]
                return await binding.run(caller, args, session)
            if name == "media_read":
                return await workspace.preview(caller, args["ref"], session)
            if name == "media_export":
                from .transfers import offer

                return await offer(caller, args["ref"], session)
            if name == "ui_context_get":
                from .ui_context import read

                return read(caller)
            if name == "ui_open":
                kind = args["ref"].split(":", 1)[0]
                routes = {
                    "asset": "edit-image",
                    "board": "boards",
                    "project": "projects",
                    "chat": "chat",
                    "flow": "flows",
                }
                if kind not in routes:
                    raise McpError(
                        "unsupported_handoff", "This entity has no standalone UI route."
                    )
                identifier = access.resolve(caller, args["ref"], kind)
                return {
                    "path": f"/{routes[kind]}/{identifier}",
                    "profile_id": caller.profile_id,
                    "delivery": "link_only",
                }
    raise McpError("unknown_tool", "Unknown tool.")


@server.call_tool(validate_input=False)
async def call_tool(name, arguments):
    try:
        caller = server.request_context.request.scope["mcp_caller"]
        value = await dispatch(caller, name, arguments or {})
        if isinstance(value, list) and value and isinstance(value[0], (TextContent,)):
            return CallToolResult(content=value)
        from mcp.types import ImageContent

        if isinstance(value, list) and value and isinstance(value[0], ImageContent):
            return CallToolResult(content=value)
        payload = value if isinstance(value, dict) else {"items": value}
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(payload))],
            structuredContent=payload,
        )
    except McpError as exc:
        result = {"code": exc.code, "message": exc.message}
    except (jsonschema.ValidationError, ValueError):
        # ValidationError repr contains rejected input, including PINs. Never log it.
        result = {
            "code": "invalid_arguments",
            "message": "Arguments do not match the advertised schema.",
        }
    except Exception:
        result = {
            "code": "operation_failed",
            "message": "The operation failed. Inspect the workspace and retry only when safe.",
        }
    return CallToolResult(
        isError=True,
        content=[TextContent(type="text", text=json.dumps(result))],
        structuredContent=result,
    )


class Gateway:
    async def __call__(self, scope, receive, send):
        request = Request(scope, receive)
        parts = request.url.path.split("/")
        try:
            if parts[:3] != ["", "mcp", "profiles"]:
                raise ValueError()
            index = 2
            profile_id = parts[index + 1]
            suffix = parts[index + 2 :]
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
                raise McpError("forbidden_origin", "Origin is not allowed.")
            if (
                request.headers.get("x-profile-id")
                or request.query_params.get("profile")
                or request.headers.get("x-profile-pin")
                or request.query_params.get("pin")
            ):
                raise McpError(
                    "conflicting_profile",
                    "Use only the profile bound in the MCP endpoint.",
                )
            bearer = request.headers.get("authorization", "")
            if not bearer.startswith("Bearer ") or len(bearer) > 256:
                raise McpError(
                    "unauthorized", "Configure this assistant connection in Stimma."
                )
            caller = await access.authenticate(profile_id, bearer[7:])
            scope["mcp_caller"] = caller
            if suffix and suffix != [""]:
                from .transfers import handle

                with ProfileScope(profile_id):
                    response = await handle(caller, suffix, request)
                    await response(scope, receive, send)
                return
            await manager.handle_request(scope, receive, send)
        except (IndexError, ValueError):
            await JSONResponse({"error": "not_found"}, status_code=404)(
                scope, receive, send
            )
        except McpError as exc:
            status = (
                401
                if exc.code == "unauthorized"
                else 404
                if exc.code == "profile_disabled"
                else 403
            )
            await JSONResponse(
                {"error": exc.code, "message": exc.message}, status_code=status
            )(scope, receive, send)


@asynccontextmanager
async def lifespan():
    import asyncio

    async with manager.run():
        watcher = asyncio.create_task(jobs.watch_revocations())
        try:
            yield
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
    tasks = list(jobs._tasks.values())
    for task in tasks:
        task.cancel()
    import asyncio

    await asyncio.gather(*tasks, return_exceptions=True)
