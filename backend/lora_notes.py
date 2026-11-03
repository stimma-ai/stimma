"""Trigger words and notes attached to a LoRA file's content fingerprint.

A note belongs to the file's bytes, not its path, so it survives moving and
renaming. Providers supply fingerprints (STP `file_fingerprints`); a LoRA
without one has no notes.

`resolve_lora_notes` is the only read path, so every consumer sees series
auto-join behave the same way. It uses its own profile-scoped sessions and
never shares a caller's transaction.
"""
import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select, text
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from core.logging import get_logger
from database import LoraNote, LoraNoteFile
from database_registry import get_database_registry

log = get_logger(__name__)

LORAS_PARAMETER = "loras"
FINGERPRINT_RE = re.compile(r"^stfp1p?:[0-9a-f]{32}$")

_FINGERPRINT_TIMEOUT_SECONDS = 2.0
_FINGERPRINT_TTL_SECONDS = 10.0

_GENERIC_STEM = re.compile(r"^(pytorch_lora_weights|adapter_model|diffusion_pytorch_model|lora|model)$", re.I)
_CHECKPOINT_DIR = re.compile(r"^(checkpoint|ckpt|step|steps|epoch)[-_.]?\d+$", re.I)
_NAMED_STEP = re.compile(r"^(.*?)[-_.](?:e|ep|epoch|s|step|steps|ckpt|checkpoint)[-_.]?\d+$", re.I)
_TRAILING_NUMBER = re.compile(r"^(.*?)[-_.](\d+)$")
_VERSION_TAIL = re.compile(r"[-_.]v\d+$", re.I)


# ── Series ────────────────────────────────────────────────────────────────

def series_key(value: str) -> Tuple[str, bool]:
    """Group checkpoints by path alone. Returns (key, has a step-like ending)."""
    parts = re.sub(r"\.[^./]+$", "", value.replace("\\", "/")).split("/")
    stem = parts.pop()
    if _GENERIC_STEM.match(stem) and parts and _CHECKPOINT_DIR.match(parts[-1]):
        parts.pop()
        return "/".join([*parts, "*", stem]), True
    named = _NAMED_STEP.match(stem)
    if named:
        return "/".join([*parts, named.group(1)]), True
    number = _TRAILING_NUMBER.match(stem)
    # v2_2 is a version, not a step; v2_000000500 is a step.
    if number and (len(number.group(2)) >= 3 or not _VERSION_TAIL.search(number.group(1))):
        return "/".join([*parts, number.group(1)]), len(number.group(2)) >= 3
    return "/".join([*parts, stem]), False


def group_series(values: List[str]) -> Dict[str, List[str]]:
    """Map series key to member values, for series of 2 or more."""
    groups: Dict[str, List[str]] = {}
    for value in values:
        groups.setdefault(series_key(value)[0], []).append(value)
    return {key: members for key, members in groups.items() if len(members) > 1}


def display_name(value: str) -> str:
    parts = re.sub(r"\.[^./]+$", "", value.replace("\\", "/")).split("/")
    stem = parts.pop()
    if _GENERIC_STEM.match(stem):
        named = [p for p in parts if not _CHECKPOINT_DIR.match(p)]
        if named:
            stem = named[-1]
    return re.sub(r"[-_]+", " ", stem).strip() or value


# ── Fingerprints ──────────────────────────────────────────────────────────

@dataclass
class _Snapshot:
    values: List[str]
    fingerprints: Dict[str, Optional[str]]
    pending: int
    at: float


_snapshots: Dict[str, _Snapshot] = {}


def _lora_values(descriptor) -> List[str]:
    schema = (getattr(descriptor, "parameter_schema", None) or {}).get("properties", {}).get(LORAS_PARAMETER) or {}
    values = ((schema.get("items") or {}).get("properties") or {}).get("path", {}).get("enum")
    return [str(v) for v in values] if isinstance(values, list) else []


async def _fetch_fingerprints(tool_id: str) -> Optional[_Snapshot]:
    """Fingerprints for a tool's LoRA list, or None when unavailable. Never raises."""
    try:
        from providers.registry import ProviderRegistry

        found = ProviderRegistry.get_instance().get_tool(tool_id)
        if not found:
            return None
        provider, descriptor = found
        values = _lora_values(descriptor)
        if not values:
            return None
        cached = _snapshots.get(tool_id)
        if (
            cached
            and cached.values == values
            and cached.pending == 0
            and time.monotonic() - cached.at < _FINGERPRINT_TTL_SECONDS
        ):
            return cached
        result = await asyncio.wait_for(
            provider.file_fingerprints(descriptor.id, LORAS_PARAMETER), _FINGERPRINT_TIMEOUT_SECONDS
        )
        if not isinstance(result, dict) or not isinstance(result.get("fingerprints"), dict):
            return None
        reported = result["fingerprints"]
        snapshot = _Snapshot(
            values=values,
            fingerprints={v: reported.get(v) if isinstance(reported.get(v), str) else None for v in values},
            pending=int(result.get("pending") or 0),
            at=time.monotonic(),
        )
        _snapshots[tool_id] = snapshot
        return snapshot
    except Exception as e:
        log.debug(f"[lora-notes] No fingerprints for {tool_id}: {e}")
        return None


