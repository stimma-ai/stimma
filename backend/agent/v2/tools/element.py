"""Element tool — list, open, start and save elements.

Elements are reusable creative ingredients (a character, a product, a style)
kept in the library. Editing is file work: ``open`` and ``init`` put an
element under ``elements/<slug>/`` in the workspace, the agent edits
``element.json``, ``ELEMENT.md`` and ``files/`` with its ordinary file tools,
and ``save`` commits the folder as the element's next version.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from ..tools_registry import tool, ToolParameter
from core.logging import get_logger
from core.profile_context import get_current_profile

log = get_logger(__name__)


def _menu_lines(manifest: dict) -> list[str]:
    lines = []
    for entry in manifest.get("media_menu") or []:
        target = (
            f"asset_id {entry['asset_id']}" if entry.get("asset_id") is not None
            else f"media_id {entry.get('embedded_media_id')}"
        )
        bits = [f"- {entry.get('key')} ({target}, {entry.get('status') or 'canonical'}"]
        if entry.get("conditional"):
            bits.append(", situational")
        bits.append(")")
        if entry.get("title"):
            bits.append(f" {entry['title']}")
        if entry.get("labels"):
            bits.append(f" [{', '.join(entry['labels'])}]")
        if entry.get("usage_hint"):
            bits.append(f" — {entry['usage_hint']}")
        lines.append("".join(bits))
    return lines


def _lora_lines(manifest: dict) -> list[str]:
    lines = []
    for entry in manifest.get("loras") or []:
        bits = [f"- {entry.get('key')}: {entry.get('display_name') or entry.get('fingerprint')}"]
        if entry.get("model_family"):
            bits.append(f" for {entry['model_family']}")
        if entry.get("default_weight") is not None:
            bits.append(f", weight {entry['default_weight']}")
        if entry.get("trigger"):
            bits.append(f", trigger `{entry['trigger']}`")
        lines.append("".join(bits))
    return lines


@tool(
    name="element",
    description=(
        "Work with elements: reusable creative ingredients in the library (a character, product, place, style "
        "or brand) made of instructions, a labeled set of reference media, optional LoRAs and companion files. "
        "list shows the elements in the library. open puts one in your workspace at elements/<slug>/ and shows "
        "its instructions. init starts a new one there. Edit elements/<slug>/ELEMENT.md (the instructions, "
        "with optional {{#if model_family == \"...\"}} … {{else}} … {{/if}} blocks), element.json (name, kind, "
        "media_menu of library assets by asset_id with key/title/labels/status/usage_hint, loras, "
        "cover_member_key) and files/ with your file tools; elements/<slug>/media/ holds read-only copies of "
        "its media to look at. save checks the folder and saves it to the library as the element's next version."
    ),
    parameters=[
        ToolParameter(
            name="action",
            type="string",
            description="list | open | init | save",
            enum=["list", "open", "init", "save"],
        ),
        ToolParameter("asset_id", "integer", "open: the element's asset_id (from list).", required=False),
        ToolParameter(
            "slug", "string",
            "init/save: the folder name under elements/ (lowercase letters, digits and '-', e.g. 'mira'). "
            "open also accepts it for an element already in the workspace.",
            required=False,
        ),
        ToolParameter("name", "string", "init: the element's name, e.g. 'Mira'.", required=False),
        ToolParameter("kind", "string", "init: character | product | place | style | brand, or another word. list: only this kind.", required=False),
        ToolParameter("description", "string", "init: one line about the element.", required=False),
        ToolParameter("query", "string", "list: only elements whose name, kind, description or tags contain this text.", required=False),
        ToolParameter("note", "string", "save: a short note on what changed, shown in the element's versions.", required=False),
        ToolParameter(
            "force", "boolean",
            "save: replace the element even if it was changed elsewhere after you opened it. Only when the user agrees.",
            required=False,
        ),
    ],
)
async def element_tool(
    action: str,
    asset_id: Optional[int] = None,
    slug: Optional[str] = None,
    name: Optional[str] = None,
    kind: Optional[str] = None,
    description: Optional[str] = None,
    query: Optional[str] = None,
    note: Optional[str] = None,
    force: Optional[bool] = None,
    **kwargs,
) -> str:
    from elements.bundle import ElementError, bundle_manifest, element_asset, list_elements
    from elements.workspace import (
        init_element,
        list_checkouts,
        open_element,
        render_for_chat,
        save_checkout,
    )

    session: AsyncSession = kwargs.get("session")
    workspace_dir = kwargs.get("workspace_dir")
    action = (action or "").strip().lower()
    if session is None:
        return "Error: the library isn't available right now"

    try:
        if action == "list":
            rows = await list_elements(session, kind=kind, query=query)
            checkouts = list_checkouts(workspace_dir) if workspace_dir else {}
            if not rows:
                return "No elements in the library yet. Start one with element(action=\"init\", slug=..., name=..., kind=...)."
            lines = [
                "| asset_id | Name | Kind | Version | Reference media | LoRAs | In workspace |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
            for row in rows:
                lines.append(
                    f"| {row['asset_id']} | {row['name']} | {row['kind'] or '-'} | {row['revision_number']} | "
                    f"{row['canonical_count']} | {row['lora_count']} | {checkouts.get(row['asset_id'], '-')} |"
                )
            return "\n".join(lines)

        if not workspace_dir:
            return "Error: no workspace is available in this conversation"

        if action == "init":
            if not name:
                return "Error: init needs a name"
            checkout = init_element(workspace_dir, slug=slug, name=name, kind=kind or "", description=description or "")
            return (
                f"Started {checkout.path}/ with element.json, ELEMENT.md and files/. Write the instructions in "
                f"{checkout.path}/ELEMENT.md, add reference media to media_menu in {checkout.path}/element.json "
                f"(library asset_id plus a key, title and usage_hint), then element(action=\"save\", slug=\"{checkout.directory.name}\"). "
                "It isn't in the library until it's saved."
            )

        if action == "open":
            if asset_id is None and slug:
                from elements.workspace import resolve_checkout, _read_meta  # noqa: PLC0415

                meta = _read_meta(resolve_checkout(workspace_dir, slug)) or {}
                asset_id = meta.get("asset_id")
                if asset_id is None:
                    return f"Error: elements/{slug}/ hasn't been saved yet, so there is nothing to open; edit it there and save it."
            if asset_id is None:
                return "Error: open needs the element's asset_id (see element(action=\"list\"))"
            checkout = await open_element(session, workspace_dir, int(asset_id))
            asset, revision, media = await element_asset(session, int(asset_id))
            manifest = bundle_manifest(media)
            rendered = render_for_chat(checkout.directory)
            parts = [f"# {asset.title} ({manifest.get('kind') or 'element'}, version {revision.revision_number})"]
            if checkout.conflict:
                parts.append(f"Warning: {checkout.conflict}")
            elif not checkout.refreshed:
                parts.append(f"{checkout.path}/ already has your unsaved edits; it was left as it is.")
            parts.append(f"Folder: {checkout.path}/ (edit element.json, ELEMENT.md, files/; media/ is read-only)")
            if manifest.get("description"):
                parts.append(manifest["description"])
            menu = _menu_lines(manifest)
            if menu:
                cover = manifest.get("cover_member_key")
                parts.append("## Media" + (f" (cover: {cover})" if cover else "") + "\n" + "\n".join(menu))
            loras = _lora_lines(manifest)
            if loras:
                parts.append("## LoRAs\n" + "\n".join(loras))
            files = [entry.get("path") for entry in manifest.get("files") or []]
            if files:
                parts.append("## Files\n" + "\n".join(f"- {checkout.path}/{p}" for p in files))
            parts.append("## Instructions (as they apply in chat)\n" + (rendered.text or "(empty)"))
            notes = list(checkout.notes) + list(rendered.warnings)
            if notes:
                parts.append("Notes:\n" + "\n".join(f"- {n}" for n in notes))
            return "\n\n".join(parts)

        if action == "save":
            if not slug:
                return "Error: save needs the slug of the folder under elements/"
            result, checkout = await save_checkout(
                session,
                workspace_dir,
                slug,
                profile_id=get_current_profile(),
                force=bool(force),
                project_id=kwargs.get("project_id"),
                note=note,
            )
            verb = "Saved new element" if result.created else "Saved"
            lines = [
                f"{verb} '{result.asset.title}' (asset_id {result.asset.id}, version {result.revision.revision_number})."
            ]
            warnings = list(result.warnings) + list(checkout.notes)
            if warnings:
                lines.append("Warnings:\n" + "\n".join(f"- {w}" for w in warnings))
            return "\n".join(lines)
    except ElementError as exc:
        return f"Error: {exc}"

    return f"Error: unknown action '{action}'; use list, open, init or save"
