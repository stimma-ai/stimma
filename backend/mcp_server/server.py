"""Official MCP SDK transport with an immutable authenticated profile context."""

from __future__ import annotations
import json
import os
import traceback
from contextlib import asynccontextmanager
from urllib.parse import urlparse
import jsonschema
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import Tool, ToolAnnotations, TextContent, CallToolResult
from starlette.requests import Request
from starlette.responses import JSONResponse
from core.logging import get_logger
from core.profile_context import ProfileScope
from database_registry import get_database_registry
from .access import access, McpError
from . import jobs, workspace
from .operations import descriptors, FAMILIES, ACCESS_HELP

from .logging import protect_sdk_logs

protect_sdk_logs()

server = Server(
    "Stimma",
    instructions="This server is one Stimma profile: its media library, generation tools, projects, boards and chats. "
    "Use tools_search, tools_inspect and tools_run when you know the operation; use agent_start when you want Stimma to choose tools and creatively iterate from a brief. "
    "Both return a job. Poll jobs_get until a terminal state; never resubmit to check progress. "
    "If jobs_get reports input_required, the job is waiting on you: answer with interaction_respond (relay permission questions to the user). "
    "Results carry asset and media refs. Use media_read for a quick look and media_export for a download link that works with a plain GET or in a browser. "
    "Download original files into your project before using them elsewhere: download URLs expire and are not hosting URLs. "
    "To save an external edit, POST to upload_url with X-Stimma-Stage: true, then content_update with format file, source_ref for the uploaded bytes and source_refs for the library inputs you used."
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
    "Your own id for this request, any short unique string. If the response is lost, retry with the same value and you get the same result; use a new value for new work.",
    minLength=1,
    maxLength=128,
)
REF = string("Opaque reference returned by Stimma, e.g. asset:…, media:…, job:…. Copy it exactly; never invent one.")
TOOLS = {
    "workspace_get": (
        "Show which profile this connection is bound to and whether it needs a PIN (requires_pin). Also returns upload_url, a link for putting a local file into the library with a plain POST. Cheap; call it first.",
        obj({}),
        False,
    ),
    "access_open": (
        "Unlock a PIN-protected profile with a PIN the user gave you. Never guess or retry a rejected PIN. Not needed when workspace_get reports requires_pin false.",
        obj({"pin": string(maxLength=72)}),
        True,
    ),
    "access_lock": (
        "Lock this connection again and cancel any jobs it started. Only meaningful on a PIN-protected profile.",
        obj({}),
        True,
    ),
    "assets_get": (
        "Get full details for specific assets by ref.",
        obj({"refs": array(REF)}, ["refs"]),
        False,
    ),
    "catalog_get": (
        "List this profile's markers, tags, sources, skills, formats or saved views.",
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
        "Find generation tools available in this profile (text-to-image, image-to-image, video, audio…) by name or task type. Returns tool_refs for tools_inspect and tools_run.",
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
        "Get a tool's parameter schema and its schema_version. Call this before tools_run; the run needs that schema_version.",
        obj({"tool_ref": REF}, ["tool_ref"]),
        False,
    ),
    "tools_run": (
        "Run one generation tool with explicit parameters. Returns a job: poll jobs_get until succeeded or failed. If the state is input_required (usually a permission question), answer it with interaction_respond or the job will wait forever. Results carry the new asset and media refs.",
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
        "Have Stimma's own agent do creative work from a brief: it picks tools, generates, reviews and iterates in a chat the user can see. Supply relevant context from your other systems in the brief. Returns a job; poll jobs_get and answer any input_required. The result identifies final outputs and includes the agent's completion summary and limitations. Prefer tools_run when you already know the exact tool and parameters.",
        obj(
            {
                "brief": string("What to make, in plain language, as you would tell a designer.", minLength=1, maxLength=32000),
                "media_refs": array(REF),
                "project_ref": REF,
                "request_key": KEY,
            },
            ["brief", "request_key"],
        ),
        True,
    ),
    "agent_continue": (
        "Send a follow-up message to a chat started by agent_start, once its current turn has finished.",
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
        "Get a job's state and result. Delegated results contain outputs explicitly marked final by the agent, a summary including reported limitations, and shortfalls detected from the requested count. Succeeded means execution ended, not creative approval. Terminal states include succeeded, failed, cancelled, interrupted and control_changed. When state is input_required, answer with interaction_respond; the job does not continue until you do. Use next_cursor as after to read only new events.",
        obj(
            {"job_ref": REF, "after": {"type": "integer", "minimum": 0, "default": 0}},
            ["job_ref"],
        ),
        False,
    ),
    "jobs_cancel": (
        "Cancel a job. Work a provider already finished is not undone or refunded.",
        obj({"job_ref": REF}, ["job_ref"]),
        True,
    ),
    "interaction_respond": (
        "Answer the question a job is waiting on (the interaction in jobs_get). For a permission request, ask the user and relay their decision as approved true/false. For a choice, give choice_indices. For a free-text question, give answer. Copy job_ref, controller_version and interaction_ref from the latest jobs_get.",
        obj(
            {
                "job_ref": REF,
                "controller_version": {"type": "integer", "minimum": 1},
                "interaction_ref": REF,
                "version": {"const": 1, "description": "Optional; always 1."},
                "response": obj(
                    {
                        "approved": {"type": "boolean", "description": "For permission questions: the user's decision."},
                        "answer": string("For free-text questions.", maxLength=32000),
                        "choice_indices": array({"type": "integer", "minimum": 0}),
                    }
                ),
                "request_key": KEY,
            },
            [
                "job_ref",
                "controller_version",
                "interaction_ref",
                "response",
                "request_key",
            ],
        ),
        True,
    ),
    "media_read": (
        "Look at media inline: an image preview (up to 1024px) or a small text document. For the full-resolution file use media_export.",
        obj({"ref": REF}, ["ref"]),
        False,
    ),
    "media_export": (
        "Get a download link for the original file (a ZIP for a directory). The link needs no key or headers: curl -o it, or open it in a browser. It is bound to this connection and stops working at the UTC time in its expires parameter (4 hours); nothing is written to disk for you.",
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
            "description": "unattended: the agent avoids asking questions where it can. Tool permission requests still arrive via jobs_get either way.",
        },
    }
)
TOOLS["tools_options"] = (
    "Search the allowed values of a tool parameter that has many options (models, LoRAs, presets…).",
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
    "source_refs": {
        **array(REF),
        "description": "Library inputs used to make this content, in source order. Independent of source_ref, which supplies the file bytes. Omit to use source_ref as the provenance source.",
    },
    "note": string("What you did and why, in one line, e.g. 'Desaturated with ImageMagick for the print version'. Shown in the asset's lineage and version history.", maxLength=500),
    "target_asset_ref": REF,
    "expected_current_revision": REF,
    "project_ref": REF,
    "request_key": KEY,
}
content_variants = [
    obj(
        {**content_common, "format": {"const": "file"}},
        ["format", "source_ref", "request_key"],
    ),
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
    "Save content as an asset or revision. Use format file and source_ref to save uploaded image/video/audio/SVG media without re-encoding (SVG retains normal sanitization). Stage an upload with X-Stimma-Stage: true to avoid an intermediate library asset. source_refs names the original library inputs used in an external edit or composite; note explains the change. Format image applies resize/crop/rotate/flip transforms. SVG/Markdown/layout accept text. To revise, pass target_asset_ref and its expected_current_revision; otherwise create a new asset. Always give a note.",
    {"type": "object", "oneOf": content_variants},
    True,
)

