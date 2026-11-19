"""What the user did to media between chat messages.

User-initiated routes (marking, collections, trash, export, edit, share) record
a ``MediaAction``. When the user next writes to a chat, the actions on that
chat's media since their previous message become one short factual note on the
message (see ``note_for_next_message``). Agent tools and background work never
record here: the note is about the user. The MCP server calls some of the same
route functions on an agent's behalf; it runs them under ``not_user_initiated``.
"""

from __future__ import annotations

import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.logging import get_logger
from database import Asset, AssetRevision, ChatItem, MediaAction

log = get_logger(__name__)

MARKED = "marked"
UNMARKED = "unmarked"
ADDED_TO_COLLECTION = "added_to_collection"
REMOVED_FROM_COLLECTION = "removed_from_collection"
TRASHED = "trashed"
RESTORED = "restored"
EXPORTED = "exported"
EDITED = "edited"
SHARED = "shared"

# Each action's (kind, sign). Opposite signs of one kind on the same target
# cancel; unsigned kinds are reported once however often they happened.
_KINDS: dict[str, tuple[str, int]] = {
    MARKED: ("marker", 1),
    UNMARKED: ("marker", -1),
    ADDED_TO_COLLECTION: ("collection", 1),
    REMOVED_FROM_COLLECTION: ("collection", -1),
    TRASHED: ("trash", 1),
    RESTORED: ("trash", -1),
    EXPORTED: ("export", 0),
    EDITED: ("edit", 0),
    SHARED: ("share", 0),
}

MAX_LINES = 30
MAX_IDS_PER_LINE = 20
MAX_NAME_CHARS = 60
# Message metadata: where the note's window ended, when that isn't the
# message's own created_at (a steer's note ends when the steer was accepted).
WINDOW_END_KEY = "media_actions_until"

_not_user = ContextVar("media_actions_not_user", default=False)


@contextmanager
def not_user_initiated():
    """Run route code on someone else's behalf (an agent): nothing is recorded."""
    token = _not_user.set(True)
    try:
        yield
    finally:
        _not_user.reset(token)


def marker_detail(marker) -> dict:
    return {"marker_id": marker.id, "marker_name": marker.name}


def collection_detail(collection) -> dict:
    return {"collection_id": collection.id, "collection_name": collection.name}


async def record_media_actions(
    session: AsyncSession,
    action: str,
    items: Iterable[tuple[Optional[int], Optional[int]]],
    detail: Optional[dict] = None,
) -> None:
    """Record ``action`` for each (media_id, asset_id) pair. The caller commits.

    An Asset given without media is recorded with its current revision's
    media; media given without an Asset, with the Asset it is a revision of.
    """
    if action not in _KINDS:
        raise ValueError(f"Unknown media action: {action}")
    if _not_user.get():
        return
    pairs = [(m, a) for m, a in items if m is not None or a is not None]
    if not pairs:
        return
    media_of: dict[int, int] = {}
    asset_of: dict[int, int] = {}
    if missing := {a for m, a in pairs if m is None}:
        media_of = dict((await session.execute(
            select(Asset.id, AssetRevision.primary_media_id)
            .join(AssetRevision, AssetRevision.id == Asset.current_revision_id)
            .where(Asset.id.in_(missing))
        )).all())
    if missing := {m for m, a in pairs if a is None}:
        asset_of = dict((await session.execute(
            select(AssetRevision.primary_media_id, AssetRevision.asset_id)
            .where(AssetRevision.primary_media_id.in_(missing))
        )).all())
    payload = json.dumps(detail) if detail else None
    now = datetime.utcnow()
    for media_id, asset_id in dict.fromkeys(pairs):
        session.add(MediaAction(
            media_id=media_id if media_id is not None else media_of.get(asset_id),
            asset_id=asset_id if asset_id is not None else asset_of.get(media_id),
            action=action,
            detail=payload,
            created_at=now,
        ))


