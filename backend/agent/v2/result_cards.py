"""Result cards: one chat card per generation run, filled in place.

A run_code that generates puts one card in the chat as soon as its first call
starts, and the results land in that card. There is no separate progress card
and no second card for the results: when the code shows them, the show claims
the card (commits the results, takes the title) instead of making a new one.

A card is one of two kinds, and only one of them has a count:

- **batch**: the run said how many it will make. A gather over N calls says N;
  ``stimma.batch(title, total=N)`` says it for calls made in a loop. The card
  has N slots from the start and they fill in place.
- **stream**: open-ended, ``stimma.stream(title)`` ("until I say stop"). Each
  call adds a slot as it starts; there is no total. A gather whose branches each
  make several calls (a worker pool) is a stream too, unless declared a batch:
  its total would only be the calls started so far.

The card is a ``media_display`` chat item. Rows use the show card's row shape;
an unfinished row has ``output.status`` ``pending`` (waiting in the queue) or
``generating``. ``display_data.mode`` is ``batch`` or ``stream`` and a batch
carries ``total``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from .background import CallItem

log = logging.getLogger(__name__)

# The card (and, inside a gather, the branch index) the current call belongs to.
current_card: ContextVar[Optional[tuple["ResultCard", Optional[int]]]] = ContextVar(
    "result_card", default=None
)

_NOUNS = {"image": "images", "video": "videos", "audio": "audio clips"}
# How often unfinished rows ask the queue whether their job has started.
_JOB_STATE_SECONDS = 2.0


@dataclass(eq=False)
class Slot:
    key: int
    call: Optional["CallItem"] = None
    status: str = "pending"  # pending | generating | complete | failed | cancelled | empty
    media_id: Optional[int] = None
    file_format: Optional[str] = None
    asset_id: Optional[int] = None
    error: Optional[str] = None

    def row(self, ended: bool = False) -> dict[str, Any]:
        output: dict[str, Any] = {"status": self.status}
        if self.media_id is not None:
            output["media_id"] = self.media_id
        if self.file_format:
            output["file_format"] = self.file_format
        if self.asset_id is not None:
            output["asset_id"] = self.asset_id
        if self.error:
            output["error"] = self.error
        if ended and self.status == "failed" and self.call is not None and self.call.job_id is not None:
            # Retry re-runs the job, and the card then follows it itself. While
            # the run goes on the run writes the card, so no handle until it ends.
            output["job_id"] = self.call.job_id
        return {"id": f"slot_{self.key}", "input": {"type": "output_only"}, "output": output}


class ResultCard:
    def __init__(self, *, title: Optional[str] = None, total: Optional[int] = None,
                 stream: bool = False, declared: bool = False):
        self.title = title
        self.stream = stream
        # A batch the code declared keeps its count even when calls come from workers.
        self.declared = declared
        self.slots: list[Slot] = []
        self._next_key = 0
        self.role = "intermediate"
        # A show has put its results here: later shows under the title join it.
        self.claimed = False
        self.item_id: Optional[int] = None
        self.status = "in_progress"
        # The run is over: nothing will write the card again. (A gather's card
        # is complete between gathers, but a later one can reopen it.)
        self.ended = False
        self.kind: Optional[str] = None
        self.dirty = False
        self._branch_calls: dict[int, int] = {}
        self._branch_slot: dict[int, Slot] = {}
        self._last_job_check = 0.0
        self._write_lock: Optional[asyncio.Lock] = None
        if total:
            self.add_slots(total)

    @property
    def write_lock(self) -> asyncio.Lock:
        # Created on first use, inside the loop that writes the card.
        if self._write_lock is None:
            self._write_lock = asyncio.Lock()
        return self._write_lock

    # -- building --------------------------------------------------------------

    def add_slots(self, n: int) -> list[Slot]:
        added = []
        for _ in range(n):
            slot = Slot(key=self._next_key)
            self._next_key += 1
            self.slots.append(slot)
            added.append(slot)
        self.dirty = True
        return added

    def reopen(self, n: int) -> list[Slot]:
        """Another gather in the same run: a loop of batches is open-ended."""
        if not self.declared:
            self.stream = True
        self.status = "in_progress"
        return self.add_slots(n)

    @property
    def live(self) -> bool:
        """Has a call started? Until then the card isn't in the chat."""
        return any(slot.call is not None or slot.media_id is not None for slot in self.slots)

    def begin(self, branch: Optional[int], call: "CallItem", task: Optional[str]) -> Slot:
        """A generation call starts; give it its slot."""
        from .background import _media_kind
        self.kind = self.kind or _media_kind(task)
        slot: Optional[Slot] = None
        if branch is not None and branch in self._branch_slot:
            calls = self._branch_calls.get(branch, 0)
            if calls == 0:
                slot = self._branch_slot[branch]
            elif not self.declared:
                # One branch making call after call is a worker: its total is
                # only the calls started so far, so it gets no count.
                self.stream = True
            self._branch_calls[branch] = calls + 1
        if slot is None and not self.stream:
            bound = {id(s) for s in self._branch_slot.values()}
            slot = next((s for s in self.slots if s.call is None and s.status == "pending"
                         and id(s) not in bound), None)
        if slot is None:
            slot = self.add_slots(1)[0]
        slot.call = call
        slot.status = "pending"
        self.dirty = True
        return slot

    def bind_branches(self, slots: list[Slot], base: int = 0) -> None:
        for offset, slot in enumerate(slots):
            self._branch_slot[base + offset] = slot

    def done(self, slot: Slot, media_id: Optional[int], path: Optional[str]) -> None:
        slot.status = "complete"
        slot.media_id = media_id
        if path:
            slot.file_format = Path(path).suffix.lstrip(".").lower() or None
        self.dirty = True

    def failed(self, slot: Slot, error: BaseException) -> None:
        from .background import GenerationCancelled
        if isinstance(error, (GenerationCancelled, asyncio.CancelledError)) or (
                slot.call is not None and slot.call.cancel_requested):
            slot.status = "cancelled"
        else:
            slot.status = "failed"
            slot.error = f"{type(error).__name__}: {error}"[:300]
        self.dirty = True

    def adopt(self, branch: int, media_id: int, path: Optional[str]) -> None:
        """A branch returned a result its slot never saw: a Task created before
        the gather keeps the context it was made in, so its call wasn't ours."""
        if self.holds(media_id):
            return
        slot = self._branch_slot.get(branch)
        if slot is None or slot.media_id is not None:
            slot = self.add_slots(1)[0]
        self.done(slot, media_id, path)

    def finish_batch(self) -> None:
        """A gather ended: branches that never generated hold no slot."""
        for slot in self.slots:
            if slot.call is None and slot.media_id is None and slot.status == "pending":
                slot.status = "empty"
        self._branch_slot.clear()
        self._branch_calls.clear()
        self.dirty = True

    def finish(self, reason: str) -> None:
        for slot in self.slots:
            if slot.status in ("pending", "generating"):
                slot.status = "cancelled" if slot.call is not None else "empty"
        self.status = "complete" if reason == "completed" else "cancelled"
        self.dirty = True

    # -- shows -------------------------------------------------------------------

    def holds(self, media_id: int) -> bool:
        return any(s.media_id == media_id for s in self.slots)

    def attach(self, media_id: int, asset_id: Optional[int], file_format: Optional[str]) -> None:
        """A show put this result here: it's in the card, committed or kept."""
        slot = next((s for s in self.slots if s.media_id == media_id), None)
        if slot is None:
            slot = self.add_slots(1)[0]
            slot.status = "complete"
            slot.media_id = media_id
            slot.file_format = file_format
        if asset_id is not None:
            slot.asset_id = asset_id
        self.dirty = True

    # -- state -------------------------------------------------------------------

    def _visible(self) -> list[Slot]:
        return [s for s in self.slots if s.status not in ("cancelled", "empty")]

    def default_title(self) -> str:
        noun = _NOUNS.get(self.kind or "", "results")
        if self.stream:
            return noun.capitalize()
        return f"{len(self._visible())} {noun}"

    def display_data(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "title": self.title or self.default_title(),
            "status": self.status,
            "mode": "stream" if self.stream else "batch",
            "rows": [s.row(ended=self.ended) for s in self._visible()],
        }
        if not self.stream:
            data["total"] = len(self._visible())
        return data

    def summary(self) -> dict[str, Any]:
        """What the background bar says about this card."""
        visible = self._visible()
        out: dict[str, Any] = {"title": self.title or self.default_title()}
        if self.stream:
            out["open"] = True
        else:
            out["done"] = sum(1 for s in visible if s.status == "complete")
            out["failed"] = sum(1 for s in visible if s.status == "failed")
            out["total"] = len(visible)
        return out

    def media_ids(self) -> list[int]:
        return [s.media_id for s in self._visible() if s.media_id is not None]

    def asset_ids(self) -> list[int]:
        return [s.asset_id for s in self._visible() if s.asset_id is not None]

    async def refresh_job_states(self, session_maker) -> None:
        """Rows whose job the queue has started read ``generating``."""
        now = time.monotonic()
        if now - self._last_job_check < _JOB_STATE_SECONDS:
            return
        self._last_job_check = now
        waiting = {s.call.job_id: s for s in self.slots
                   if s.status in ("pending", "generating") and s.call is not None and s.call.job_id is not None}
        if not waiting or session_maker is None:
            return
        try:
            from sqlalchemy import select
            from database import GenerationJob
            async with session_maker() as session:
                rows = (await session.execute(
                    select(GenerationJob.id, GenerationJob.status).where(GenerationJob.id.in_(list(waiting)))
                )).all()
        except Exception as e:
            log.debug(f"result card: job status lookup failed: {e}")
            return
        for job_id, status in rows:
            slot = waiting[job_id]
            if slot.status not in ("pending", "generating"):
                continue  # it finished while the queue was asked
            state = "generating" if status == "processing" else "pending"
            if slot.status != state:
                slot.status = state
                self.dirty = True