TOOLS["tools_run"][1]["properties"].update(
    {
        "batch": array({"type": "object"}, 200),
        "batch_labels": {**array(string("Your label for this batch item, e.g. France.", maxLength=200), 200), "description": "Optional labels in the same order and number as batch. Returned on successes, failures and retries; labels are never sent to the generation tool."},
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
    "Retry the failed items of a tools_run batch. Items that succeeded are kept; items whose outcome is unknown are not retried.",
    obj({"job_ref": REF, "request_key": KEY}, ["job_ref", "request_key"]),
    True,
)

_catalog = None


def catalog():
    global _catalog
    if _catalog is None:
        result = descriptors()
        from .operations import _strip_titles

        for name, (description, schema, write) in TOOLS.items():
            result.append(
                Tool(
                    name=name,
                    description=description,
                    inputSchema=_strip_titles(schema),
                    annotations=ToolAnnotations(
                        readOnlyHint=not write,
                        destructiveHint=write,
                        idempotentHint=name != "access_open",
                        openWorldHint=name
                        in ("agent_start", "agent_continue", "tools_run"),
                    ),
                )
            )
        for name, binding, description in [
            (
                "assets_query",
                workspace.query_binding,
                "Find and count library assets. Scope to a known project first. Use similar_to_text for visual appearance, caption_query for caption words and prompt_query for generation instructions. Tags, markers and board sections carry explicit organization or approval; similarity and recency do not imply approval. Preview a shortlist with media_read before choosing inputs.",
            ),
            (
                "lineage_get",
                workspace.lineage_binding,
                "See how a piece of media was made: its sources, the tool and parameters used, and what was derived from it.",
            ),
        ]:
            result.append(
                Tool(
                    name=name,
                    description=description,
                    inputSchema=binding.schema(),
                    annotations=ToolAnnotations(readOnlyHint=True),
                )
            )
        _catalog = {tool.name: tool for tool in result}
    return _catalog


@server.list_tools()
async def list_tools():
    return list(catalog().values())


def coerce_scalars(value, schema):
    """Read "1" as 1 and "true" as true where the schema wants a number or bool.

    Assistants routinely quote numbers they copied out of a previous result.
    Rejecting `"version": "1"` teaches them nothing and stalls the job; the
    intent is unambiguous, so accept it. Anything else is left for the
    validator to name.
    """
    if not isinstance(schema, dict):
        return value
    if isinstance(value, dict) and isinstance(schema.get("properties"), dict):
        return {
            key: coerce_scalars(item, schema["properties"].get(key))
            for key, item in value.items()
        }
    if isinstance(value, list) and "items" in schema:
        return [coerce_scalars(item, schema["items"]) for item in value]
    if isinstance(value, str):
        kind = schema.get("type")
        const = schema.get("const")
        wants_int = kind == "integer" or (kind is None and isinstance(const, int) and not isinstance(const, bool))
        wants_number = kind == "number" or (kind is None and isinstance(const, float))
        wants_bool = kind == "boolean" or isinstance(const, bool)
        text = value.strip()
        if wants_int and text.lstrip("-").isdigit():
            return int(text)
        if wants_number:
            try:
                return float(text)
            except ValueError:
                return value
        if wants_bool and text.lower() in ("true", "false"):
            return text.lower() == "true"
    return value


async def dispatch(caller, name, arguments):
    if name not in catalog():
        raise McpError("unknown_tool", "Unknown tool.")
    arguments = coerce_scalars(arguments, catalog()[name].inputSchema)
    jsonschema.validate(arguments, catalog()[name].inputSchema)
    if name == "access_open":
        return await access.open(caller, arguments.get("pin"))
    if name == "access_lock":
        await jobs.revoke(caller.profile_id, caller.client_id)
        return access.status(caller)
    if name == "workspace_get":
        from config import get_settings

        from .transfers import upload_link, HOW_TO_UPLOAD

        profile = get_settings().get_profile(caller.profile_id)
        status = access.status(caller)
        result = {"profile_name": profile.name, "profile_id": profile.id, **status}
        if not status["locked"]:
            result["upload_url"] = upload_link(caller)
            result["how_to_upload"] = HOW_TO_UPLOAD
        return result
    access.require(caller, activity=name != "jobs_get")
    db = get_database_registry().get_database(caller.profile_id)
    args = dict(arguments)
    with ProfileScope(caller.profile_id):
        if name in ("agent_start", "tools_run", "content_update"):
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
            if binding.write:
                return await jobs.mutate(
                    caller,
                    name + ":" + binding.function,
                    key,
                    args,
                    lambda session: binding.run(caller, args, session),
                )
            async with db.async_session_maker() as session:
                return await binding.run(caller, args, session)
        async with db.async_session_maker() as session:
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
            if name in ("assets_query", "lineage_get"):
                binding = {
                    "assets_query": workspace.query_binding,
                    "lineage_get": workspace.lineage_binding,
                }[name]
                return await binding.run(caller, args, session)
            if name == "media_read":
                return await workspace.preview(caller, args["ref"], session)
            if name == "media_export":
                from .transfers import offer

                return await offer(caller, args["ref"], session)
    raise McpError("unknown_tool", "Unknown tool.")


log = get_logger(__name__)


def client_origin(request):
    """The origin the assistant reached us through, for URLs we hand back.

    Behind the desktop relay the request's own Host is the device's loopback
    listener, which the assistant cannot reach; the relay forwards the address
    it was called on instead.
    """
    host = request.headers.get("x-forwarded-host") or request.url.netloc
    scheme = request.headers.get("x-forwarded-proto") or request.url.scheme
    return f"{scheme}://{host}"


def schema_problem(exc):
    """Name the field and the constraint it broke, without echoing the input.

    Input values can include PINs, so only schema-side facts and key names
    appear here. "controller_version: must satisfy type \"integer\"" is what
    an assistant needs to fix its call; "does not match" is not.
    """
    where = "/".join(str(part) for part in exc.absolute_path) or "arguments"
    if exc.validator == "required":
        present = exc.instance if isinstance(exc.instance, dict) else {}
        missing = [key for key in exc.validator_value if key not in present]
        return f"{where}: missing required {', '.join(missing)}."
    if exc.validator == "additionalProperties":
        known = set(exc.schema.get("properties", {}))
        extra = sorted(k for k in exc.instance if k not in known)
        return f"{where}: unexpected {', '.join(extra)}."
    if exc.validator == "oneOf":
        # Action families: say which actions exist, or, when the action is
        # known, what is wrong inside that one variant. Dumping every variant
        # is not an error message.
        variants = exc.validator_value
        actions = {
            v.get("properties", {}).get("action", {}).get("const"): v for v in variants
        }
        actions.pop(None, None)
        chosen = exc.instance.get("action") if isinstance(exc.instance, dict) else None
        if actions and chosen not in actions:
            return f"{where}: unknown action; use one of {', '.join(actions)}."
        if chosen in actions:
            resolver = jsonschema.validators.validator_for(exc.schema)
            inner = resolver(
                {**actions[chosen], "$defs": exc.schema.get("$defs", {})}
            )
            first = next(iter(inner.iter_errors(exc.instance)), None)
            if first is not None:
                first.absolute_path.extendleft(reversed(list(exc.absolute_path)))
                return f"action {chosen}: " + schema_problem(first)
        return f"{where}: must match one of the {len(variants)} accepted shapes."
    return f"{where}: must satisfy {exc.validator} {json.dumps(exc.validator_value)}."


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
    except jsonschema.ValidationError as exc:
        # The repr contains the rejected input, including PINs. Never log it.
        result = {
            "code": "invalid_arguments",
            "message": "Arguments do not match the advertised schema. "
            + schema_problem(exc),
        }
    except Exception as exc:
        # Type and location only: exception messages can carry input values.
        # Without this line a failure is undiagnosable from either side.
        frame = traceback.extract_tb(exc.__traceback__)[-1]
        log.warning(
            "MCP tool failed",
            tool=name,
            error=type(exc).__name__,
            location=f"{os.path.basename(frame.filename)}:{frame.lineno}",
        )
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
            if (
                len(suffix) == 2
                and suffix[0] == "download"
                and request.method in ("GET", "HEAD")
            ):
                from .transfers import download

                with ProfileScope(profile_id):
                    response = await download(profile_id, suffix[1])
                    await response(scope, receive, send)
                return
            if len(suffix) == 2 and suffix[0] == "upload" and request.method == "POST":
                from .transfers import upload

                with ProfileScope(profile_id):
                    response = await upload(profile_id, suffix[1], request)
                    await response(scope, receive, send)
                return
            bearer = request.headers.get("authorization", "")
            if not bearer.startswith("Bearer ") or len(bearer) > 256:
                raise McpError(
                    "unauthorized", "Missing or invalid connection key. Create a connection in Stimma under Settings → MCP and send its key as a Bearer token."
                )
            caller = await access.authenticate(profile_id, bearer[7:])
            scope["mcp_caller"] = caller
            from .transfers import request_origin

            request_origin.set(client_origin(request))
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