async def record_media_action(
    session: AsyncSession,
    action: str,
    *,
    media_id: Optional[int] = None,
    asset_id: Optional[int] = None,
    detail: Optional[dict] = None,
) -> None:
    await record_media_actions(session, action, [(media_id, asset_id)], detail)


async def record_and_commit(
    session: AsyncSession, action: str, media_ids: Iterable[int], detail: Optional[dict] = None
) -> None:
    """Record and commit for routes that otherwise only read (export, share).

    Writes in a session of its own, so the route's session and the objects it
    loaded are untouched. Never raises: the user's export or share matters
    more than the record.
    """
    media_ids = list(media_ids)
    if _not_user.get() or not media_ids:
        return
    try:
        async with async_sessionmaker(session.bind, expire_on_commit=False)() as own:
            await record_media_actions(own, action, [(m, None) for m in media_ids], detail)
            await own.commit()
    except Exception as exc:  # noqa: BLE001
        log.warning(f"Could not record media action {action}: {type(exc).__name__}: {exc}")


def _naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is not None and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _parse_detail(raw: Optional[str]) -> dict:
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _quote(name: Any) -> Optional[str]:
    """A user-chosen name as one bounded, quoted line."""
    text = re.sub(r"[\s\x00-\x1f\x7f]+", " ", str(name or "")).strip()
    if not text:
        return None
    if len(text) > MAX_NAME_CHARS:
        text = text[:MAX_NAME_CHARS - 1].rstrip() + "\u2026"
    return json.dumps(text, ensure_ascii=False)


def _phrase(action: str, detail: dict) -> str:
    if action in (MARKED, UNMARKED):
        target = _quote(detail.get("marker_name")) or "a marker"
        return f"marked {target}" if action == MARKED else f"unmarked {target}"
    if action in (ADDED_TO_COLLECTION, REMOVED_FROM_COLLECTION):
        name = _quote(detail.get("collection_name"))
        target = f"collection {name}" if name else "an untitled collection"
        return f"added to {target}" if action == ADDED_TO_COLLECTION else f"removed from {target}"
    if action == TRASHED:
        return "moved to trash"
    if action == RESTORED:
        return "restored from trash"
    if action == EXPORTED:
        return "exported"
    if action == EDITED:
        result = detail.get("result_media_id")
        if result is None:
            return "edited"
        if detail.get("save_as_new"):
            return f"edited and saved as new media {result}"
        return f"edited (new version is media {result})"
    if action == SHARED:
        return "shared as a public link"
    return action


def _target(action: str, detail: dict) -> Any:
    kind = _KINDS[action][0]
    if kind == "marker":
        return detail.get("marker_id")
    if kind == "collection":
        return detail.get("collection_id")
    if kind == "edit":
        # Each Save As New is its own new media; in-place saves are one edit.
        return detail.get("result_media_id") if detail.get("save_as_new") else None
    return None


def _ids(labels: list[int]) -> str:
    shown = ", ".join(str(i) for i in labels[:MAX_IDS_PER_LINE])
    if len(labels) > MAX_IDS_PER_LINE:
        shown += f" and {len(labels) - MAX_IDS_PER_LINE} more"
    return shown


