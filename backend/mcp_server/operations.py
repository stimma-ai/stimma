"""Typed, curated domain operations. No REST passthrough or arbitrary dispatch."""

from __future__ import annotations
import copy
import importlib
import inspect
import json
from dataclasses import dataclass
from typing import Any, get_type_hints
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from .access import access, McpError

ACCESS_HELP = " If locked, use access_open with a PIN explicitly supplied by the user; never guess. Retry a lost mutation response with the same request_key."

ID_KINDS = {
    "asset_id": "asset",
    "asset_ids": "asset",
    "source_asset_id": "asset",
    "media_id": "media",
    "media_ids": "media",
    "selected_media_ids": "media",
    "primary_media_id": "media",
    "parent_revision_id": "revision",
    "source_id": "media",
    "target_id": "media",
    "from_chatitem_id": "chat_item",
    "source_media_id": "media",
    "target_media_id": "media",
    "excluded_marker_ids": "marker",
    "excluded_tag_ids": "tag",
    "excluded_project_ids": "project",
    "revision_id": "revision",
    "current_revision_id": "revision",
    "expected_revision_id": "revision",
    "board_id": "board",
    "board_ids": "board",
    "project_id": "project",
    "project_ids": "project",
    "chat_id": "chat",
    "flow_id": "flow",
    "preset_id": "preset",
    "view_id": "view",
    "section_id": "section",
    "section_ids": "section",
    "target_section_id": "section",
    "board_section_id": "section",
    "destination_section_id": "section",
    "cover_asset_id": "asset",
    "cover_media_id": "media",
    "remove_tag_ids": "tag",
    "marker_id": "marker",
    "marker_ids": "marker",
    "tag_id": "tag",
    "tag_ids": "tag",
    "user_tool_id": "custom_tool",
    "item_id": "chat_item",
    "chat_item_id": "chat_item",
}
PRIVATE_FIELDS = {
    "_mcp_interaction_id",
    "_inprocess_request_id",
    "file_path",
    "folder_path",
    "source_path",
    "workspace_path",
    "workspace_dir",
    "pin",
    "pin_hash",
    "credential_hash",
    "agent_tool_config",
    "tool_config",
    "folders",
    "excluded_folders",
    "execution_state",
    "original_chatitem_id",
    "generation_settings",
    "raw_metadata",
    "lineage_trace",
    "llm_trace",
    "thinking",
    "reasoning",
}
NESTED_KINDS = {
    "asset": "asset",
    "revision": "revision",
    "board": "board",
    "project": "project",
    "chat": "chat",
    "flow": "flow",
    "preset": "preset",
    "assets": "asset",
    "revisions": "revision",
    "media": "media",
    "boards": "board",
    "sections": "section",
    "projects": "project",
    "chats": "chat",
    "flows": "flow",
    "presets": "preset",
    "markers": "marker",
    "tags": "tag",
}


def present(caller, value, kind=None):
    value = jsonable_encoder(value)
    if isinstance(value, list):
        return [present(caller, item, kind) for item in value]
    if not isinstance(value, dict):
        return value
    output = {}
    if value.get("updated_at") is not None:
        output["version"] = value["updated_at"]
    for key, item in value.items():
        if key in ("generation_metadata", "item_metadata") and isinstance(item, str):
            try:
                item = json.loads(item)
            except ValueError:
                continue
        if key in PRIVATE_FIELDS or key.endswith("_path") or key.endswith("_dir"):
            continue
        entity = ID_KINDS.get(key) or (kind if key == "id" else None)
        if entity and item is not None:
            if isinstance(item, list):
                output[key] = [access.ref(caller, entity, ident) for ident in item]
            elif isinstance(item, (str, int)):
                output[key] = access.ref(caller, entity, item)
            else:
                output[key] = present(caller, item, entity)
        else:
            output[key] = present(caller, item, NESTED_KINDS.get(key, kind))
    return output


def decode(caller, value, key=None, schema=None, definitions=None):
    schema, definitions = schema or {}, definitions or {}
    if "$ref" in schema:
        schema = definitions[schema["$ref"].rsplit("/", 1)[-1]]
    if "anyOf" in schema:
        schema = next((s for s in schema["anyOf"] if s.get("type") != "null"), {})
        if "$ref" in schema:
            schema = definitions[schema["$ref"].rsplit("/", 1)[-1]]
    if isinstance(value, dict):
        return {
            k: decode(
                caller, v, k, schema.get("properties", {}).get(k, {}), definitions
            )
            for k, v in value.items()
        }
    kind = ID_KINDS.get(key)
    if kind and value is not None:

        def resolve(ref):
            identifier = access.resolve(caller, ref, kind)
            return int(identifier) if identifier.isdigit() else identifier

        result = (
            [resolve(v) for v in value] if isinstance(value, list) else resolve(value)
        )
        if schema.get("type") == "string":
            return (
                ",".join(map(str, result)) if isinstance(result, list) else str(result)
            )
        return result
    if isinstance(value, list):
        return [
            decode(caller, v, schema=schema.get("items", {}), definitions=definitions)
            for v in value
        ]
    return value


