"""
Conversation feedback package builder (v1).

Builds the package.zip attached to thumbs feedback:

    manifest.json       {packageVersion: 1, appVersion, agentContext, mediaMap}
    conversation.json   {chat?, messages: [{role, text, media}], items?, ...}
    llm_traces.json     {traces: [...]}            (chat/recipe packages only)
    media/<n>.<ext>     media files, media_id remapped

Two sources:
- chat / recipe chats: Chat + ChatItems + associated LLMTraces from the
  profile DB, media files copied from disk.
- prompt-agent (frontend-transient): the frontend posts its in-memory
  conversation + prompt/parameter state; wrapped in the same manifest shape.

Media is collected from every attachment path the chat UI renders:
item.media_id / media_ids columns, item_metadata attachments,
media_display rows, progress_display previews, inline markdown refs in
message text, tool_result generation payloads, and grid/set composite
cells (expanded recursively).

Cap: 100 MB. Media is added newest-first until the cap; the remainder is
listed in the manifest as omitted. Referenced media that cannot be read
from disk (or has no library row) is listed in the manifest as missing —
never silently absent.

The zip MUST stay renderable by the admin inbox viewer
(AdminFeedbackDetail.vue): it scans JSON entries (zip order) for arrays of
{role, text, media} shaped objects — conversation.json carries exactly that
under ``messages`` and is written before llm_traces.json.
"""
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.logging import get_logger

log = get_logger(__name__)

PACKAGE_VERSION = 1
DEFAULT_MAX_PACKAGE_BYTES = 100 * 1024 * 1024


def _app_version() -> str:
    try:
        from user_agent import get_app_version
        return get_app_version()
    except Exception:
        return "0.0.0"


# Inline refs rendered by the chat UI: ![caption](media_id=123) / ![caption](media:123)
_INLINE_MEDIA_RE = re.compile(r"!\[[^\]]*\]\(media(?:_id=|:)(\d+)\)")
# Generation outputs referenced by call_tool result strings: <result media_id=123 ...>
_TOOL_RESULT_MEDIA_RE = re.compile(r"<result media_id=(\d+)")

_COMPOSITE_FORMATS = ("stimmaset.json", "stimmagrid.json")


def _media_ids_for_item(item: Any) -> List[int]:
    """Media ids referenced by one chat item, across every attachment path:
    media_id / media_ids columns, metadata attachments (user uploads),
    media_display rows, progress_display previews, inline markdown refs,
    and generation outputs referenced from tool_result payloads."""
    seen: Dict[int, None] = {}

    def add(value):
        try:
            mid = int(value)
        except (TypeError, ValueError):
            return
        if mid > 0 and mid not in seen:
            seen[mid] = None

    if item.media_id:
        add(item.media_id)
    raw = getattr(item, "media_ids", None)
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                for v in parsed:
                    add(v)
        except (json.JSONDecodeError, TypeError):
            pass

    meta = getattr(item, "item_metadata", None)
    if meta:
        try:
            parsed = json.loads(meta) if isinstance(meta, str) else meta
        except (json.JSONDecodeError, TypeError):
            parsed = None
        if isinstance(parsed, dict):
            # Attachments recorded in item metadata (user uploads)
            for att in parsed.get("attachments") or []:
                if isinstance(att, dict) and att.get("media_id"):
                    add(att["media_id"])
            display = parsed.get("display_data")
            if isinstance(display, dict):
                # media_display: show() / generation result tiles
                rows = display.get("rows")
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            output = row.get("output")
                            if isinstance(output, dict) and output.get("media_id"):
                                add(output["media_id"])
                # progress_display: preview thumbnails
                previews = display.get("previews")
                if isinstance(previews, list):
                    for mid in previews:
                        add(mid)

    text = getattr(item, "message_text", None)
    if text:
        for match in _INLINE_MEDIA_RE.finditer(text):
            add(match.group(1))

    raw_result = getattr(item, "tool_result", None)
    if raw_result and isinstance(raw_result, str):
        try:
            payload = json.loads(raw_result)
        except (json.JSONDecodeError, TypeError):
            payload = None
        if isinstance(payload, dict):
            if payload.get("media_id"):
                add(payload["media_id"])
            ids = payload.get("media_ids")
            if isinstance(ids, list):
                for v in ids:
                    add(v)
        for match in _TOOL_RESULT_MEDIA_RE.finditer(raw_result):
            add(match.group(1))

    return list(seen.keys())


