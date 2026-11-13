"""What a prompt's slots draw from: their pools of variants, written in the background.

realize() asks `runtime_for()` for a prepared prompt's Variants: per slot its pool (or the
stand-in it had before an edit), the use counts and the user's choice. A recorded revision
replays the texts it drew.

When readings and their seeds land, `start_pools()` queues the first write of every pool the
prompt's slots need (variant_pools.PoolWriter). It returns at once; nothing waits for it. A
shipped draw is counted (`count_draw`), which tops a pool up when 80% of it has been drawn.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger
from prompt_programs.fill import ProgramError
from prompt_programs.variant_pools import (
    Choice, Job, Pick, PoolWriter, VariantStore, person_pickers, store_for, writer_for,
)
from prompt_programs.variants import Slot

log = get_logger(__name__)

# A revision records the judge it drew with. Drawing judged nothing, so only a revision
# drawn that way (or recording none) replays exactly.
UNJUDGED = (None, "null")
ENGINE = "variants-1"


def has_draws(entry: Dict[str, Any]) -> bool:
    """Whether a prepared prompt has anything to draw: a slot read, or a user list."""
    return any(s.get("state") == "ready" and not s.get("degraded") for s in entry.get("slots") or []) \
        or any(p.get("source") == "list" for p in entry.get("picks") or [])


def _store(profile_id: Optional[str]) -> Optional[VariantStore]:
    try:
        return store_for(profile_id)
    except Exception as e:   # no profile (scripts): slots stand as their words
        log.debug(f"[fluent] no variant store: {e}")
        return None


def _writer(profile_id: Optional[str]) -> Optional[PoolWriter]:
    try:
        return writer_for(profile_id)
    except Exception as e:
        log.debug(f"[fluent] no pool writer: {e}")
        return None


class Variants:
    """The options service a fill draws slots through (fill.OptionsService)."""

    def __init__(self, store: Optional[VariantStore], chosen: Optional[Dict[str, Choice]] = None,
                 fixed: Optional[Dict[str, str]] = None):
        self.store = store
        self.chosen = dict(chosen or {})
        self.fixed = dict(fixed or {})          # a replay's texts, per slot
        self._overlay: Dict[str, Dict[str, int]] = {}   # draws already made in this batch, per pool

    def pool(self, slot: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        if self.store is None or not slot.get("pool"):
            return [], {}
        key = str(slot["pool"])
        got = self.store.variants(key)
        if not got and slot.get("stand_in"):
            key = str(slot["stand_in"])
            got = self.store.variants(key)
        uses = dict(self.store.uses(key))
        for t, n in self._overlay.get(key, {}).items():
            uses[t] = uses.get(t, 0) + n
        return got, uses

    def choice(self, slot_id: str) -> Choice:
        return self.chosen.get(slot_id) or Choice()

    def note(self, entry: Dict[str, Any], result: Any) -> None:
        """Count a batch's draw in memory, so the next draw of the batch takes another variant
        (generate-forever's buffer draws several at once, before any is counted on disk)."""
        pools = {s["id"]: s.get("pool") for s in entry.get("slots") or []}
        for d in getattr(result, "draws", []) or []:
            key = pools.get(d.id)
            if key and d.value and d.source in ("variant", "own", "pinned"):
                n = " ".join(str(d.value).split()).lower()
                bucket = self._overlay.setdefault(str(key), {})
                bucket[n] = bucket.get(n, 0) + 1


def runtime_for(entry: Dict[str, Any], *, chosen: Optional[Dict[str, Choice]] = None,
                profile_id: Optional[str] = None, project_id: Optional[int] = None,
                revision: Optional[Dict[str, Any]] = None, store: Optional[VariantStore] = None) -> Variants:
    """What realize() draws a prepared prompt's slots with. A recorded `revision` replays the
    texts it drew; one drawn by an earlier Fluent can't be redrawn (its image keeps its text)."""
    rev = revision if isinstance(revision, dict) else {}
    if rev.get("judge") not in UNJUDGED:
        raise ProgramError(f"This prompt was drawn with judge {rev.get('judge')}, which this version of Stimma doesn't "
                           "have, so it can't be replayed exactly.")
    fixed: Dict[str, str] = {}
    if rev:
        if rev.get("engine") != ENGINE:
            raise ProgramError("This image was drawn by an earlier Fluent; its prompt is kept as it was made, "
                               "and it can't be drawn again exactly.")
        fixed = {str(k): str(v.get("text")) for k, v in (rev.get("variants") or {}).items()
                 if isinstance(v, dict) and v.get("text")}
    return Variants(store if store is not None else _store(profile_id), chosen, fixed)


def attach_writer(entry: Dict[str, Any], profile_id: Optional[str] = None) -> None:
    """Call from async code before realize() runs in a worker thread, so the pool writes a draw
    starts have the event loop to run on."""
    if has_draws(entry):
        _writer(profile_id)


attach_filler = attach_writer   # (its old name, for callers that start background work)


# --------------------------------------------------------------------------- writing pools

def slot_job(entry: Dict[str, Any], slot: Dict[str, Any], *, model: str = "", project_id: Optional[int] = None
             ) -> Optional[Job]:
    """The write a slot's pool needs, or None while its seeds aren't narrowed yet (or it has no pool)."""
    from prompt_programs.seeding import seeds_of
    record = (entry.get("seeds") or {}).get(slot["id"])
    if not slot.get("pool") or record is None or slot["id"] in (entry.get("seeds_pending") or []):
        return None
    span = slot.get("span") or [0, 0]
    sl = Slot(words=slot["words"], prompt=str(entry.get("prompt") or ""), span=(int(span[0]), int(span[1])),
              kind=str(slot.get("kind") or "free"), category=str(slot.get("category") or ""))
    return Job(key=str(slot["pool"]), slot=sl, seeds=seeds_of(record), project_id=project_id, model=model)


def _model(entry: Dict[str, Any]) -> str:
    return str(entry.get("model") or "")


def start_pools(entry: Dict[str, Any], *, profile_id: Optional[str] = None, project_id: Optional[int] = None,
                chosen: Optional[Dict[str, Choice]] = None, writer: Optional[PoolWriter] = None,
                retry: bool = False) -> List[str]:
    """Queue the first write of each read slot's pool that has none, and a batch for seeds the
    user picked that nothing in a pool matches yet. A write that failed is asked again only after a
    while, or at once with `retry` (an explicit retry). Returns the pool keys queued. Never calls
    a model itself and never raises."""
    out: List[str] = []
    try:
        w = writer or _writer(profile_id)
        if w is None:
            return out
        for s in entry.get("slots") or []:
            if s.get("state") != "ready" or s.get("degraded"):
                continue
            job = slot_job(entry, s, model=_model(entry), project_id=project_id)
            if job is None:
                continue
            if w.submit(job, retry=retry):
                out.append(job.key)
            c = (chosen or {}).get(s["id"])
            if c is not None and w.picked(slot_job(entry, s, model=_model(entry), project_id=project_id), c):
                out.append(job.key)
    except Exception as e:
        log.warning(f"[fluent] couldn't start the pools of {entry.get('key')}: {e}")
    return out


def count_draw(entry: Dict[str, Any], result: Any, *, profile_id: Optional[str] = None,
               project_id: Optional[int] = None, chosen: Optional[Dict[str, Choice]] = None) -> None:
    """Count a shipped draw's variants (a generation, a buffered draw); a pool 80% drawn this
    round tops up in the background. Never raises."""
    try:
        w = _writer(profile_id)
        if w is None:
            return
        slots = {s["id"]: s for s in entry.get("slots") or []}
        for d in getattr(result, "draws", []) or []:
            s = slots.get(d.id)
            if s is None or not s.get("pool"):
                continue
            job = slot_job(entry, s, model=_model(entry), project_id=project_id)
            if job is None:
                continue
            w.drew(job, Pick(d.value, d.source, dict(d.seeds or {})), choice=(chosen or {}).get(d.id))
    except Exception as e:
        log.warning(f"[fluent] counting a draw of {entry.get('key')} failed: {e}")


def slot_state(entry: Dict[str, Any], slot: Dict[str, Any], writer: Optional[PoolWriter]) -> str:
    """reading | writing | ready | as_written (stimma-plans VARIANTS_IMPL.md section 1)."""
    if slot.get("state") != "ready":
        return "reading"
    if slot.get("degraded"):
        return "as_written"
    if writer is None or not slot.get("pool"):
        return "writing"
    return writer.state(str(slot["pool"]), slot.get("stand_in"))


async def more_like_these(entry: Dict[str, Any], slot_id: str, *, profile_id: Optional[str] = None,
                          project_id: Optional[int] = None, chosen: Optional[Dict[str, Choice]] = None) -> List[str]:
    """One more batch for a slot, awaited (the chooser's More like these): the new variants."""
    s = next((x for x in entry.get("slots") or [] if x.get("id") == slot_id), None)
    if s is None:
        raise ProgramError("That part of the prompt isn't there any more.")
    job = slot_job(entry, s, model=_model(entry), project_id=project_id)
    w = _writer(profile_id)
    if job is None or w is None:
        return []
    c = (chosen or {}).get(slot_id)
    if c is not None:
        job.pins = c.pins
    return await w.more(job)


# --------------------------------------------------------------------------- what a picker shows

def pool_view(entry: Dict[str, Any], chosen: Optional[Dict[str, Choice]] = None, *, profile_id: Optional[str] = None,
              project_id: Optional[int] = None) -> Dict[str, Any]:
    """Per slot what its picker shows (VARIANTS_IMPL.md section 4): its state, its variants with
    their seeds and use counts, the user's own, the choice as read, and for a person the descent
    and gender pickers. Starts any write it needs; never calls a model or waits."""
    chosen = dict(chosen or {})
    store, writer = _store(profile_id), _writer(profile_id)
    start_pools(entry, profile_id=profile_id, project_id=project_id, chosen=chosen, writer=writer)
    rt = Variants(store, chosen)
    out: Dict[str, Any] = {}
    busy: List[str] = []
    for s in entry.get("slots") or []:
        sid = s["id"]
        c = chosen.get(sid) or Choice()
        variants, uses = rt.pool(s) if s.get("state") == "ready" and not s.get("degraded") else ([], {})
        have = {" ".join(v["text"].split()).lower() for v in variants}
        listed = [{"text": v["text"], "seeds": dict(v.get("seeds") or {}),
                   "uses": uses.get(" ".join(v["text"].split()).lower(), 0), "own": False} for v in variants]
        listed += [{"text": t, "seeds": {}, "uses": uses.get(" ".join(t.split()).lower(), 0), "own": True}
                   for t in c.add if " ".join(t.split()).lower() not in have]
        more = bool(writer is not None and s.get("pool") and writer.busy(str(s["pool"])))
        if more:
            busy.append(sid)
        from prompt_programs.variants import kept_chunks, valid_category
        keep = kept_chunks(s["words"], valid_category(s["words"], s.get("category") or "", str(s.get("kind") or "")))
        view: Dict[str, Any] = {"kind": "variants", "state": slot_state(entry, s, writer), "more": more, "keep": keep,
                                "variants": listed, "options": [v["text"] for v in listed], "chosen": c.to_dict()}
        if s.get("kind") == "person" and not s.get("degraded"):
            record = (entry.get("seeds") or {}).get(sid) or {}
            banks = {b.get("role"): b for b in record.get("banks") or []}
            fits = (banks.get("descent") or {}).get("narrowed")
            gfits = (banks.get("gender") or {}).get("narrowed")
            view["person"] = person_pickers(variants, c, fits=fits if isinstance(fits, list) else None,
                                            gender_fits=gfits if isinstance(gfits, list) else None)
        out[sid] = view
    return {"choices": out, "more": busy}


__all__ = ["ENGINE", "Variants", "attach_filler", "attach_writer", "count_draw", "has_draws", "more_like_these",
           "pool_view", "runtime_for", "slot_job", "slot_state", "start_pools"]