def public_schema(schema):
    schema = copy.deepcopy(schema)

    def visit(node, key=None):
        if not isinstance(node, dict):
            return
        if key in ID_KINDS:
            nullable = any(x.get("type") == "null" for x in node.get("anyOf", []))
            many = (
                node.get("type") == "array"
                or key.endswith("_ids")
                or any(x.get("type") == "array" for x in node.get("anyOf", []))
            )
            node.clear()
            node.update(
                {"type": "array", "items": {"type": "string"}, "maxItems": 200}
                if many
                else {"type": ["string", "null"] if nullable else "string"}
            )
            node["description"] = (
                f"Opaque {ID_KINDS[key]} reference returned by Stimma; never a numeric database ID."
            )
            return
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            for k in list(node["properties"]):
                if k in PRIVATE_FIELDS or (
                    node.get("title") == "FlowUpdateRequest" and k == "inputs"
                ):
                    node["properties"].pop(k)
                    if k in node.get("required", []):
                        node["required"].remove(k)
                else:
                    visit(node["properties"][k], k)
        for k in ("$defs",):
            for child in node.get(k, {}).values():
                visit(child)
        for k in ("anyOf", "oneOf", "allOf"):
            for child in node.get(k, []):
                visit(child, key)
        if isinstance(node.get("items"), dict):
            visit(node["items"])

    visit(schema)
    return schema


@dataclass
class Binding:
    module: str
    function: str
    kind: str | None
    write: bool = False
    _model: Any = None
    _fn: Any = None

    def load(self):
        if self._model:
            return
        self._fn = getattr(
            importlib.import_module("routes." + self.module), self.function
        )
        types = get_type_hints(self._fn)
        fields = {}
        for name, param in inspect.signature(self._fn).parameters.items():
            if name == "session":
                continue
            annotation = types.get(name, Any)
            default = param.default
            if default is inspect.Parameter.empty:
                default = ...
            if isinstance(default, FieldInfo):
                default = copy.copy(default)
            fields[name] = annotation, default
        self._model = create_model(
            "Mcp_" + self.function, __config__=ConfigDict(extra="forbid"), **fields
        )

    def schema(self):
        self.load()
        schema = public_schema(self._model.model_json_schema())
        if self.function == "browse_assets":
            for name in ("source_refs", "excluded_source_refs"):
                schema["properties"][name] = {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 100,
                }
        if self.function == "restore_asset_revision_route":
            schema["properties"]["expected_current_revision"] = {"type": "string"}
            schema.setdefault("required", []).append("expected_current_revision")
        if self.function == "update_flow_program":
            schema["properties"]["program_version"] = {
                "type": "string",
                "description": "SHA256 version returned by flows_get program.",
            }
            schema.setdefault("required", []).append("program_version")
        return schema

    async def run(self, caller, args, session):
        self.load()
        args = dict(args)
        if self.function == "browse_assets":
            from config import get_settings

            profile = get_settings().get_profile(caller.profile_id)
            for public, internal in [
                ("source_refs", "folders"),
                ("excluded_source_refs", "excluded_folders"),
            ]:
                if public in args:
                    import hashlib

                    folders = {
                        hashlib.sha256(folder.path.encode()).hexdigest(): folder.path
                        for folder in profile.folders
                    }
                    identifiers = [
                        access.resolve(caller, ref, "source")
                        for ref in args.pop(public)
                    ]
                    if any(identifier not in folders for identifier in identifiers):
                        raise McpError("not_found", "Source is unavailable.")
                    args[internal] = ",".join(
                        folders[identifier] for identifier in identifiers
                    )
        if self.function == "restore_asset_revision_route":
            from database import Asset

            asset_id = int(access.resolve(caller, args["asset_id"], "asset"))
            expected = int(
                access.resolve(
                    caller, args.pop("expected_current_revision"), "revision"
                )
            )
            asset = await session.get(Asset, asset_id)
            if not asset or asset.current_revision_id != expected:
                raise McpError(
                    "revision_conflict",
                    "The current revision changed; read it again before restoring.",
                )
        if self.function == "update_flow_program":
            import hashlib
            from flow_runtime import get_flow_program_path
            from database import Flow

            flow_id = int(access.resolve(caller, args["flow_id"], "flow"))
            flow = await session.get(Flow, flow_id)
            if not flow or flow.execution_state == "running":
                raise McpError(
                    "control_changed",
                    "Pause the Flow in Stimma before editing its program.",
                )
            expected = args.pop("program_version")
            path = get_flow_program_path(flow_id)
            actual = hashlib.sha256(
                (path.read_text() if path.exists() else "").encode()
            ).hexdigest()
            if actual != expected:
                raise McpError(
                    "revision_conflict",
                    "The Flow program changed. Read it again before editing.",
                )
        original = self._model.model_json_schema()
        parsed = self._model.model_validate(
            decode(caller, args, schema=original, definitions=original.get("$defs", {}))
        )
        kwargs = {name: getattr(parsed, name) for name in type(parsed).model_fields}
        if "session" in inspect.signature(self._fn).parameters:
            kwargs["session"] = session
        return present(caller, await self._fn(**kwargs), self.kind)


