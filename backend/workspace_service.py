"""The shared workspace: documents every client of a profile reads and writes.

A document is (namespace, key) -> JSON. Namespaces in use:

    tab    one sidebar tab, keyed by tab id
    kv     anything else the client keeps for this profile, keyed by its name
    blob   a reference to a large value stored as a file ({hash, size})

Writes are last-arrival-wins per top-level key, which suits one person moving
between clients. A write that changes nothing is dropped without bumping the
revision or broadcasting, so clients that independently apply the same update
(two clients reacting to one rename, say) settle instead of echoing.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import app_dirs
from core.logging import get_logger
from core.profile_context import get_current_profile
from database import (
    Asset,
    Board,
    Chat,
    DatabaseMeta,
    Flow,
    MediaItem,
    PinnedTool,
    Project,
    WorkingDocument,
    WorkspaceDoc,
    WorkspaceMigration,
)

log = get_logger(__name__)

TAB = "tab"
KV = "kv"
BLOB = "blob"

# Closed tabs can be reopened, and keep their tool state, for this long.
RETENTION = timedelta(days=30)
RECENTLY_CLOSED_LIMIT = 20
MAX_DOC_BYTES = 4 * 1024 * 1024
MAX_BLOB_BYTES = 64 * 1024 * 1024
# Larger changes are announced without their content; clients read them.
INLINE_CHANGE_BYTES = 128 * 1024

_NAME_RE = re.compile(r"^[a-z_]{1,32}$")
_PINS_SEEDED_KEY = "workspace_pins_seeded"
# The instance id every client agrees on for a tab made from a server-side pin.
PIN_INSTANCE_ID = "pin"
_INSTANCE_IN_KEY_RE = re.compile(r"__i_([0-9A-Za-z]+)(?![0-9A-Za-z-])")
_EDITOR_OVERLAY_RE = re.compile(r"__i_image-stack-(\d+)$")


_write_locks: dict[tuple, asyncio.Lock] = {}


def write_lock() -> asyncio.Lock:
    """Held across a write's read, merge, commit and broadcast. Merging reads the
    whole document, so two writes at once would lose one's fields, and events must
    go out in revision order because clients drop older ones."""
    key = (get_current_profile(), asyncio.get_running_loop())
    return _write_locks.setdefault(key, asyncio.Lock())


class WorkspaceError(ValueError):
    """A request the workspace refuses; `status` is the HTTP status."""

    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def _dumps(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _validate_name(namespace: str, key: str) -> None:
    if not _NAME_RE.match(namespace):
        raise WorkspaceError(f"Invalid namespace: {namespace!r}")
    if not key or len(key) > 1024:
        raise WorkspaceError("Invalid key")


def _doc_dict(row: WorkspaceDoc) -> dict:
    return {
        "namespace": row.namespace,
        "key": row.key,
        "value": json.loads(row.value) if row.value is not None else None,
        "rev": row.rev,
    }


async def _get(session: AsyncSession, namespace: str, key: str) -> Optional[WorkspaceDoc]:
    return await session.get(WorkspaceDoc, (namespace, key))


async def get_doc(session: AsyncSession, namespace: str, key: str) -> Optional[dict]:
    row = await _get(session, namespace, key)
    return _doc_dict(row) if row is not None and row.deleted_at is None else None


async def apply_ops(session: AsyncSession, ops: Iterable[dict]) -> list[dict]:
    """Apply a batch of writes in the caller's transaction; returns what changed.

    An op has a namespace and key plus one of:
      value          replace the document, reviving it if it was deleted
      set / unset    merge top-level keys into a live object document; ignored
                     when the document is gone, so a late field update can't
                     resurrect half of something another client deleted
      deleted: true  soft-delete it
    """
    changes: list[dict] = []
    for op in ops:
        namespace, key = op["namespace"], op["key"]
        _validate_name(namespace, key)
        row = await _get(session, namespace, key)
        now = datetime.utcnow()

        if op.get("deleted"):
            if row is None or row.deleted_at is not None:
                continue
            row.deleted_at = now
            row.rev += 1
            changes.append({"namespace": namespace, "key": key, "rev": row.rev, "deleted": True})
            continue

        if "value" in op:
            encoded = _dumps(op["value"])
            if len(encoded.encode()) > MAX_DOC_BYTES:
                raise WorkspaceError("Document too large", status=413)
            if row is None:
                row = WorkspaceDoc(namespace=namespace, key=key, value=encoded, rev=1, created_at=now, updated_at=now)
                session.add(row)
            elif row.deleted_at is None and row.value == encoded:
                continue
            else:
                row.value = encoded
                row.deleted_at = None
                row.rev += 1
            changes.append({"namespace": namespace, "key": key, "rev": row.rev, "value": op["value"]})
            continue

        set_keys = op.get("set") or {}
        unset_keys = op.get("unset") or []
        if row is None or row.deleted_at is not None:
            continue
        current = json.loads(row.value) if row.value is not None else None
        if not isinstance(current, dict):
            raise WorkspaceError("Can only merge into an object document", status=409)
        applied_set = {k: v for k, v in set_keys.items() if k not in current or current[k] != v}
        applied_unset = [k for k in unset_keys if k in current]
        if not applied_set and not applied_unset:
            continue
        current.update(applied_set)
        for k in applied_unset:
            del current[k]
        encoded = _dumps(current)
        if len(encoded.encode()) > MAX_DOC_BYTES:
            raise WorkspaceError("Document too large", status=413)
        row.value = encoded
        row.rev += 1
        changes.append({"namespace": namespace, "key": key, "rev": row.rev, "set": applied_set, "unset": applied_unset})
    await session.flush()
    return changes


def event_payload(changes: list[dict], origin: Optional[str]) -> dict:
    """The `workspace_docs_changed` event, with oversized content left out."""
    trimmed = []
    for change in changes:
        if len(_dumps(change).encode()) > INLINE_CHANGE_BYTES:
            change = {"namespace": change["namespace"], "key": change["key"], "rev": change["rev"], "refetch": True}
        trimmed.append(change)
    return {"origin": origin, "changes": trimmed}


async def snapshot(session: AsyncSession) -> dict:
    """Everything a client needs to show the workspace."""
    await seed_pinned_tabs(session)
    result = await session.execute(select(WorkspaceDoc).where(WorkspaceDoc.deleted_at.is_(None)))
    docs = [_doc_dict(row) for row in result.scalars().all()]
    closed = await session.execute(
        select(WorkspaceDoc)
        .where(WorkspaceDoc.namespace == TAB, WorkspaceDoc.deleted_at.is_not(None))
        .order_by(WorkspaceDoc.deleted_at.desc())
        .limit(RECENTLY_CLOSED_LIMIT)
    )
    claim = await session.execute(
        select(WorkspaceMigration).where(WorkspaceMigration.applied.is_(True)).limit(1)
    )
    claimed = claim.scalar_one_or_none()
    return {
        "docs": docs,
        "closed_tabs": [json.loads(row.value) for row in closed.scalars().all() if row.value],
        "migration": {"claimed": claimed is not None},
    }


def _pin_tab(pin: PinnedTool) -> dict:
    safe_tool = pin.full_tool_id.replace(":", "_")
    return {
        "id": f"tool:{pin.full_tool_id}:i:{PIN_INSTANCE_ID}",
        "type": "tool",
        "entityId": pin.full_tool_id,
        "pinned": True,
        "displayOrder": pin.pin_order or 0,
        "displayName": pin.name or pin.full_tool_id,
        "instanceId": PIN_INSTANCE_ID,
        "feedScope": f"{safe_tool}__i_{PIN_INSTANCE_ID}",
    }


async def _live_tabs(session: AsyncSession) -> list[dict]:
    result = await session.execute(
        select(WorkspaceDoc).where(WorkspaceDoc.namespace == TAB, WorkspaceDoc.deleted_at.is_(None))
    )
    return [json.loads(row.value) for row in result.scalars().all() if row.value]


async def _ensure_pin_tabs(session: AsyncSession) -> list[dict]:
    """Give every tool pinned on the server a pinned tab, once tabs are known."""
    pins = (await session.execute(select(PinnedTool).order_by(PinnedTool.pin_order.asc()))).scalars().all()
    tabs = await _live_tabs(session)
    ops: list[dict] = []
    for pin in pins:
        mine = [t for t in tabs if t.get("type") == "tool" and t.get("entityId") == pin.full_tool_id]
        if any(t.get("pinned") for t in mine):
            continue
        if mine:
            best = max(mine, key=lambda t: t.get("lastActivatedAt") or 0)
            ops.append({"namespace": TAB, "key": best["id"], "set": {"pinned": True}})
        else:
            tab = _pin_tab(pin)
            ops.append({"namespace": TAB, "key": tab["id"], "value": tab})
    return await apply_ops(session, ops)


async def seed_pinned_tabs(session: AsyncSession) -> list[dict]:
    """First read of a profile's workspace: its existing tool pins become tabs."""
    if await session.get(DatabaseMeta, _PINS_SEEDED_KEY) is not None:
        return []
    changes = await _ensure_pin_tabs(session)
    session.add(DatabaseMeta(key=_PINS_SEEDED_KEY, value="1"))
    await session.commit()
    return changes


