"""Timers the chat agent sets for itself.

The agent can only act during a turn, and a turn only starts when something
speaks to it. A timer is how it speaks to itself later: "check on the renders
in 20 minutes", or, for work the user asked to run for hours, "every 15
minutes, keep going". When a timer comes due, the chat gets a ``<timer>``
message, which reaches the agent the way a background task's notification
does: a running turn hears it at its next step, an idle chat gets a new turn.

Timers live in the database (``agent_timers``) so a server restart doesn't
lose them; one that came due while the server was down fires on startup.
Stopping the agent from the UI ends the chat's timers, so Stop always means
stop.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.logging import get_logger

log = get_logger(__name__)

MIN_MINUTES = 1.0
MAX_MINUTES = 7 * 24 * 60.0
MAX_ACTIVE_PER_CHAT = 5
NOTE_LIMIT = 2000
POLL_SECONDS = 10.0
# A timer this late (the server was down, or busy) says so when it fires.
LATE_AFTER = timedelta(minutes=2)


# When the user last pressed Stop in each chat (monotonic), by (profile, chat).
# A firing claimed before a Stop, or code started before one, must not bring
# the agent back.
_stopped_at: dict[tuple[str, int], float] = {}


def _chat_key(chat_id: int) -> tuple[str, int]:
    from core.profile_context import get_current_profile
    return get_current_profile(), chat_id


def note_stop(chat_id: int) -> None:
    _stopped_at[_chat_key(chat_id)] = time.monotonic()


def stopped_since(chat_id: int, since: float) -> bool:
    return _stopped_at.get(_chat_key(chat_id), float("-inf")) >= since


def local_time(dt: Optional[datetime]) -> Optional[str]:
    """A stored UTC-naive time as the server's local clock, like message stamps."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def duration(seconds: float) -> str:
    """'45 min', '2 h 5 min', '3 days 4 h'."""
    minutes = int(round(seconds / 60))
    if minutes < 60:
        return f"{minutes} min"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"{hours} h {minutes} min" if minutes else f"{hours} h"
    days, hours = divmod(hours, 24)
    return f"{days} days {hours} h" if hours else f"{days} days"


def timer_ref(timer_id: int) -> str:
    return f"timer-{timer_id}"


def parse_ref(ref: Any) -> int:
    text = str(ref).strip()
    if text.startswith("timer-"):
        text = text[len("timer-"):]
    try:
        return int(text)
    except ValueError:
        raise ValueError(f"No such timer {ref!r}; timers look like 'timer-3'.") from None


def describe(timer) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": timer_ref(timer.id),
        "note": timer.note,
        "every_minutes" if timer.repeat else "after_minutes": round(timer.interval_s / 60, 2),
        "repeats": bool(timer.repeat),
        "set_at": local_time(timer.created_at),
        "fired": timer.fire_count,
    }
    if timer.ended_at is None:
        out["state"] = "active"
        out["next_fires_at"] = local_time(timer.fire_at)
        out["fires_in"] = duration(max(0.0, (timer.fire_at - datetime.utcnow()).total_seconds()))
        out["fire_at_utc"] = timer.fire_at.replace(tzinfo=timezone.utc).isoformat()
    else:
        out["state"] = timer.end_reason or "ended"
    return out


async def create_timer(
    session: AsyncSession, chat_id: int, *, minutes: float, note: str, repeat: bool,
):
    from database import AgentTimer
    try:
        minutes = float(minutes)
    except (TypeError, ValueError):
        raise ValueError("minutes must be a number") from None
    if not (MIN_MINUTES <= minutes <= MAX_MINUTES):
        raise ValueError(f"minutes must be between {MIN_MINUTES:g} and {MAX_MINUTES:g} (7 days)")
    note = (note or "").strip()
    if not note:
        raise ValueError(
            "Give the timer a note: what to do when it fires. It's the only thing you'll "
            "have to go on then, so say the goal and how long the user wants it to run."
        )
    if len(note) > NOTE_LIMIT:
        raise ValueError(f"The note is {len(note)} characters; keep it under {NOTE_LIMIT}.")
    active = (await session.execute(
        select(AgentTimer).where(AgentTimer.chat_id == chat_id, AgentTimer.ended_at.is_(None))
    )).scalars().all()
    if len(active) >= MAX_ACTIVE_PER_CHAT:
        refs = ", ".join(timer_ref(t.id) for t in active)
        raise ValueError(
            f"This chat already has {len(active)} active timers ({refs}); cancel one first."
        )
    now = datetime.utcnow()
    interval_s = int(round(minutes * 60))
    timer = AgentTimer(
        chat_id=chat_id,
        note=note,
        interval_s=interval_s,
        repeat=bool(repeat),
        fire_at=now + timedelta(seconds=interval_s),
        created_at=now,
    )
    session.add(timer)
    await session.commit()
    await session.refresh(timer)
    await _broadcast_changed(chat_id)
    return timer


async def list_timers(session: AsyncSession, chat_id: int) -> list:
    """The chat's active timers, oldest first."""
    from database import AgentTimer
    return list((await session.execute(
        select(AgentTimer).where(AgentTimer.chat_id == chat_id, AgentTimer.ended_at.is_(None))
        .order_by(AgentTimer.id)
    )).scalars().all())


async def end_timers(
    session: AsyncSession, chat_id: int, *, timer_id: Optional[int] = None, reason: str = "cancelled",
) -> list:
    """End one timer, or all of the chat's active ones. Returns those ended."""
    from database import AgentTimer
    q = select(AgentTimer).where(AgentTimer.chat_id == chat_id, AgentTimer.ended_at.is_(None))
    if timer_id is not None:
        q = q.where(AgentTimer.id == timer_id)
    rows = list((await session.execute(q)).scalars().all())
    now = datetime.utcnow()
    for t in rows:
        t.ended_at = now
        t.end_reason = reason
    if rows:
        await session.commit()
        await _broadcast_changed(chat_id)
    return rows