# Each action is explicitly selected and independently schema-validated. Settings,
# filesystem, provider credentials and raw execution routes are never registered.
FAMILIES: dict[str, tuple[str, dict[str, Binding]]] = {}


def family(name, description, module, kind, reads=(), writes=()):
    bindings = {}
    for write, entries in [(False, reads), (True, writes)]:
        for action, fn in entries:
            bindings[action] = Binding(module, fn, kind, write)
    FAMILIES[name] = description, bindings


family(
    "boards_get",
    "Inspect boards, sections and membership. Removing membership preserves Assets.",
    "boards",
    "board",
    [("list", "get_boards"), ("detail", "get_board")],
)
family(
    "boards_update",
    "Organize boards and sections with explicit membership operations.",
    "boards",
    "board",
    writes=[
        ("create", "create_board"),
        ("update", "update_board"),
        ("trash", "delete_board"),
        ("restore", "restore_board"),
        ("section_create", "create_board_section"),
        ("section_update", "update_board_section"),
        ("section_delete", "delete_board_section"),
        ("section_reorder", "reorder_board_sections"),
        ("add", "add_board_items"),
        ("remove", "bulk_remove_board_items"),
        ("move", "bulk_move_board_items"),
    ],
)
family(
    "projects_get",
    "Inspect projects and their workspace context.",
    "projects",
    "project",
    [("list", "list_projects"), ("detail", "get_project")],
)
family(
    "projects_update",
    "Create or edit project context and model choices. Tool permissions cannot be widened.",
    "projects",
    "project",
    writes=[
        ("create", "create_project"),
        ("update", "update_project"),
        ("delete", "delete_project"),
    ],
)
family(
    "saved_views_get",
    "Read saved browser filters.",
    "saved_views",
    "view",
    [("list", "get_saved_views"), ("detail", "get_saved_view")],
)
family(
    "saved_views_update",
    "Save and organize browser filter definitions.",
    "saved_views",
    "view",
    writes=[
        ("create", "create_saved_view"),
        ("update", "update_saved_view"),
        ("delete", "delete_saved_view"),
        ("reorder", "reorder_saved_view"),
    ],
)
family(
    "presets_get",
    "Inspect saved tool settings without executing them or changing usage.",
    "presets",
    "preset",
    [("list", "list_presets"), ("detail", "get_preset"), ("stats", "get_preset_stats")],
)
family(
    "presets_update",
    "Create, edit, duplicate or remove tool presets.",
    "presets",
    "preset",
    writes=[
        ("create", "create_preset"),
        ("update", "update_preset"),
        ("delete", "delete_preset"),
        ("duplicate", "duplicate_preset"),
    ],
)
family(
    "revisions_list",
    "Inspect immutable saved revisions of an Asset.",
    "assets",
    "revision",
    [("list", "list_asset_revisions")],
)
family(
    "revisions_restore",
    "Restore a historical revision as the current saved revision.",
    "assets",
    "asset",
    writes=[("restore", "restore_asset_revision_route")],
)
family(
    "assets_trash",
    "Move Assets to Trash without immediately deleting their files.",
    "assets",
    "asset",
    writes=[("trash", "trash_assets")],
)
family(
    "assets_restore",
    "Restore trashed Assets.",
    "assets",
    "asset",
    writes=[("restore", "restore_assets")],
)
family(
    "assets_update",
    "Update Asset expiration, project membership or explicitly promote retained contextual media.",
    "assets",
    "asset",
    writes=[
        ("clear_expiration", "clear_asset_expiration"),
        ("add_project", "add_assets_to_project"),
        ("remove_project", "remove_asset_from_project"),
        ("promote", "promote_contextual_media"),
    ],
)
family(
    "markers_update",
    "Explicit marker assignment or removal. Inspect the catalog first; unknown markers are not created.",
    "assets",
    "asset",
    writes=[("assign", "bulk_asset_markers")],
)
family(
    "tags_update",
    "Add or remove user tags on Assets.",
    "assets",
    "asset",
    writes=[("assign", "bulk_asset_tags")],
)
family(
    "containers_get",
    "Inspect container members, preserving linked Asset versus embedded Media semantics.",
    "assets",
    "asset",
    [("members", "container_member_summary")],
)
family(
    "containers_update",
    "Promote container members or explode the container; exploding trashes the container.",
    "assets",
    "asset",
    writes=[
        ("promote", "promote_container_members"),
        ("explode", "explode_container_asset"),
    ],
)
family(
    "assets_facets",
    "Count matches by browser facet without an agent.",
    "assets",
    None,
    [("counts", "get_asset_filter_counts"), ("keywords", "get_asset_top_keywords")],
)
family(
    "contextual_media_get",
    "Inspect retained chat, Flow and editor intermediates without promoting them into All Assets.",
    "assets",
    "media",
    [("list", "list_contextual_media")],
)
family(
    "chats_get",
    "Read visible chat history or list chats. Execution and private model traces are separate.",
    "chats",
    "chat",
    [("list", "list_chats"), ("detail", "get_chat")],
)
family(
    "chats_update",
    "Manage chat metadata or fork an existing chat; these operations do not start the agent.",
    "chats",
    "chat",
    writes=[
        ("create", "create_chat"),
        ("update", "update_chat"),
        ("fork", "fork_chat"),
        ("branch", "branch_chat"),
        ("trash", "delete_chat"),
        ("restore", "restore_chat"),
    ],
)
family(
    "flows_get",
    "Inspect reusable Flow definitions. Use flows_run for known workflows or delegate authoring to agent_start.",
    "flows",
    "flow",
    [
        ("list", "list_flows"),
        ("detail", "get_flow"),
        ("program", "get_flow_program"),
        ("equations", "list_equations"),
        ("trace", "get_equation_trace"),
    ],
)
family(
    "flows_update",
    "Create, fork or edit a reusable Flow. Program changes can invalidate and resume computation.",
    "flows",
    "flow",
    writes=[
        ("create", "create_flow"),
        ("fork", "fork_flow"),
        ("update", "update_flow"),
        ("program", "update_flow_program"),
        ("trash", "delete_flow"),
        ("restore", "restore_flow"),
    ],
)
family(
    "custom_tools_get",
    "Inspect profile-owned tools frozen from Flows.",
    "user_tools",
    "custom_tool",
    [
        ("list", "list_user_tools"),
        ("detail", "get_user_tool"),
        ("defaults", "freeze_defaults"),
    ],
)
family(
    "custom_tools_update",
    "Freeze a Flow or edit, refresh and remove its custom tool definition.",
    "user_tools",
    "custom_tool",
    writes=[
        ("freeze", "freeze_flow"),
        ("update", "patch_user_tool"),
        ("resync", "resync_user_tool"),
        ("delete", "delete_user_tool"),
    ],
)