_TAB_ENTITIES = {"chat": Chat, "board": Board, "flow": Flow, "project": Project, "lineage": MediaItem}


async def _tab_entity_exists(session: AsyncSession, tab: dict) -> bool:
    kind = tab.get("type")
    entity = str(tab.get("entityId") or "")
    if kind == "tool":
        return True  # Tools come and go; an unavailable one can come back.
    if kind == "editor":
        model, raw = Asset, entity.removeprefix("asset:")
    else:
        model, raw = _TAB_ENTITIES.get(kind), entity
    if model is None or not raw.isdigit():
        return False
    row = await session.get(model, int(raw))
    return row is not None and getattr(row, "deleted_at", None) is None


async def _import_docs(session: AsyncSession, docs: list[dict]) -> tuple[list[dict], dict]:
    """Add uploaded documents to the workspace. Never overwrites or deletes
    anything a client already put there, apart from a stand-in tab made from a
    server pin that the upload has a real tab for."""
    stats = {"imported": 0, "already_present": 0, "dropped": []}
    ops: list[dict] = []
    tool_with_pinned_tab = set()
    for doc in docs:
        namespace, key, value = doc["namespace"], doc["key"], doc.get("value")
        _validate_name(namespace, key)
        if namespace == TAB:
            if not isinstance(value, dict) or value.get("id") != key:
                stats["dropped"].append({"key": key, "reason": "malformed"})
                continue
            if not await _tab_entity_exists(session, value):
                stats["dropped"].append({"key": key, "reason": "missing_entity"})
                continue
            if value.get("type") == "tool" and value.get("pinned"):
                tool_with_pinned_tab.add(value.get("entityId"))
        editor_overlay = _EDITOR_OVERLAY_RE.search(key)
        if editor_overlay and await session.get(WorkingDocument, int(editor_overlay.group(1))) is None:
            stats["dropped"].append({"key": key, "reason": "missing_entity"})
            continue
        if await _get(session, namespace, key) is not None:
            stats["already_present"] += 1
            continue
        ops.append({"namespace": namespace, "key": key, "value": value})
        stats["imported"] += 1
    changes = await apply_ops(session, ops)

    # A stand-in was never a tab anyone opened, so it isn't left to reopen either.
    for tab in await _live_tabs(session):
        if tab.get("instanceId") == PIN_INSTANCE_ID and tab.get("entityId") in tool_with_pinned_tab:
            await session.execute(delete(WorkspaceDoc).where(WorkspaceDoc.namespace == TAB, WorkspaceDoc.key == tab["id"]))
    changes += await _ensure_pin_tabs(session)
    return changes, stats


