"""Typed, curated domain operations. No REST passthrough or arbitrary dispatch."""

from __future__ import annotations
import copy
import importlib
import inspect
import json
import re
from dataclasses import dataclass
from typing import Any, get_type_hints
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, create_model
from pydantic.fields import FieldInfo
from pydantic_core import PydanticUndefined
from .access import access, McpError

ACCESS_HELP = " If a call returns profile_locked, the profile has a PIN: ask the user for it and call access_open. If a write's response is lost, retry it with the same request_key."

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
    "to_section_id": "section",
    "project_id": "project",
    "project_ids": "project",
    "chat_id": "chat",
    "flow_id": "flow",
    "parent_id": "flow",
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


PUBLIC_NAMES = {"q": "query"}

# Plain-language help for route fields whose names alone would make a model
# guess. Applied wherever the route's own model says nothing.
FIELD_DESCRIPTIONS = {
    "query": "Free-text search.",
    "page": "1-based page number.",
    "page_size": "Results per page.",
    "offset": "Skip this many results.",
    "limit": "Maximum results to return.",
    "after": "Only events after this cursor (from next_cursor).",
    "caption_query": "Match against the automatic image caption.",
    "prompt_query": "Match against the generation prompt.",
    "media_types": "Comma-separated: image, video, audio, document.",
    "excluded_media_types": "Comma-separated media types to leave out.",
    "resolutions": "Comma-separated size classes, e.g. 1k,2k,4k.",
    "keywords": "Comma-separated keywords the asset must have.",
    "excluded_keywords": "Comma-separated keywords to leave out.",
    "is_generated": "Only assets made by a generation tool.",
    "is_imported": "Only assets imported from files.",
    "is_unused": "Only assets not used as input elsewhere.",
    "has_project": "Only assets that belong to a project.",
    "tool_ids": "Comma-separated tool ids (provider:tool, as in tool details) that made the asset.",
    "excluded_tool_ids": "Comma-separated tool ids to leave out.",
    "created_after": "ISO date or datetime.",
    "created_before": "ISO date or datetime.",
    "show_expiring": "Only assets scheduled to expire.",
    "exclude_expiring": "Leave out assets scheduled to expire.",
    "similar_to": "Rank by visual similarity to this asset.",
    "similar_face_to": "Rank by face similarity to this asset.",
    "similar_to_text": "Rank by similarity to this text.",
    "similarity_threshold": "0-1; higher is stricter.",
    "min_mp": "Minimum megapixels.",
    "max_mp": "Maximum megapixels.",
    "random_seed": "Seed for a stable random ordering.",
    "keyword_limit": "How many top keywords to return.",
    "tag_limit": "How many top tags to return.",
    "tool_limit": "How many top tools to return.",
    "include_deleted": "Include trashed items.",
    "nsfw_override": "Publish even if flagged as adult content.",
    "hitl_policies": "Per-question policy for the frozen tool: which questions it may answer itself.",
    "output_map": "Which Flow outputs become the tool's outputs, by name.",
    "memory": "Long-lived notes the agent keeps for this project.",
    "direction": "up or down.",
    "filters": "The saved library filter, in the same shape as an assets_query call.",
    "pin": "The profile PIN the user gave you.",
    "add": "true to add, false to remove.",
}