def descriptors():
    from mcp.types import Tool, ToolAnnotations

    result = []
    for name, (description, variants) in FAMILIES.items():
        schemas = []
        definitions = {}
        write = any(b.write for b in variants.values())
        for action, binding in variants.items():
            schema = binding.schema()
            definitions.update(schema.pop("$defs", {}))
            schema["properties"]["action"] = {"const": action, "type": "string"}
            schema.setdefault("required", []).append("action")
            if binding.write:
                schema["properties"]["request_key"] = {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                }
                schema["required"].append("request_key")
            schemas.append(schema)
        result.append(
            Tool(
                name=name,
                description=description + ACCESS_HELP,
                inputSchema={"type": "object", "oneOf": schemas, "$defs": definitions},
                annotations=ToolAnnotations(
                    readOnlyHint=not write,
                    destructiveHint=write,
                    idempotentHint=write,
                    openWorldHint=False,
                ),
            )
        )
    return result


family(
    "assets_delete_permanently",
    "Preview or permanently delete trashed Assets using Stimma’s durable deletion service. Deleting files is irreversible.",
    "assets",
    "asset",
    [("preview", "get_asset_deletion_preview")],
    [("delete", "permanently_delete_assets")],
)
family(
    "share_publish",
    "Explicitly publish selected media using Stimma’s existing identity and content checks. Never needed for ordinary file delivery.",
    "share",
    "media",
    writes=[("publish", "share_media")],
)

family(
    "containers_create",
    "Create a set of linked Assets or embedded exact Media. Specify exactly one member list.",
    "media",
    "asset",
    writes=[("create", "create_set_from_media")],
)