# ── Reads ─────────────────────────────────────────────────────────────────

def _session(profile_id: Optional[str]):
    from core.profile_context import get_current_profile

    return get_database_registry().get_database(profile_id or get_current_profile()).async_session_maker()


async def _live_links(session, fingerprints: List[str]) -> Dict[str, LoraNoteFile]:
    if not fingerprints:
        return {}
    rows = await session.execute(
        select(LoraNoteFile).where(LoraNoteFile.fingerprint.in_(fingerprints), LoraNoteFile.deleted_at.is_(None))
    )
    return {row.fingerprint: row for row in rows.scalars()}


async def _live_notes(session, note_ids) -> Dict[int, LoraNote]:
    if not note_ids:
        return {}
    rows = await session.execute(select(LoraNote).where(LoraNote.id.in_(set(note_ids)), LoraNote.deleted_at.is_(None)))
    return {row.id: row for row in rows.scalars()}


async def _link_counts(session, note_ids) -> Dict[int, int]:
    if not note_ids:
        return {}
    rows = await session.execute(
        select(LoraNoteFile.note_id).where(LoraNoteFile.note_id.in_(set(note_ids)), LoraNoteFile.deleted_at.is_(None))
    )
    counts: Dict[int, int] = {}
    for (note_id,) in rows:
        counts[note_id] = counts.get(note_id, 0) + 1
    return counts


async def _auto_join(profile_id, series: Dict[str, List[str]], snapshot: _Snapshot, links, notes) -> None:
    """Link new checkpoints to their series' shared note, while the path still
    says they belong to it. The link is what survives a later move and rename."""
    joins: List[Tuple[str, int, str]] = []
    for members in series.values():
        fingerprints = {m: snapshot.fingerprints.get(m) for m in members}
        shared = {
            links[f].note_id
            for f in fingerprints.values()
            if f and f in links and links[f].note_id in notes and notes[links[f].note_id].shared
        }
        if len(shared) != 1:
            continue
        note_id = next(iter(shared))
        joins.extend((f, note_id, m) for m, f in fingerprints.items() if f and f not in links)
    if not joins:
        return
    async with _session(profile_id) as session:
        for fingerprint, note_id, value in joins:
            await session.execute(
                sqlite_insert(LoraNoteFile)
                .values(
                    fingerprint=fingerprint,
                    note_id=note_id,
                    last_seen_value=value,
                    created_at=datetime.utcnow(),
                )
                .on_conflict_do_nothing(index_elements=["fingerprint"], index_where=text("deleted_at IS NULL"))
            )
        await session.commit()


async def resolve_lora_notes(profile_id: Optional[str], tool_id: str) -> Dict[str, Any]:
    """Notes for a tool's LoRA list: {available, pending, items: {value: {...}}}."""
    snapshot = await _fetch_fingerprints(tool_id)
    if snapshot is None:
        return {"available": False, "pending": 0, "items": {}}

    series = group_series(snapshot.values)
    series_of = {value: key for key, members in series.items() for value in members}
    fingerprints = [f for f in snapshot.fingerprints.values() if f]

    async with _session(profile_id) as session:
        links = await _live_links(session, fingerprints)
        notes = await _live_notes(session, [link.note_id for link in links.values()])

    await _auto_join(profile_id, series, snapshot, links, notes)

    async with _session(profile_id) as session:
        links = await _live_links(session, fingerprints)
        notes = await _live_notes(session, [link.note_id for link in links.values()])
        counts = await _link_counts(session, notes.keys())

    def note_for(value: str) -> Optional[LoraNote]:
        fingerprint = snapshot.fingerprints.get(value)
        link = links.get(fingerprint) if fingerprint else None
        return notes.get(link.note_id) if link else None

    items: Dict[str, Any] = {}
    for value in snapshot.values:
        note = note_for(value)
        key = series_of.get(value)
        series_info = None
        if key is not None:
            members = series[key]
            series_info = {
                "id": key,
                "size": len(members),
                # Never default to spreading a note over files that have their own.
                "default_shared": any(series_key(m)[1] for m in members)
                and not any(note_for(m) for m in members),
            }
        items[value] = {
            "fingerprint": snapshot.fingerprints.get(value),
            "note": (
                {
                    "trigger_words": list(note.trigger_words or []),
                    "notes": note.notes or "",
                    "shared": bool(note.shared),
                    "linked_count": counts.get(note.id, 1),
                }
                if note
                else None
            ),
            "series": series_info,
        }
    return {"available": True, "pending": snapshot.pending, "items": items}