def _collect_media_ids(items: List[Any]) -> List[int]:
    """Media ids referenced by chat items, in item order, de-duplicated."""
    seen: Dict[int, None] = {}
    for item in items:
        for mid in _media_ids_for_item(item):
            if mid not in seen:
                seen[mid] = None
    return list(seen.keys())


def _composite_ref_paths(row: Any) -> List[str]:
    """Absolute file paths referenced by a set/grid composite's items/cells.

    Reads the composite JSON from disk, falling back to the cached
    raw_metadata when the file is unreadable."""
    if not row.file_path:
        return []
    base_path = Path(row.file_path)
    content = None
    try:
        content = json.loads(base_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    if content is None and getattr(row, "raw_metadata", None):
        try:
            content = json.loads(row.raw_metadata)
        except (json.JSONDecodeError, TypeError):
            pass
    if not isinstance(content, dict):
        return []

    from structured_media import resolve_path

    refs: List[str] = []
    for key in ("items", "cells"):
        entries = content.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and entry.get("path"):
                try:
                    refs.append(str(resolve_path(base_path, entry["path"])))
                except (TypeError, ValueError):
                    continue
    return refs


def _item_to_message(item: Any, media_names: Dict[int, str]) -> Optional[Dict[str, Any]]:
    """Map a ChatItem to the {role, text, media} shape the admin viewer renders."""
    role_map = {
        "user_message": "user",
        "assistant_message": "assistant",
        "assistant_message_chunk": "assistant",
    }
    role = role_map.get(item.item_type, item.item_type)
    text = item.message_text or ""

    if item.item_type == "tool_call":
        args = item.tool_args or ""
        text = f"{item.tool_name or 'tool'}({args})"
    elif item.item_type == "tool_result":
        text = item.tool_error or item.tool_result or ""
    elif item.item_type == "error":
        text = item.message_text or item.tool_error or ""

    media: List[str] = []
    for mid in _media_ids_for_item(item):
        media.append(media_names.get(mid, f"media_id:{mid} (omitted)"))

    if not text and not media:
        return None
    return {"role": role, "text": text, "media": media}


async def build_chat_package(
    chat_id: int,
    session,
    agent_context: str = "main",
    max_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,
) -> bytes:
    """Build the package zip for a chat (or recipe chat). Returns zip bytes."""
    from sqlalchemy import select
    from database import Chat, ChatItem, LLMTrace, MediaItem

    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if chat is None:
        raise ValueError(f"Chat {chat_id} not found")

    result = await session.execute(
        select(ChatItem).where(ChatItem.chat_id == chat_id).order_by(ChatItem.created_at, ChatItem.id)
    )
    items = list(result.scalars().all())

    result = await session.execute(
        select(LLMTrace).where(LLMTrace.chat_id == chat_id).order_by(LLMTrace.created_at, LLMTrace.id)
    )
    traces = list(result.scalars().all())

    media_ids = _collect_media_ids(items)
    referenced_ids: List[int] = list(media_ids)
    media_rows: Dict[int, Any] = {}

    new_rows: List[Any] = []
    if media_ids:
        result = await session.execute(select(MediaItem).where(MediaItem.id.in_(media_ids)))
        new_rows = list(result.scalars().all())

    # Expand grid/set composites: their cells reference other media items
    # (by file path, relative to the composite file). Bounded depth guards
    # against pathological nesting.
    depth = 0
    while new_rows and depth < 4:
        for row in new_rows:
            media_rows[row.id] = row
        ref_paths: List[str] = []
        for row in new_rows:
            if (row.file_format or "").lower() in _COMPOSITE_FORMATS:
                ref_paths.extend(_composite_ref_paths(row))
        new_rows = []
        if ref_paths:
            result = await session.execute(
                select(MediaItem).where(
                    MediaItem.file_path.in_(ref_paths),
                    MediaItem.deleted_at.is_(None),
                )
            )
            for row in result.scalars().all():
                if row.id not in media_rows:
                    new_rows.append(row)
                    referenced_ids.append(row.id)
        depth += 1

    return _assemble_package(
        agent_context=agent_context,
        chat_dict=chat.to_dict(),
        items=items,
        traces=[t.to_dict() for t in traces],
        media_rows=list(media_rows.values()),
        referenced_media_ids=referenced_ids,
        max_bytes=max_bytes,
    )


def _assemble_package(
    *,
    agent_context: str,
    chat_dict: Dict[str, Any],
    items: List[Any],
    traces: List[Dict[str, Any]],
    media_rows: List[Any],
    max_bytes: int,
    referenced_media_ids: Optional[List[int]] = None,
) -> bytes:
    # Media newest-first up to the cap; remainder listed as omitted.
    def sort_key(row):
        return row.created_date or row.indexed_date or datetime.min
    ordered = sorted(media_rows, key=sort_key, reverse=True)

    media_map: Dict[str, Dict[str, Any]] = {}
    media_names: Dict[int, str] = {}
    included: List[tuple] = []  # (archive_name, file_bytes)
    budget = max_bytes
    counter = 0

    # Referenced ids with no library row (e.g. deleted media): listed as
    # missing so they are never silently absent from the manifest.
    known_ids = {row.id for row in media_rows}
    for mid in referenced_media_ids or []:
        if mid not in known_ids:
            media_map[str(mid)] = {"missing": True, "reason": "not_in_library"}

    for row in ordered:
        path = Path(row.file_path) if row.file_path else None
        if not path or not path.exists():
            media_map[str(row.id)] = {"missing": True, "reason": "file_unavailable"}
            continue
        try:
            data = path.read_bytes()
        except OSError:
            media_map[str(row.id)] = {"missing": True, "reason": "file_unavailable"}
            continue
        size = len(data)
        if size > budget:
            media_map[str(row.id)] = {"omitted": True, "reason": "size_cap"}
            continue
        counter += 1
        ext = path.suffix.lstrip(".") or (row.file_format or "bin").split(".")[0]
        name = f"media/{counter}.{ext}"
        included.append((name, data))
        media_names[row.id] = name
        media_map[str(row.id)] = {"file": name, "bytes": size}
        budget -= size

    messages = []
    for item in items:
        msg = _item_to_message(item, media_names)
        if msg:
            messages.append(msg)

    manifest = {
        "packageVersion": PACKAGE_VERSION,
        "appVersion": _app_version(),
        "agentContext": agent_context,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "messageCount": len(messages),
        "mediaMap": media_map,
    }

    conversation = {
        "chat": chat_dict,
        "messages": messages,
        "items": [item.to_dict() for item in items],
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Write order matters: the admin viewer reads zip entries in order
        # and renders the first JSON with message-shaped data.
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("conversation.json", json.dumps(conversation, indent=2))
        if traces:
            zf.writestr("llm_traces.json", json.dumps({"traces": traces}, indent=2))
        for name, data in included:
            zf.writestr(name, data, compress_type=zipfile.ZIP_STORED)
    return buf.getvalue()


def build_prompt_agent_package(
    conversation: Dict[str, Any],
    max_bytes: int = DEFAULT_MAX_PACKAGE_BYTES,  # noqa: ARG001 — text-only, far below cap
) -> bytes:
    """Wrap the frontend's in-memory prompt-agent conversation.

    ``conversation``: {messages: [{role, content|text}], prompt?, parameters?,
    instructions?} — posted by the frontend (the prompt agent's conversation
    is frontend-transient).
    """
    raw_messages = conversation.get("messages") or []
    messages = []
    for m in raw_messages:
        if not isinstance(m, dict):
            continue
        text = m.get("text") if m.get("text") is not None else m.get("content")
        role = m.get("role") or "assistant"
        if text:
            messages.append({"role": str(role), "text": str(text), "media": []})

    manifest = {
        "packageVersion": PACKAGE_VERSION,
        "appVersion": _app_version(),
        "agentContext": "prompt-agent",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "messageCount": len(messages),
        "mediaMap": {},
    }
    body = {
        "messages": messages,
        "prompt": conversation.get("prompt"),
        "parameters": conversation.get("parameters"),
        "instructions": conversation.get("instructions"),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("conversation.json", json.dumps(body, indent=2))
    return buf.getvalue()