async def migrate(session: AsyncSession, client_id: str, docs: list[dict], meta: Optional[dict] = None) -> dict:
    """Take one client's locally kept workspace.

    Every upload is archived. The first one for this profile becomes the claim
    and is imported, in one transaction, so a crash leaves nothing partial and
    two clients at once can't both win. Retrying a claim returns its result.
    """
    previous = await session.execute(
        select(WorkspaceMigration)
        .where(WorkspaceMigration.client_id == client_id)
        .order_by(WorkspaceMigration.applied.desc(), WorkspaceMigration.id.desc())
        .limit(1)
    )
    row = previous.scalar_one_or_none()
    if row is not None:
        return {
            "applied": row.applied,
            "repeat": True,
            "stats": json.loads(row.stats) if row.stats else None,
            "changes": [],
        }

    payload = _dumps({"docs": docs, "meta": meta or {}})
    claim = WorkspaceMigration(client_id=client_id, applied=True, payload=payload)
    session.add(claim)
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        session.add(WorkspaceMigration(client_id=client_id, applied=False, payload=payload))
        await session.commit()
        return {"applied": False, "repeat": False, "stats": None, "changes": []}

    changes, stats = await _import_docs(session, docs)
    if await session.get(DatabaseMeta, _PINS_SEEDED_KEY) is None:
        session.add(DatabaseMeta(key=_PINS_SEEDED_KEY, value="1"))
    claim.stats = _dumps(stats)
    await session.commit()
    log.info(
        "workspace migrated",
        imported=stats["imported"],
        already_present=stats["already_present"],
        dropped=len(stats["dropped"]),
    )
    return {"applied": True, "repeat": False, "stats": stats, "changes": changes}