async def describe_media_actions_since(
    session: AsyncSession,
    chat_id: int,
    since: Optional[datetime],
    until: datetime,
) -> Optional[str]:
    """One note on what the user did to this chat's media in (since, until].

    Actions count when their media is the chat's, or their Asset has a
    revision whose media is. Each item is named by a media id the chat knows.
    Only the net change is told: marking then unmarking, adding then removing,
    or trashing then restoring says nothing. None when nothing is left.
    """
    from agent.v2.tools.library import chat_media_ids

    since, until = _naive_utc(since), _naive_utc(until)
    chat_media = set(await chat_media_ids(session, chat_id))
    if not chat_media:
        return None

    # Asset -> the chat media id from its latest revision.
    asset_label: dict[int, int] = {}
    revisions = (await session.execute(
        select(AssetRevision.asset_id, AssetRevision.primary_media_id)
        .where(AssetRevision.primary_media_id.in_(chat_media))
        .order_by(AssetRevision.asset_id, AssetRevision.revision_number)
    )).all()
    for asset_id, media_id in revisions:
        asset_label[asset_id] = media_id

    conditions = [MediaAction.media_id.in_(chat_media)]
    if asset_label:
        conditions.append(MediaAction.asset_id.in_(asset_label.keys()))
    query = select(MediaAction).where(
        MediaAction.deleted_at.is_(None),
        MediaAction.created_at <= until,
        or_(*conditions),
    ).order_by(MediaAction.created_at, MediaAction.id)
    if since is not None:
        query = query.where(MediaAction.created_at > since)
    actions = (await session.scalars(query)).all()
    if not actions:
        return None

    # (item, kind, target) -> [label, net sign or count, last action, last detail]
    net: dict[tuple, list] = {}
    for row in actions:
        if row.action not in _KINDS:
            continue
        kind, sign = _KINDS[row.action]
        if kind in ("export", "share") and row.media_id is not None:
            # Exactly what left the app: told by the media acted on.
            item = ("media", row.media_id)
            label = row.media_id
        elif row.asset_id is not None:
            item = ("asset", row.asset_id)
            label = asset_label.get(row.asset_id)
            if label is None:
                label = row.media_id if row.media_id in chat_media else None
        else:
            item = ("media", row.media_id)
            label = row.media_id
        if label is None:
            continue
        detail = _parse_detail(row.detail)
        key = (item, kind, _target(row.action, detail))
        entry = net.setdefault(key, [label, 0, row.action, detail])
        entry[1] += sign if sign else 1
        entry[2], entry[3] = row.action, detail

    groups: dict[str, list[int]] = {}
    for (_, kind, _), (label, total, action, detail) in net.items():
        if _KINDS[action][1] and total == 0:
            continue
        labels = groups.setdefault(_phrase(action, detail), [])
        if label not in labels:
            labels.append(label)
    if not groups:
        return None

    lines = [f"media {_ids(labels)}: {phrase}" for phrase, labels in groups.items()]
    if len(lines) > MAX_LINES:
        lines = lines[:MAX_LINES] + [f"and {len(lines) - MAX_LINES} more"]
    return (
        "[Since the previous message, the user acted on media from this chat: "
        + "; ".join(lines) + ".]"
    )


def _window_start(item: ChatItem) -> Optional[datetime]:
    """Where a user message's window ended, or None for a message the user
    didn't write (a stop marker or a task notice)."""
    metadata = _parse_detail(item.item_metadata)
    if metadata.get("stop_event") or metadata.get("background_task"):
        return None
    try:
        return datetime.fromisoformat(metadata[WINDOW_END_KEY])
    except (KeyError, TypeError, ValueError):
        return item.created_at


async def note_for_next_message(
    session: AsyncSession, chat_id: int, chat_created_at: datetime, until: datetime
) -> Optional[str]:
    """The note for a user message about to be added to a chat, as of ``until``.

    Covers the time since the user's previous message (or since the chat
    began). Reads in a session of its own, so a failure can't spoil the
    caller's; never raises: a failure here must not stop the message.
    """
    try:
        async with async_sessionmaker(session.bind, expire_on_commit=False)() as own:
            recent = (await own.scalars(
                select(ChatItem)
                .where(ChatItem.chat_id == chat_id, ChatItem.item_type == "user_message")
                .order_by(ChatItem.created_at.desc(), ChatItem.id.desc())
                .limit(50)
            )).all()
            # The latest boundary, not the newest message's: a steer delivered
            # late ends its window when it was accepted, which can be earlier
            # than a message sent meanwhile.
            since = max(
                (start for start in map(_window_start, recent) if start is not None),
                default=chat_created_at,
            )
            return await describe_media_actions_since(own, chat_id, since, until)
    except Exception as exc:  # noqa: BLE001
        log.warning(f"Skipped the media actions note for chat {chat_id}: {type(exc).__name__}: {exc}")
        return None