def public_key(key):
    """What a model sees for a field: *_ref for ids that carry references,
    and a few plain names in place of abbreviations."""
    if key in PUBLIC_NAMES:
        return PUBLIC_NAMES[key]
    if key in ID_KINDS:
        if key.endswith("_ids"):
            return key[:-4] + "_refs"
        if key.endswith("_id"):
            return key[:-3] + "_ref"
    return key


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
            # Inputs ask for *_ref; outputs say *_ref. One vocabulary.
            name = public_key(key)
            if isinstance(item, list):
                output[name] = [access.ref(caller, entity, ident) for ident in item]
            elif isinstance(item, (str, int)):
                output[name] = access.ref(caller, entity, item)
            else:
                output[name] = present(caller, item, entity)
        else:
            # A null reference field keeps its public name too.
            output[public_key(key) if entity else key] = present(
                caller, item, NESTED_KINDS.get(key, kind)
            )
    media_id = value.get("id") if kind == "media" else value.get("media_id")
    if not isinstance(media_id, int) and isinstance(value.get("media"), dict):
        media_id = value["media"].get("id")
    if isinstance(media_id, int) and "download_url" not in output:
        # The file itself, one GET away, wherever media shows up: asset
        # details, job results, lineage. Nothing to look up afterwards.
        from .transfers import download_link
        from .access import McpError

        try:
            output["download_url"] = download_link(caller, media_id)[0]
        except McpError:
            pass
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
                f"Opaque {ID_KINDS[key]} reference returned by Stimma, copied exactly; never a number."
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


def _strip_titles(node):
    if isinstance(node, dict):
        return {
            k: _strip_titles(v)
            for k, v in node.items()
            if k != "title" and not (k == "description" and v == "")
        }
    if isinstance(node, list):
        return [_strip_titles(v) for v in node]
    return node


@dataclass
class Binding:
    module: str
    function: str
    kind: str | None
    write: bool = False
    _model: Any = None
    _fn: Any = None
    _nested: Any = None
    _public_to_internal: Any = None

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
        """The schema a model sees: one flat object per action.

        The route's ``request`` body model is inlined, id fields are named
        ``*_ref`` (they carry references, never numbers) and Pydantic titles,
        which are internal function and class names, are dropped. They were
        the loudest words in the schema and they misled: a model shown
        ``Mcp_add_board_items`` next to ``action: add`` invents ``add_items``.
        """
        self.load()
        schema = self._public_schema()
        definitions = schema.pop("$defs", {})
        # Route bodies arrive as one nested model under request/data/body.
        # Inline them: a model should see fields, not a wrapper to guess at.
        self._nested = {}
        for wrapper in list(schema["properties"]):
            prop = schema["properties"][wrapper]
            if "$ref" not in prop:
                continue
            body = definitions.get(prop["$ref"].rsplit("/", 1)[-1], {})
            if body.get("type") != "object" or "properties" not in body:
                continue
            if set(body["properties"]) & (set(schema["properties"]) - {wrapper}):
                continue
            schema["properties"].pop(wrapper)
            if wrapper in schema.get("required", []):
                schema["required"].remove(wrapper)
            self._nested[wrapper] = set(body["properties"])
            for key, inner in body["properties"].items():
                schema["properties"][key] = inner
            schema.setdefault("required", []).extend(body.get("required", []))
        self._public_to_internal = {}
        renamed = {}
        for key, prop in schema["properties"].items():
            name = public_key(key)
            self._public_to_internal[name] = key
            if isinstance(prop, dict) and not prop.get("description") and name in FIELD_DESCRIPTIONS:
                prop["description"] = FIELD_DESCRIPTIONS[name]
            renamed[name] = prop
        schema["properties"] = renamed
        schema["required"] = [public_key(k) for k in schema.get("required", [])]
        still_used = {
            m.rsplit("/", 1)[-1] for m in re.findall(r'"#/\$defs/([^"]+)"', json.dumps(schema))
        }
        if still_used:
            schema["$defs"] = {k: v for k, v in definitions.items() if k in still_used}
        return _strip_titles(schema)

    def unflatten(self, args):
        """Public (flat, *_ref) arguments back to the route's own shape."""
        self.schema()
        internal = {wrapper: {} for wrapper in self._nested}
        for key, value in args.items():
            name = self._public_to_internal.get(key, key)
            for wrapper, keys in self._nested.items():
                if name in keys:
                    internal[wrapper][name] = value
                    break
            else:
                internal[name] = value
        return internal

    def _public_schema(self):
        schema = public_schema(self._model.model_json_schema())
        if self.function == "browse_assets":
            for name in ("source_refs", "excluded_source_refs"):
                schema["properties"][name] = {
                    "type": "array",
                    "items": {"type": "string"},
                    "maxItems": 100,
                }
        return schema

    async def run(self, caller, args, session):
        self.load()
        args = self.unflatten(dict(args))
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
    """Entries are (action, route function) or (action, route function, kind)
    when an action returns a different entity than the family's own."""
    bindings = {}
    for write, entries in [(False, reads), (True, writes)]:
        for entry in entries:
            action, fn, *rest = entry
            bindings[action] = Binding(module, fn, rest[0] if rest else kind, write)
    FAMILIES[name] = description, bindings