def run_progress(cards: list[ResultCard]) -> Optional[dict[str, Any]]:
    """One line for the background bar from a run's cards: X of Y, or open."""
    live = [c for c in cards if c.live]
    if not live:
        return None
    summaries = [c.summary() for c in live]
    title = summaries[-1]["title"] if len(live) == 1 else None
    if any(s.get("open") for s in summaries):
        return {"open": True, "title": title}
    return {
        "title": title,
        "done": sum(s["done"] for s in summaries),
        "failed": sum(s["failed"] for s in summaries),
        "total": sum(s["total"] for s in summaries),
    }


def shown_receipt(media_ids: list[int], asset_by_media: dict[int, Optional[int]]) -> str:
    base = "Displayed 1 item to user." if len(media_ids) == 1 else f"Displayed {len(media_ids)} items to user."
    return base + " " + ", ".join(
        f"media_id={mid} asset_id={asset_by_media[mid]}" if asset_by_media.get(mid) is not None
        else f"media_id={mid}"
        for mid in media_ids
    )


def card_item_fields(card: ResultCard) -> dict[str, Any]:
    media = card.media_ids()
    assets = card.asset_ids()
    return {
        "media_id": media[0] if len(media) == 1 else None,
        "media_ids": json.dumps(media) if media else None,
        "asset_id": assets[0] if len(assets) == 1 else None,
        "asset_ids": json.dumps(assets) if assets else None,
        # No role until a show claims the card: mid-run, "kept with this chat"
        # would label work that is still arriving. Unclaimed at the end, it is.
        "show_role": card.role if card.claimed or card.status != "in_progress" else None,
        "item_metadata": json.dumps({"display_data": card.display_data()}),
    }