async def _has_any_notes(profile_id: Optional[str]) -> bool:
    async with _session(profile_id) as session:
        row = await session.execute(select(LoraNote.id).where(LoraNote.deleted_at.is_(None)).limit(1))
        return row.first() is not None


def canonical_lora_values(values: List[str], loras: Any) -> List[str]:
    """Map enabled, nonzero LoRA items to the tool's real values, using the same
    rule execution does. Accepts {lora}, {path} and {name} items. Anything that
    doesn't resolve is skipped."""
    from agent.tools.stp_utils import AmbiguousLoraError, _find_lora_match, _normalize_lora_name

    if not isinstance(loras, list):
        return []
    known = set(values)
    index: Dict[str, List[str]] = {}
    for value in values:
        index.setdefault(_normalize_lora_name(value), []).append(value)
    result: List[str] = []
    for item in loras:
        if isinstance(item, str):
            query, weight, enabled = item, 1.0, True
        elif isinstance(item, dict):
            query = item.get("path") or item.get("lora") or item.get("name")
            weight, enabled = item.get("weight", 1.0), item.get("enabled", True)
        else:
            continue
        try:
            if not query or not enabled or float(weight) == 0:
                continue
        except (TypeError, ValueError):
            continue
        query = str(query)
        if query in known:
            match = query
        else:
            try:
                found = _find_lora_match(query, values, index)
            except AmbiguousLoraError:
                continue
            if not found:
                continue
            match = found[0]
        if match not in result:
            result.append(match)
    return result


async def lora_context_for(tool_id: str, parameters: Dict[str, Any], profile_id: Optional[str] = None) -> List[Dict]:
    """Trigger words and notes for the LoRAs a generation is actually using.

    Notes must never get in the way of generating, so every failure reads as
    "no context".
    """
    try:
        loras = (parameters or {}).get(LORAS_PARAMETER)
        if not loras or not await _has_any_notes(profile_id):
            return []
        found = await resolve_lora_notes(profile_id, tool_id)
        if not found["available"]:
            return []
        context = []
        for value in canonical_lora_values(list(found["items"].keys()), loras):
            note = found["items"][value]["note"]
            if note:
                context.append(
                    {"name": display_name(value), "trigger_words": note["trigger_words"], "notes": note["notes"]}
                )
        return context
    except Exception as e:
        log.warning(f"[lora-notes] Could not resolve LoRA context for {tool_id}: {e}")
        return []


def lora_context_signature(context: Optional[List[Dict]]) -> str:
    """Stable hash of the context. Empty for no context, so tools without notes
    compare equal to anything warmed before notes existed."""
    if not context:
        return ""
    return hashlib.sha256(json.dumps(context, sort_keys=True).encode()).hexdigest()


def prepend_missing_triggers(prompt: str, context: Optional[List[Dict]]) -> str:
    lowered = prompt.lower()
    missing: List[str] = []
    for lora in context or []:
        for word in lora.get("trigger_words") or []:
            if word.lower() not in lowered and word not in missing:
                missing.append(word)
    return f"{', '.join(missing)}, {prompt}" if missing else prompt


async def agent_notes_by_tool(profile_id: Optional[str], tool_ids: List[str]) -> Dict[str, List[Dict]]:
    """Annotated LoRAs per tool, for the agent's catalog. Never raises."""
    try:
        if not tool_ids or not await _has_any_notes(profile_id):
            return {}
        resolved = await asyncio.gather(*(resolve_lora_notes(profile_id, t) for t in tool_ids))
    except Exception as e:
        log.warning(f"[lora-notes] Could not gather LoRA notes for the agent: {e}")
        return {}
    result: Dict[str, List[Dict]] = {}
    for tool_id, found in zip(tool_ids, resolved):
        annotated = [
            {"value": value, "trigger_words": item["note"]["trigger_words"], "notes": item["note"]["notes"]}
            for value, item in found["items"].items()
            if item["note"]
        ]
        if annotated:
            result[tool_id] = annotated
    return result


# ── Writes ────────────────────────────────────────────────────────────────

def _clean_triggers(words: List[str]) -> List[str]:
    cleaned: List[str] = []
    for word in words:
        word = (word or "").strip()
        if word and word not in cleaned:
            cleaned.append(word)
    return cleaned


def _same_text(a: LoraNote, b: LoraNote) -> bool:
    return list(a.trigger_words or []) == list(b.trigger_words or []) and (a.notes or "") == (b.notes or "")