async def _broadcast_changed(chat_id: int) -> None:
    try:
        from utils.websocket import ws_manager
        await ws_manager.broadcast("agent_timers_changed", {"chat_id": chat_id})
    except Exception as e:  # the UI refetches on its own next load
        log.debug(f"timers: broadcast failed: {e}")


# ---------------------------------------------------------------------------
# Firing
# ---------------------------------------------------------------------------


def timer_text(timer, *, due_at: datetime, now: datetime, since_user: Optional[float]) -> str:
    lines = ["<timer>"]
    if timer.repeat:
        head = (
            f"Your timer {timer_ref(timer.id)} fired (it repeats every "
            f"{duration(timer.interval_s)}; set {local_time(timer.created_at)}, "
            f"this is firing {timer.fire_count})."
        )
    else:
        head = (
            f"Your timer {timer_ref(timer.id)} fired (set {local_time(timer.created_at)}, "
            f"for {duration(timer.interval_s)} later)."
        )
    lines.append(head)
    if now - due_at > LATE_AFTER:
        lines.append(
            f"It was due at {local_time(due_at)} and is {duration((now - due_at).total_seconds())} "
            "late, most likely because the Stimma server wasn't running."
        )
    if since_user is not None:
        lines.append(f"The user's last message was {duration(since_user)} ago.")
    lines.append(f"Your note: {timer.note}")
    if timer.repeat:
        lines.append(
            f"It fires again at {local_time(timer.fire_at)}. Cancel it with "
            f'stimma.timers.cancel("{timer_ref(timer.id)}") once the work is done.'
        )
    lines.append("</timer>")
    return "\n".join(lines)


async def _last_user_message_at(session: AsyncSession, chat_id: int) -> Optional[datetime]:
    """When the user (not a notification or timer) last wrote in the chat."""
    import json
    from database import ChatItem
    rows = (await session.execute(
        select(ChatItem.created_at, ChatItem.item_metadata).where(
            ChatItem.chat_id == chat_id, ChatItem.item_type == "user_message",
        ).order_by(ChatItem.id.desc()).limit(50)
    )).all()
    for created_at, meta in rows:
        try:
            m = json.loads(meta) if meta else {}
        except (ValueError, TypeError):
            m = {}
        if not isinstance(m, dict) or not (m.get("background_task") or m.get("timer")):
            return created_at
    return None


async def fire_due_timers(profile_id: str) -> int:
    """Fire every timer of this profile that is due. Returns how many fired."""
    from core.profile_context import set_current_profile
    from database import AgentTimer, Chat
    from database_registry import get_database_registry

    set_current_profile(profile_id)
    db = get_database_registry().get_database(profile_id)
    now = datetime.utcnow()
    claimed = time.monotonic()
    notes: list[tuple[int, dict]] = []
    async with db.async_session_maker() as session:
        due = (await session.execute(
            select(AgentTimer).where(AgentTimer.ended_at.is_(None), AgentTimer.fire_at <= now)
            .order_by(AgentTimer.fire_at)
        )).scalars().all()
        for timer in due:
            chat = await session.get(Chat, timer.chat_id)
            if chat is None or chat.deleted_at is not None:
                timer.ended_at = now
                timer.end_reason = "chat_deleted"
                continue
            due_at = timer.fire_at
            timer.fire_count += 1
            timer.last_fired_at = now
            if timer.repeat:
                # Missed firings (server down) collapse into this one.
                timer.fire_at = now + timedelta(seconds=timer.interval_s)
            else:
                timer.ended_at = now
                timer.end_reason = "fired"
            last_user = await _last_user_message_at(session, timer.chat_id)
            since_user = (now - last_user).total_seconds() if last_user else None
            notes.append((timer.chat_id, {
                "text": timer_text(timer, due_at=due_at, now=now, since_user=since_user),
                "task": {"id": timer_ref(timer.id)},
                "metadata": {"timer": {
                    "id": timer_ref(timer.id), "note": timer.note,
                    "repeats": bool(timer.repeat), "fired": timer.fire_count,
                }},
            }))
        if due:
            await session.commit()

    from utils.websocket import ws_manager
    from .service import deliver_background_notification
    for chat_id, note in notes:
        await _broadcast_changed(chat_id)
        # Delivery can run a whole agent turn; never hold the scheduler for it.
        asyncio.create_task(_deliver(profile_id, chat_id, note, ws_manager, deliver_background_notification, claimed))
    return len(notes)


async def _deliver(profile_id, chat_id, note, ws_manager, deliver, claimed: float) -> None:
    from core.profile_context import set_current_profile
    set_current_profile(profile_id)
    try:
        # Stopped since this firing was claimed: record it, but don't wake.
        await deliver(chat_id, note, ws_manager, wake=not stopped_since(chat_id, claimed))
    except Exception as e:
        log.error(f"Chat {chat_id}: timer delivery failed: {e}", exc_info=True)


async def run_scheduler() -> None:
    """Fire due timers for every profile, forever."""
    from database_registry import get_database_registry
    while True:
        try:
            for profile in get_database_registry().list_profiles():
                try:
                    await fire_due_timers(profile["id"])
                except Exception as e:
                    log.warning(f"timers: profile {profile['id']} pass failed: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            log.warning(f"timers: scheduler pass failed: {e}")
        await asyncio.sleep(POLL_SECONDS)