def blob_dir(profile_id: Optional[str] = None) -> Path:
    return app_dirs.get_profile_dir(profile_id or get_current_profile()) / "workspace_blobs"


async def put_blob(session: AsyncSession, key: str, data: bytes, if_absent: bool = False) -> list[dict]:
    """Store a large value as a content-addressed file and point a doc at it.

    `if_absent` is for carrying over old values: anything already here, deleted
    included, is newer than what a client kept locally."""
    if len(data) > MAX_BLOB_BYTES:
        raise WorkspaceError("Blob too large", status=413)
    _validate_name(BLOB, key)
    if if_absent and await _get(session, BLOB, key) is not None:
        return []
    digest = hashlib.sha256(data).hexdigest()
    directory = blob_dir()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / digest
    if not target.exists():
        staged = directory / f".{digest}.tmp"
        staged.write_bytes(data)
        staged.replace(target)
    return await apply_ops(session, [{"namespace": BLOB, "key": key, "value": {"hash": digest, "size": len(data)}}])


async def get_blob(session: AsyncSession, key: str) -> Optional[bytes]:
    doc = await get_doc(session, BLOB, key)
    if doc is None:
        return None
    path = blob_dir() / doc["value"]["hash"]
    return path.read_bytes() if path.exists() else None


async def purge_expired(session: AsyncSession, profile_id: str, now: Optional[datetime] = None) -> dict:
    """Empty the trash: tabs closed long ago, the tool state only they used, and
    stored files nothing points at any more."""
    cutoff = (now or datetime.utcnow()) - RETENTION
    rows = (await session.execute(select(WorkspaceDoc))).scalars().all()
    live_instances = set()
    expired_instances = set()
    for row in rows:
        if row.namespace != TAB or not row.value:
            continue
        instance = json.loads(row.value).get("instanceId")
        if not instance:
            continue
        if row.deleted_at is None or row.deleted_at >= cutoff:
            live_instances.add(str(instance))
        else:
            expired_instances.add(str(instance))
    expired_instances -= live_instances

    purged = 0
    for row in rows:
        gone = row.deleted_at is not None and row.deleted_at < cutoff
        if not gone and row.namespace != TAB:
            match = _INSTANCE_IN_KEY_RE.search(row.key)
            gone = match is not None and match.group(1) in expired_instances
        if gone:
            await session.execute(
                delete(WorkspaceDoc).where(WorkspaceDoc.namespace == row.namespace, WorkspaceDoc.key == row.key)
            )
            purged += 1
    await session.commit()

    referenced = {
        json.loads(value)["hash"]
        for (value,) in (await session.execute(select(WorkspaceDoc.value).where(WorkspaceDoc.namespace == BLOB))).all()
        if value
    }
    files = 0
    directory = blob_dir(profile_id)
    if directory.exists():
        for path in directory.iterdir():
            if path.name not in referenced and not path.name.startswith("."):
                path.unlink(missing_ok=True)
                files += 1
    return {"docs": purged, "files": files}
