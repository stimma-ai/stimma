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

Cap: 100 MB. Media is added newest-first until the cap; the remainder is
listed in the manifest as omitted.

The zip MUST stay renderable by the admin inbox viewer
(AdminFeedbackDetail.vue): it scans JSON entries (zip order) for arrays of
{role, text, media} shaped objects — conversation.json carries exactly that
under ``messages`` and is written before llm_traces.json.
"""
import io
import json
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


def _collect_media_ids(items: List[Any]) -> List[int]:
    """Media ids referenced by chat items, in item order, de-duplicated."""
    seen: Dict[int, None] = {}

    def add(value):
        try:
            mid = int(value)
        except (TypeError, ValueError):
            return
        if mid not in seen:
            seen[mid] = None

    for item in items:
        if item.media_id:
            add(item.media_id)
        for field in ("media_ids",):
            raw = getattr(item, field, None)
            if raw:
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, list):
                        for v in parsed:
                            add(v)
                except (json.JSONDecodeError, TypeError):
                    pass
        # Attachments recorded in item metadata (user uploads)
        meta = getattr(item, "item_metadata", None)
        if meta:
            try:
                parsed = json.loads(meta)
                for att in (parsed or {}).get("attachments", []) or []:
                    if isinstance(att, dict) and att.get("media_id"):
                        add(att["media_id"])
            except (json.JSONDecodeError, TypeError, AttributeError):
                pass
    return list(seen.keys())


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
    for mid in _collect_media_ids([item]):
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
    media_rows: List[Any] = []
    if media_ids:
        result = await session.execute(select(MediaItem).where(MediaItem.id.in_(media_ids)))
        media_rows = list(result.scalars().all())

    return _assemble_package(
        agent_context=agent_context,
        chat_dict=chat.to_dict(),
        items=items,
        traces=[t.to_dict() for t in traces],
        media_rows=media_rows,
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
) -> bytes:
    # Media newest-first up to the cap; remainder listed as omitted.
    def sort_key(row):
        return row.created_date or row.indexed_date or datetime.min
    ordered = sorted(media_rows, key=sort_key, reverse=True)

    media_map: Dict[str, Dict[str, Any]] = {}
    media_names: Dict[int, str] = {}
    included: List[tuple] = []  # (row, archive_name, file_bytes_len, path)
    budget = max_bytes
    counter = 0
    for row in ordered:
        path = Path(row.file_path) if row.file_path else None
        if not path or not path.exists():
            media_map[str(row.id)] = {"omitted": True, "reason": "file_unavailable"}
            continue
        size = path.stat().st_size
        if size > budget:
            media_map[str(row.id)] = {"omitted": True, "reason": "size_cap"}
            continue
        counter += 1
        ext = path.suffix.lstrip(".") or (row.file_format or "bin").split(".")[0]
        name = f"media/{counter}.{ext}"
        included.append((row, name, size, path))
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
        for _row, name, _size, path in included:
            try:
                zf.write(path, arcname=name, compress_type=zipfile.ZIP_STORED)
            except OSError:
                pass
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


async def chat_package_summary(chat_id: int, session) -> Dict[str, Any]:
    """Cheap preview summary (no zip): message count + media ids."""
    from sqlalchemy import select
    from database import Chat, ChatItem

    result = await session.execute(select(Chat).where(Chat.id == chat_id))
    chat = result.scalar_one_or_none()
    if chat is None:
        raise ValueError(f"Chat {chat_id} not found")
    result = await session.execute(
        select(ChatItem).where(ChatItem.chat_id == chat_id).order_by(ChatItem.created_at, ChatItem.id)
    )
    items = list(result.scalars().all())
    media_ids = _collect_media_ids(items)
    message_count = sum(
        1 for i in items if i.item_type in ("user_message", "assistant_message") and i.message_text
    )
    return {
        "chat_name": chat.name,
        "item_count": len(items),
        "message_count": message_count,
        "media_ids": media_ids,
    }