async def _retire_if_unlinked(session, note_id: int, now: datetime) -> None:
    await session.flush()
    if (await _link_counts(session, [note_id])).get(note_id):
        return
    note = await session.get(LoraNote, note_id)
    if note:
        note.deleted_at = now


async def save_note(
    profile_id: Optional[str],
    fingerprint: str,
    trigger_words: List[str],
    notes: str,
    value: Optional[str] = None,
) -> None:
    """Save text onto the note this fingerprint links to, creating a private one
    if needed. Emptying both fields removes the note and its links. Never
    changes sharing."""
    words = _clean_triggers(trigger_words)
    body = (notes or "").strip()
    now = datetime.utcnow()
    async with _session(profile_id) as session:
        link = (await _live_links(session, [fingerprint])).get(fingerprint)
        note = await session.get(LoraNote, link.note_id) if link else None
        if not words and not body:
            if note:
                note.deleted_at = now
                rows = await session.execute(
                    select(LoraNoteFile).where(LoraNoteFile.note_id == note.id, LoraNoteFile.deleted_at.is_(None))
                )
                for row in rows.scalars():
                    row.deleted_at = now
                await session.commit()
            return
        if note is None:
            note = LoraNote(shared=False, created_at=now, updated_at=now)
            session.add(note)
            await session.flush()
            session.add(LoraNoteFile(fingerprint=fingerprint, note_id=note.id, last_seen_value=value, created_at=now))
        note.trigger_words = words
        note.notes = body
        note.updated_at = now
        if link and value:
            link.last_seen_value = value
        await session.commit()


async def share_note(profile_id: Optional[str], tool_id: str, value: str, replace: bool = False) -> Dict[str, Any]:
    """Share this file's note with its detected series, in one transaction.

    Returns {"status": "shared" | "conflict" | "noop" | "unavailable", "conflicts": n}.
    """
    snapshot = await _fetch_fingerprints(tool_id)
    if snapshot is None or value not in snapshot.fingerprints:
        return {"status": "unavailable", "conflicts": 0}
    fingerprint = snapshot.fingerprints[value]
    if not fingerprint:
        return {"status": "unavailable", "conflicts": 0}
    key = series_key(value)[0]
    members = {m: snapshot.fingerprints[m] for m in snapshot.values if series_key(m)[0] == key}
    member_fingerprints = {f for f in members.values() if f}
    now = datetime.utcnow()
    async with _session(profile_id) as session:
        links = await _live_links(session, list(member_fingerprints))
        source_link = links.get(fingerprint)
        if not source_link:
            return {"status": "noop", "conflicts": 0}
        notes = await _live_notes(session, [link.note_id for link in links.values()])
        target = notes.get(source_link.note_id)
        if target is None:
            return {"status": "noop", "conflicts": 0}
        conflicts = sum(
            1
            for f, link in links.items()
            if link.note_id != target.id and link.note_id in notes and not _same_text(notes[link.note_id], target)
        )
        if conflicts and not replace:
            return {"status": "conflict", "conflicts": conflicts}

        target.shared = True
        target.updated_at = now
        displaced = set()
        for f, link in links.items():
            if link.note_id != target.id:
                link.deleted_at = now
                displaced.add(link.note_id)
        await session.flush()
        value_for = {f: m for m, f in members.items() if f}
        for f in member_fingerprints:
            if f not in links or links[f].note_id != target.id:
                session.add(LoraNoteFile(fingerprint=f, note_id=target.id, last_seen_value=value_for.get(f), created_at=now))
        for note_id in displaced:
            await _retire_if_unlinked(session, note_id, now)
        await session.commit()
    return {"status": "shared", "conflicts": conflicts}


async def unshare_note(profile_id: Optional[str], fingerprint: str) -> bool:
    """Keep a private copy on this file and remove the shared note from the rest."""
    now = datetime.utcnow()
    async with _session(profile_id) as session:
        link = (await _live_links(session, [fingerprint])).get(fingerprint)
        note = await session.get(LoraNote, link.note_id) if link else None
        if note is None or note.deleted_at is not None:
            return False
        rows = await session.execute(
            select(LoraNoteFile).where(LoraNoteFile.note_id == note.id, LoraNoteFile.deleted_at.is_(None))
        )
        for row in rows.scalars():
            row.deleted_at = now
        note.deleted_at = now
        await session.flush()
        private = LoraNote(
            trigger_words=list(note.trigger_words or []),
            notes=note.notes,
            shared=False,
            created_at=now,
            updated_at=now,
        )
        session.add(private)
        await session.flush()
        session.add(
            LoraNoteFile(fingerprint=fingerprint, note_id=private.id, last_seen_value=link.last_seen_value, created_at=now)
        )
        await session.commit()
    return True