family(
    "boards_get",
    "Inspect boards, their sections and what is on them.",
    "boards",
    "board",
    [("list", "get_boards"), ("detail", "get_board")],
)
family(
    "boards_update",
    "Organize work on boards: create, rename, trash or restore a board; create, rename, reorder or delete its sections; add assets to a board or a section, move them between sections, or remove them. Removing from a board never deletes the asset.",
    "boards",
    "board",
    writes=[
        ("create", "create_board"),
        ("update", "update_board"),
        ("trash", "delete_board"),
        ("restore", "restore_board"),
        ("section_create", "create_board_section", "section"),
        ("section_update", "update_board_section", "section"),
        ("section_delete", "delete_board_section", "section"),
        ("section_reorder", "reorder_board_sections"),
        ("add", "add_board_items"),
        ("remove", "bulk_remove_board_items"),
        ("move", "bulk_move_board_items"),
    ],
)
family(
    "projects_get",
    "List projects and read their context.",
    "projects",
    "project",
    [("list", "list_projects"), ("detail", "get_project")],
)
family(
    "projects_update",
    "Create or edit a project's context and model choices.",
    "projects",
    "project",
    writes=[
        ("create", "create_project"),
        ("update", "update_project"),
    ],
)
family(
    "assets_update",
    "Change assets: trash or restore them, add or remove a marker or tags, clear an expiration, or move them into or out of a project. Markers come from catalog_get.",
    "assets",
    "asset",
    writes=[
        ("trash", "trash_assets"),
        ("restore", "restore_assets"),
        ("markers", "bulk_asset_markers"),
        ("tags", "bulk_asset_tags"),
        ("clear_expiration", "clear_asset_expiration"),
        ("add_to_project", "add_assets_to_project"),
        ("remove_from_project", "remove_asset_from_project"),
    ],
)
family(
    "chats_get",
    "List chats or read a chat's name, project and dates. Not its messages.",
    "chats",
    "chat",
    [("list", "list_chats"), ("detail", "get_chat")],
)
family(
    "chats_update",
    "Rename or trash a chat. Chat contents are not reachable here; use agent_start to have Stimma work in a new chat.",
    "chats",
    "chat",
    writes=[
        ("update", "update_chat"),
        ("trash", "delete_chat"),
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
            schema["properties"] = {
                "action": {"const": action, "type": "string"},
                **schema["properties"],
            }
            schema.setdefault("required", []).insert(0, "action")
            if binding.write:
                schema["properties"]["request_key"] = {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 128,
                    "description": "Your own id for this request, any short unique string. Retry a lost response with the same value; use a new value for new work.",
                }
                schema["required"].append("request_key")
            schemas.append(schema)
        result.append(
            Tool(
                name=name,
                description=f"{description} Actions: {', '.join(variants)}.",
                inputSchema={"type": "object", "oneOf": schemas, **({"$defs": definitions} if definitions else {})},
                annotations=ToolAnnotations(
                    readOnlyHint=not write,
                    destructiveHint=write,
                    idempotentHint=write,
                    openWorldHint=False,
                ),
            )
        )
    return result



