"""A slot's pool of variants: stored per profile, drawn least-used first, topped up in the background.

The writer (variants.py) writes a slot's variants; this module keeps them and draws from them
with no model call:

- The store. One append-only JSONL file per pool, one line per writer call that kept anything
  (`{"batch", "role", "variants": [{"text", "seeds"}], ...}`), and the pool's use counts beside
  it. A pool is keyed by the model, the slot's words, the line its reading was made in and the
  prompt's notes (pool_key): the context the quiet re-read uses, never the whole prompt; an edit
  elsewhere that the check says changes the scene adds a mark of it.
- Drawing. Per image, per slot: left out, as written, a fixed (replayed) text, the variants the
  user pinned, the variants whose seeds match the seeds the user picked, else any variant; each
  time the least-used one, ties broken by the draw's seeded RNG. A slot with no pool yet goes in
  as its own words. Never an error and never nothing to draw.
- Writing. Each pool has one chat session (variants.Session), stored beside it
  (`<key>.session.json`), and every write is one or more turns of it: the first pool, a
  background top-up (after a counted draw, when 80% of what the slot draws from has been drawn
  this round), "More like these" (awaited) and a batch for seeds the user picked. A pool runs one
  turn at a time, the most urgent waiting one next (what someone waits for, then first writes,
  then top-ups), so a turn someone waits for never opens a second, blind conversation. Slots run
  side by side under a cap of STREAMS streams per profile, every slot's first turn ahead of any
  slot's later ones. Each variant is stored the moment its object closes in the stream. A slot not
  about a person whose seeds are still narrowed opens its session with one unseeded turn (role
  "early"); the seeded turns that follow continue that log, and it counts toward its pool.

A failed write is never stored: the slot stands as written and the next prepare that starts
work asks again.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import heapq
import itertools
import json
import os
import random
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.variants import (
    AGE, DESCENT, GENDER, HAVE_SHOWN, MIN_POOL, MORE_TURNS, STAGE, TOPUP, TURN, VARIANTS_VERSION, Ask, Pins, Seeds, Session, Slot, Turn,
    age_stages, age_years, ask_writer, draw_seeds, first_turn, more_turn, reply_text, split, stages_of, write_turn,
    year_ages,
)

log = get_logger(__name__)

POOL_VERSION = "pool-1"
TOPUP_AT = 0.8      # share of what a slot draws from drawn this round that starts a top-up
MAX_POOL = 300      # a pool this big stops topping up and cycles least-used
RETRY_AFTER = 120.0 # seconds a failed first write stands as written before a prepare or poll asks again
MIN_MATCH = 8       # picked seeds that match fewer variants than this write more that match, at once
STREAMS = 6         # writer streams in flight per profile, one per pool at most. Measured on local
                    # models, four new slots each streaming turns of 10 show every slot's first variant
                    # in 1.4-2.9 s and fill all four in 32-33 s; every slot's first turn goes first.
URGENT_STREAMS = 2  # streams a pick or More like these may run beyond STREAMS, so it never queues behind first writes
GATE_SETTLE = 0.01  # seconds turns arriving together are gathered before any is granted, so the first
                    # turn of every slot a prepare starts goes ahead of any one slot's later turns
YIELD_POLL = 0.25   # seconds between looks while a background top-up gives way to a prepare
SEEDS_KEPT = 500    # draws with an explicit draw seed remembered per prompt


def pool_key(model: Optional[str], words: str, marked: str, notes: Sequence[str], minor: Sequence[str] = (),
             scene: str = "", place: str = "") -> str:
    """A pool's key: the model, the slot's words, the line its reading was made in (marked) and
    the prompt's notes; a person who may be under 18 has a pool of their own, and so does a slot
    read again because an edit elsewhere changed the scene (`scene`, reader.scene_mark), and a
    person whose place context differs (`place`, places.mark: "JP@prompt", "FR@default")."""
    parts: Dict[str, Any] = {"v": POOL_VERSION, "writer": VARIANTS_VERSION, "model": model, "words": words,
                             "marked": marked, "notes": list(notes)}
    if minor:
        parts["minor"] = sorted(minor)
    if scene:
        parts["scene"] = scene
    if place:
        parts["place"] = place
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


# --------------------------------------------------------------------------- the store

class VariantStore:
    """Pools on disk: `<key[:2]>/<key>.jsonl`, one line per stored variant and one per turn's
    tally, `<key>.uses.json`, the variants the user removed, `<key>.removed.json`, and the pool's
    session log, `<key>.session.json`."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._mem: Dict[str, Tuple[int, List[Dict[str, Any]]]] = {}

    def _path(self, key: str, suffix: str = ".jsonl") -> Path:
        from prompt_programs.store import valid_key
        if not valid_key(key):   # never a path out of the store
            raise ValueError(f"not a pool key: {key!r}")
        return self.root / key[:2] / f"{key}{suffix}"

    def batches(self, key: str) -> List[Dict[str, Any]]:
        try:
            p = self._path(key)
            size = p.stat().st_size
        except (OSError, ValueError):
            return []
        hit = self._mem.get(key)
        if hit and hit[0] == size:
            return hit[1]
        out: List[Dict[str, Any]] = []
        try:
            text = p.read_text("utf-8")
        except OSError:
            return []
        for ln in text.splitlines():
            try:
                rec = json.loads(ln)
            except ValueError:
                continue   # a line still being written
            if isinstance(rec, dict):
                out.append(rec)
        self._mem[key] = (size, out)
        return out

    def variants(self, key: str) -> List[Dict[str, Any]]:
        """The pool in order: {"text", "seeds", "batch"}; the first of two texts that differ only in
        case and spacing wins. A text the user removed is never in it."""
        seen: set = set(self.removed(key))
        out: List[Dict[str, Any]] = []
        for rec in self.batches(key):
            for v in rec.get("variants") or []:
                if not isinstance(v, dict) or not isinstance(v.get("text"), str) or not v["text"].strip():
                    continue
                n = _norm(v["text"])
                if n in seen:
                    continue
                seen.add(n)
                out.append({"text": v["text"], "seeds": dict(v.get("seeds") or {}), "batch": rec.get("batch")})
        return out

    def has(self, key: str) -> bool:
        return bool(self.variants(key))

    def append(self, key: str, record: Dict[str, Any]) -> None:
        p = self._path(key)
        line = json.dumps(record, ensure_ascii=False) + "\n"
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
            self._mem.pop(key, None)
        from prompt_programs.events import pool_changed
        pool_changed(key)

    def session(self, key: str) -> Dict[str, Any]:
        """The pool's session log as stored (variants.Session.to_dict), {} when there is none."""
        try:
            got = json.loads(self._path(key, ".session.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return got if isinstance(got, dict) else {}

    def save_session(self, key: str, session: Dict[str, Any]) -> None:
        """Replace the pool's session log (written whole after each turn that joins it)."""
        p = self._path(key, ".session.json")
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(session, f, ensure_ascii=False)
            os.replace(tmp, p)

    def removed(self, key: str) -> List[str]:
        """The texts removed from a pool (normalized)."""
        try:
            got = json.loads(self._path(key, ".removed.json").read_text("utf-8"))
        except (OSError, ValueError):
            return []
        return [str(t) for t in got if isinstance(t, str)] if isinstance(got, list) else []

    def remove(self, key: str, texts: Sequence[str]) -> None:
        """Remove variants from a pool for good: never drawn or listed again, even when a later
        batch writes the same text."""
        p = self._path(key, ".removed.json")
        with self._lock:
            got = list(dict.fromkeys([*self.removed(key), *(_norm(t) for t in texts if str(t).strip())]))
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(got, f, ensure_ascii=False)
            os.replace(tmp, p)

    def uses(self, key: str) -> Dict[str, int]:
        try:
            got = json.loads(self._path(key, ".uses.json").read_text("utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): int(v) for k, v in got.items() if isinstance(v, int)} if isinstance(got, dict) else {}

    def _seeds_path(self, entry_key: str) -> Path:
        from prompt_programs.store import valid_key
        if not valid_key(entry_key):
            raise ValueError(f"not a prompt key: {entry_key!r}")
        return self.root / "seeds" / entry_key[:2] / f"{entry_key}.json"

    def seeded(self, entry_key: str, seed: int) -> Dict[str, str]:
        """What a draw with an explicit draw seed drew for a prompt before ({slot: text}), so the
        same seed and choices repeat it though use counts have moved since; {} when none."""
        try:
            got = json.loads(self._seeds_path(entry_key).read_text("utf-8")).get(str(seed))
        except (OSError, ValueError, AttributeError):
            return {}
        return {str(k): str(v) for k, v in got.items()} if isinstance(got, dict) else {}

    def remember(self, entry_key: str, seed: int, texts: Dict[str, str]) -> None:
        """Keep a draw made with an explicit draw seed (the latest SEEDS_KEPT per prompt)."""
        p = self._seeds_path(entry_key)
        with self._lock:
            try:
                got = json.loads(p.read_text("utf-8"))
            except (OSError, ValueError):
                got = {}
            got = {k: v for k, v in got.items() if k != str(seed)} if isinstance(got, dict) else {}
            got[str(seed)] = dict(texts)
            got = dict(list(got.items())[-SEEDS_KEPT:])
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(got, f, ensure_ascii=False)
            os.replace(tmp, p)

    def mark_used(self, key: str, texts: Sequence[str]) -> Dict[str, int]:
        """Count one draw of each text; returns the counts after."""
        p = self._path(key, ".uses.json")
        with self._lock:
            got = self.uses(key)
            for t in texts:
                got[_norm(t)] = got.get(_norm(t), 0) + 1
            p.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(got, f, ensure_ascii=False)
            os.replace(tmp, p)
        return got

    def unmark_used(self, key: str, texts: Sequence[str]) -> None:
        """Take back one counted draw of each text (a buffered draw dropped before it shipped)."""
        p = self._path(key, ".uses.json")
        with self._lock:
            got = self.uses(key)
            for t in texts:
                n = _norm(t)
                if got.get(n, 0) > 1:
                    got[n] -= 1
                else:
                    got.pop(n, None)
            if not p.parent.is_dir():
                return
            fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(got, f, ensure_ascii=False)
            os.replace(tmp, p)


# --------------------------------------------------------------------------- the user's choice

@dataclass(frozen=True)
class Choice:
    """What the user chose for one slot in the chooser (choices.py hands it over)."""
    values: Tuple[str, ...] = ()       # pinned variants (a text not in the pool still holds)
    add: Tuple[str, ...] = ()          # the user's own variants: drawn with the pool
    as_written: bool = False
    off: bool = False
    pins: Pins = field(default_factory=Pins)

    @classmethod
    def of(cls, obj: Any, add: Sequence[str] = ()) -> "Choice":
        """A slot's choice from the editor's wire form (stimma-plans VARIANTS_IMPL.md section 4)."""
        def strings(v: Any) -> Tuple[str, ...]:
            items = v if isinstance(v, (list, tuple)) else [v] if v is not None else []
            return tuple(dict.fromkeys(str(x) for x in items if x is not None and str(x).strip()))
        def years(v: Any) -> Tuple[int, ...]:
            items = v if isinstance(v, (list, tuple)) else [v] if v is not None else []
            return tuple(dict.fromkeys(int(x) for x in items if not isinstance(x, bool) and
                                       (isinstance(x, int) or (isinstance(x, str) and x.strip().isdigit()))))
        o = obj if isinstance(obj, dict) else {}
        seeds = o.get("seeds") if isinstance(o.get("seeds"), dict) else {}
        d = seeds.get("descent") if isinstance(seeds.get("descent"), dict) else {}
        g = seeds.get("gender") if isinstance(seeds.get("gender"), dict) else {}
        a = seeds.get("age") if isinstance(seeds.get("age"), dict) else {}
        groups = d.get("groups") if isinstance(d.get("groups"), dict) else {}
        pins = Pins(descent=strings(d.get("values")), regions=strings(groups.get("region")),
                    gender=strings(g.get("values")), age=strings(a.get("values")), years=years(a.get("years")))
        return cls(values=strings(o.get("values")), add=tuple(dict.fromkeys([*strings(o.get("add")), *strings(add)])),
                   as_written=o.get("as_written") is True, off=o.get("off") is True, pins=pins)

    def to_dict(self) -> Optional[Dict[str, Any]]:
        """The choice as /pools echoes it, or None for no choice."""
        if self.off:
            return {"off": True}
        if self.as_written:
            return {"as_written": True}
        out: Dict[str, Any] = {}
        if self.values:
            out["values"] = list(self.values)
        seeds: Dict[str, Any] = {}
        if self.pins.descent or self.pins.regions:
            seeds["descent"] = {"values": list(self.pins.descent), "groups": {"region": list(self.pins.regions)}}
        if self.pins.gender:
            seeds["gender"] = {"values": list(self.pins.gender)}
        if self.pins.age or self.pins.years:
            seeds["age"] = {"values": list(self.pins.age), **({"years": list(self.pins.years)} if self.pins.years else {})}
        if seeds:
            out["seeds"] = seeds
        return out or None


def matches(seeds: Dict[str, Any], pins: Pins) -> bool:
    """Whether a variant written with `seeds` is what the picked seeds ask for."""
    picked = pins.descents()
    if picked is not None and str(seeds.get("descent") or "") not in set(picked):
        return False
    if pins.gender and str(seeds.get("gender") or "") not in set(pins.gender):
        return False
    if pins.age or pins.years:
        age = seeds.get("age")
        if not (set(stages_of(age)) & set(pins.age) or (pins.years and age in year_ages(pins.years))):
            return False   # its recorded age is in none of the picked stages or years (or it has none)
    return True


@dataclass
class Pick:
    """One slot's draw: its text (None: left out) and where it came from."""
    text: Optional[str]
    source: str                         # variant, own, pinned, fixed, words, off
    seeds: Dict[str, Any] = field(default_factory=dict)

    @property
    def counted(self) -> bool:
        """A draw that counts toward the pool's use counts: anything that shipped from the pool or
        the user's own, held ones included (the judge holds the slots it doesn't reroll)."""
        return self.source in ("variant", "own", "pinned", "fixed") and self.text is not None


def _least(rng: random.Random, items: Sequence[Dict[str, Any]], uses: Dict[str, int]) -> Dict[str, Any]:
    low = min(uses.get(_norm(v["text"]), 0) for v in items)
    return rng.choice([v for v in items if uses.get(_norm(v["text"]), 0) == low])


def drawable(variants: Sequence[Dict[str, Any]], choice: Choice) -> List[Dict[str, Any]]:
    """What a slot draws from now: the pinned variants, else the pool's variants whose seeds match
    the picked seeds (with the user's own), else the pool and the user's own."""
    by = {_norm(v["text"]): v for v in variants}
    own = [{"text": t, "seeds": {}, "own": True} for t in choice.add if _norm(t) not in by]
    if choice.values:
        return [{**by[_norm(t)], "pinned": True} if _norm(t) in by else {"text": t, "seeds": {}, "pinned": True}
                for t in choice.values]
    if choice.pins:
        hit = [v for v in variants if matches(v.get("seeds") or {}, choice.pins)]
        return hit + own if hit else []
    return list(variants) + own


def pick(variants: Sequence[Dict[str, Any]], uses: Dict[str, int], choice: Choice, rng: random.Random, words: str,
         fixed: Optional[str] = None) -> Pick:
    """One slot's value for one image. Never raises and never comes back with nothing to draw:
    a slot whose pool is empty (not written yet, failed, or nothing matching the picked seeds)
    goes in as its own words, with a single picked descent before them."""
    if choice.off:
        return Pick(None, "off")
    if choice.as_written:
        return Pick(words, "words")
    if isinstance(fixed, str) and fixed.strip():
        return Pick(fixed, "fixed")
    items = drawable(variants, choice)
    if not items:
        picked = choice.pins.descents() if not choice.values else None
        if picked and len(picked) == 1 and not choice.pins.regions:
            return Pick(f"{picked[0]} {words}", "words", {"descent": picked[0]})
        return Pick(words, "words")
    v = _least(rng, items, uses)
    source = "pinned" if v.get("pinned") else "own" if v.get("own") else "variant"
    return Pick(v["text"], source, dict(v.get("seeds") or {}))


def due(variants: Sequence[Dict[str, Any]], uses: Dict[str, int], choice: Choice) -> bool:
    """Whether a slot's pool wants a top-up: TOPUP_AT of what it draws from has been drawn this
    round (more than the least-drawn has), or the picked seeds match nothing yet. Pinned variants
    never ask for more."""
    if choice.off or choice.as_written or choice.values or len(variants) >= MAX_POOL:
        return False
    items = drawable(variants, choice)
    if choice.pins and len(items) < MIN_MATCH:
        return True   # a narrow pick (Korean, trans woman) would repeat its few matches
    if not items:
        return False
    counts = [uses.get(_norm(v["text"]), 0) for v in items]
    low = min(counts)
    return sum(1 for c in counts if c > low) / len(counts) >= TOPUP_AT


def in_pool(variants: Sequence[Dict[str, Any]], seed: str) -> Dict[str, int]:
    """How many of a pool's variants carry each value of one seed (descent, gender); for age, by
    life stage (a 35-year-old counts for young adult and middle-aged)."""
    out: Dict[str, int] = {}
    for v in variants:
        s = (v.get("seeds") or {}).get(seed)
        if isinstance(s, str) and s:
            for k in (stages_of(s) if seed == "age" else (s,)):
                out[k] = out.get(k, 0) + 1
    return out


def in_pool_years(variants: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    """How many of a pool's variants carry each recorded age, by year ("24": 3; JSON keys are text)."""
    out: Dict[str, int] = {}
    for v in variants:
        s = (v.get("seeds") or {}).get("age")
        if isinstance(s, str) and stages_of(s):
            k = str(age_years(s))
            out[k] = out.get(k, 0) + 1
    return out


def person_pickers(variants: Sequence[Dict[str, Any]], choice: Choice, *, fits: Optional[Sequence[str]] = None,
                   gender_fits: Optional[Sequence[str]] = None,
                   ages: Optional[Dict[str, List[str]]] = None, gender_list: Optional[str] = GENDER,
                   descent: bool = True, age: bool = True) -> Dict[str, Any]:
    """A person slot's descent, gender and age pickers for /pools (VARIANTS_IMPL.md section 4):
    descent browsed by its list's browse facet (Region > heritage), what the words allow of it
    (`fits`), what is picked and how many variants carry each value; the same for gender, a short
    list shown whole (`gender_fits`: what the words allow of it); age by life stage, only the
    stages the person may be (`ages`: variants.age_stages, their narrowed ages and the minors
    rules; None: every adult stage), each with the span of years it holds for them. Several people
    seed differently (seeding.plan): a couple's gender row is who they are (`gender_list`, the
    couple list), a family or group has none (None), a group or a figure with no real heritage no
    descent row, and a family or group no age row."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    out: Dict[str, Any] = {}
    d = vocab.get(DESCENT)
    if d is not None and descent:
        facet = d.browse
        parts: Dict[str, List[str]] = {p: [] for p in d.local_facets.get(facet, ())} if facet else {}
        for v in d.values:
            for p in (v.tags.get(facet) or ()) if facet else ():
                parts.setdefault(str(p), []).append(v.text)
        out["descent"] = {"list": d.id, "label": d.label, "browse": facet,
                          "parts": [{"id": p, "values": vs} for p, vs in parts.items() if vs],
                          "fits": list(fits) if fits else [v.text for v in d.values],
                          "picked": {"values": list(choice.pins.descent), "groups": {facet or "region": list(choice.pins.regions)}},
                          "in_pool": in_pool(variants, "descent")}
    g = vocab.get(gender_list) if gender_list else None
    if g is not None:
        out["gender"] = {"list": g.id, "label": g.label, "options": [v.text for v in g.values],
                         "fits": list(gender_fits) if gender_fits else [v.text for v in g.values],
                         "picked": {"values": list(choice.pins.gender)}, "in_pool": in_pool(variants, "gender")}
    a = vocab.get(AGE) if age else None
    if a is not None:
        stages = ages if ages is not None else age_stages()
        out["age"] = {"list": a.id, "label": a.label, "browse": STAGE, "options": list(stages),
                      "stages": [{"id": st, "label": st[:1].upper() + st[1:],
                                  "span": [min(age_years(t) for t in ts), max(age_years(t) for t in ts)],
                                  "years": [age_years(t) for t in ts]}
                                 for st, ts in stages.items()],
                      "fits": list(stages), "picked": {"values": list(choice.pins.age), "years": list(choice.pins.years)},
                      "in_pool": in_pool(variants, "age"), "in_pool_years": in_pool_years(variants)}
    return out


# --------------------------------------------------------------------------- the cap on streams in flight

class CallGate:
    """At most `limit` holders at once, granted in priority order (lowest first; ties in arrival
    order). Requests arriving within `settle` seconds of each other are weighed together. An
    urgent one (a pick, More like these) may run `extra` beyond the limit. The profile's cap on
    writer streams, and (limit 1) a pool's one turn at a time."""

    def __init__(self, limit: int = STREAMS, extra: int = URGENT_STREAMS, settle: float = GATE_SETTLE):
        self.limit, self.extra, self.settle = limit, extra, settle
        self._pending: Optional[asyncio.TimerHandle] = None
        self.running = 0
        self._waiting: List[Tuple[Tuple[int, ...], int, bool, "asyncio.Future[None]"]] = []
        self._seq = itertools.count()

    @property
    def idle(self) -> bool:
        return self.running == 0 and not any(not f.done() for *_, f in self._waiting)

    @contextlib.asynccontextmanager
    async def slot(self, priority: Tuple[int, ...], urgent: bool = False):
        fut: "asyncio.Future[None]" = asyncio.get_running_loop().create_future()
        heapq.heappush(self._waiting, (priority, next(self._seq), urgent, fut))
        if self._pending is None:
            self._pending = asyncio.get_running_loop().call_later(self.settle, self._settled)
        try:
            await fut
        except asyncio.CancelledError:
            if fut.done() and not fut.cancelled():
                self._release()   # granted as it was cancelled
            raise
        try:
            yield
        finally:
            self._release()

    def _settled(self) -> None:
        self._pending = None
        self._pump()

    def _release(self) -> None:
        """A holder is done: the next grant waits `settle`, so the holder's own next request (a
        write's next turn) is weighed with the ones already waiting."""
        self.running -= 1
        if self.settle <= 0:
            self._pump()
        elif self._pending is None:
            self._pending = asyncio.get_running_loop().call_later(self.settle, self._settled)

    def _pump(self) -> None:
        while self._waiting:
            _, _, urgent, fut = self._waiting[0]
            if fut.done():   # cancelled while waiting
                heapq.heappop(self._waiting)
                continue
            if self.running >= self.limit + (self.extra if urgent else 0):
                return
            heapq.heappop(self._waiting)
            self.running += 1
            fut.set_result(None)


# --------------------------------------------------------------------------- writing in the background

@dataclass
class Job:
    """One write for one pool: one or more turns of its session."""
    key: str
    slot: Slot
    seeds: Seeds
    role: str = "first"                # early (an unseeded opening turn while its seeds are narrowed), first, top_up, more
    pins: Pins = field(default_factory=Pins)
    project_id: Optional[int] = None
    model: str = ""

    @property
    def high(self) -> bool:
        """Written ahead of a prepare that's reading: a first pool, More like these, or a top-up
        for seeds the user just picked."""
        return self.role != "top_up" or bool(self.pins)

    @property
    def urgent(self) -> bool:
        """Someone is waiting to see it: More like these, or a batch for seeds the user picked. Its
        turns go next in the pool's session, ahead of any background turn, and may run beyond the
        profile's cap on streams."""
        return self.role == "more" or (self.role == "top_up" and bool(self.pins))

    @property
    def rank(self) -> int:
        """Priority: what someone waits for, then first writes (every slot's first turn before
        any slot's later ones), then background top-ups."""
        return 0 if self.urgent else 1 if self.role in ("first", "early") else 2

    @property
    def lane(self) -> str:
        """What one write at a time is held to: the pool, or for an early turn, a pick or More like
        these a lane of their own, so they never wait for (or are refused by) a background write of
        the same pool. Their turns still go one at a time in the pool's one session."""
        if self.role == "early":
            return f"{self.key}|early"
        if self.role == "more":
            return f"{self.key}|more"
        return f"{self.key}|pick" if self.role == "top_up" and self.pins else self.key


LANES = ("", "|pick", "|early", "|more")


class PoolWriter:
    """A profile's pool writes, run on the event loop. Each pool has one session (its chat log,
    stored with it); a write is one or more turns of it, one turn at a time per pool, the most
    urgent waiting turn next. At most STREAMS turns stream at once per profile. `submit()` is safe
    from any thread (a draw may run in a worker thread). A background top-up gives way while
    `paused()` (a prepare is reading on the same chat model). A write that keeps nothing is never
    stored: `failed(key)` says why until the next first write is asked."""

    def __init__(self, store: VariantStore, ask: Ask = ask_writer, paused: Optional[Callable[[], bool]] = None,
                 streams: int = STREAMS):
        self.store, self.ask = store, ask
        self.paused = paused or (lambda: False)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._inflight: Dict[str, "asyncio.Future[List[str]]"] = {}
        self._queued: List[Job] = []
        self._failed: Dict[str, Tuple[str, float]] = {}   # key -> (why, when)
        self._early: set = set()   # pools an unseeded opening turn was asked for (once each)
        self._thin: set = set()    # pools whose short first write was asked again (once each)
        self._gate: Optional[CallGate] = None
        self._turns: Dict[str, CallGate] = {}   # per pool: one turn at a time, by priority
        self._streams = streams
        self.calls = 0   # turns asked

    # -- state
    def busy(self, key: str) -> bool:
        with self._lock:
            return any(f"{key}{x}" in self._inflight for x in LANES) or any(j.key == key for j in self._queued)

    def first_written(self, key: str) -> bool:
        """Whether a pool's first write is stored: an unseeded opening turn alone isn't it, and nor
        is one that kept fewer than MIN_POOL (most of its turns failed or were unreadable) until it
        has been asked again once; a top-up or More like these stored means it was."""
        batches = [b for b in self.store.batches(key) if b.get("role") != "early" and b.get("variants")]
        if not batches:
            return False
        return key in self._thin or any(b.get("role") != "first" for b in batches) or \
            sum(len(b["variants"]) for b in batches) >= MIN_POOL

    def failed(self, key: str) -> Optional[str]:
        got = self._failed.get(key)
        return got[0] if got else None

    def state(self, key: str, stand_in: Optional[str] = None) -> str:
        """ready (a pool, or a stand-in, to draw from), writing, or as_written (the writer gave
        nothing; it stands as its words until asked again)."""
        if self.store.has(key) or (stand_in and self.store.has(stand_in)):
            return "ready"
        if self.busy(key):
            return "writing"
        return "as_written" if key in self._failed else "writing"

    # -- queueing
    def attach(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start writing on `loop` (the running one by default); jobs queued before start then."""
        loop = loop or asyncio.get_running_loop()
        if self.loop is not loop:
            self.loop = loop
            self._gate = None
            self._turns = {}
        with self._lock:
            queued, self._queued = self._queued, []
        for job in queued:
            with self._lock:
                self._inflight[job.lane] = None
            loop.call_soon_threadsafe(self._start, job)

    def submit(self, job: Job, retry: bool = False) -> bool:
        """Queue a write unless one for its lane is queued or running (a first write for a pool
        that has variants is skipped, and so is one that failed less than RETRY_AFTER ago unless
        `retry`: a picker polling /pools never asks a failing model again and again). Returns
        whether it was queued."""
        if job.role == "first" and self.first_written(job.key):
            return False
        if job.role == "early" and (self.store.has(job.key) or job.key in self._early):
            return False   # asked once: a failed one leaves the first write to come as it was
        with self._lock:
            if job.lane in self._inflight or any(j.lane == job.lane for j in self._queued):
                return False
            if job.role == "early":
                self._early.add(job.key)
            if job.role == "first":
                failed = self._failed.get(job.key)
                if failed is not None and not retry and time.time() - failed[1] < RETRY_AFTER:
                    return False
                self._failed.pop(job.key, None)
            loop = self.loop
            if loop is None or loop.is_closed():
                self._queued.append(job)
                return True
            self._inflight[job.lane] = None   # held until it starts on the loop
        loop.call_soon_threadsafe(self._start, job)
        return True

    def _start(self, job: Job) -> None:
        fut = asyncio.ensure_future(self._guarded(job))
        with self._lock:
            self._inflight[job.lane] = fut
        fut.add_done_callback(lambda f, k=job.lane: self._done(k, f))

    def _done(self, key: str, fut: Any) -> None:
        with self._lock:
            if self._inflight.get(key) is fut:
                del self._inflight[key]
        from prompt_programs.events import pool_changed
        pool_changed(key.split("|")[0])

    async def _guarded(self, job: Job) -> List[str]:
        while not job.high and self._paused():
            await asyncio.sleep(YIELD_POLL)
        try:
            return await self.run(job)
        except Exception as e:   # one pool failing never stops the others
            log.warning(f"[variants] writing {job.slot.words!r} failed: {e}")
            if job.role == "first":
                self._failed[job.key] = (str(e)[:200] or type(e).__name__, time.time())
            return []

    def _paused(self) -> bool:
        try:
            return bool(self.paused())
        except Exception:
            return False

    # -- the writes
    def gate(self, job: Job) -> Callable[[int], Any]:
        """The cap on streams a job's turns run in, by priority (Job.rank, then the turn's index
        in its write, so four new slots each stream their first turn in the first wave)."""
        if self._gate is None:
            self._gate = CallGate(limit=self._streams)
        g = self._gate
        return lambda i: g.slot((job.rank, i), urgent=job.urgent)

    @contextlib.asynccontextmanager
    async def _turn(self, job: Job, i: int):
        """A pool's one turn at a time: the most urgent waiting turn of its session goes next,
        then the turn takes its place under the profile's cap on streams."""
        g = self._turns.get(job.key)
        if g is None:
            g = self._turns[job.key] = CallGate(limit=1, extra=0)
        try:
            async with g.slot((job.rank, i)):
                async with self.gate(job)(i):
                    yield
        finally:
            if g.idle and self._turns.get(job.key) is g:
                del self._turns[job.key]

    def _room(self, job: Job, out: Sequence[str], n: int) -> bool:
        """Room for one more variant as it lands: under MAX_POOL (another lane may have filled it
        meanwhile) and within what this write asked for. More like these, which the user asked
        for, may pass the cap by its own batch."""
        if len(out) >= n:
            return False
        return job.role == "more" or len(self.store.variants(job.key)) < MAX_POOL

    def _record(self, job: Job, batch: int, **kw: Any) -> Dict[str, Any]:
        return {"batch": batch, "role": job.role, "version": VARIANTS_VERSION, "at": time.time(), "model": job.model,
                **kw}

    def _tally(self, job: Job, batch: int, turn: Turn, *, logged: bool, restarted: bool) -> Dict[str, Any]:
        return self._record(job, batch, words=job.slot.words, category=job.slot.category, keep=job.slot.keep(),
                            pinned=job.pins.to_dict(), variants=[], asked=turn.asked, kept=len(turn.variants),
                            dropped=dict(turn.dropped), repairs=turn.repairs, ideas=turn.ideas,
                            seconds=turn.seconds, first=turn.first, streamed=turn.streamed, logged=logged,
                            restarted=restarted, **({"error": turn.error} if turn.error else {}),
                            **({"descents": dict(turn.descents)} if turn.descents else {}))

    def _quota(self, job: Job, have: Sequence[Dict[str, Any]]) -> int:
        """How many variants a write asks for."""
        if job.role == "early":
            return TURN
        if job.role == "first":
            return max(TURN, job.slot.n - len(have))
        if job.role == "more":
            return TOPUP
        return min(TOPUP, MAX_POOL - len(have))

    async def _wait_early(self, job: Job) -> None:
        """An unseeded opening turn in flight lands first, so the first write continues its session."""
        while True:
            with self._lock:
                held = f"{job.key}|early" in self._inflight
                early = self._inflight.get(f"{job.key}|early")
            if not held:
                return
            if early is None:   # queued, not started yet
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(Exception):
                await asyncio.shield(early)
            return

    async def run(self, job: Job) -> List[str]:
        """One write for one pool: turns of TURN in the pool's session, each variant stored the
        moment it is checked. A turn that keeps under half of what it asked for never joins the
        log; the session is asked again once from a fresh first turn with fresh seeds, and a
        second such turn ends the write (the slot stands as it is, asked again later). A first
        write still under MIN_POOL after its planned turns asks up to MORE_TURNS more; one left
        short draws what it has and is asked again once after RETRY_AFTER. Returns the new
        variants' texts."""
        if job.role == "early" and self.store.has(job.key):
            return []
        if job.role == "first":
            await self._wait_early(job)
            if self.first_written(job.key):
                return []
            if any(b.get("role") == "first" and b.get("variants") for b in self.store.batches(job.key)):
                self._thin.add(job.key)   # a short first write, asked again once: its session goes on
        seeds = Seeds() if job.role == "early" else job.seeds.pinned(job.pins)
        have = self.store.variants(job.key)
        n = self._quota(job, have)
        if n <= 0:
            return []
        cores = [str(v["seeds"]["core"]) for v in have if (v.get("seeds") or {}).get("core")]
        base = len(self.store.batches(job.key))
        parts = split(draw_seeds(random.Random(f"{job.key}|{base}"), seeds, n, job.slot.words, cores), TURN)
        out: List[str] = []
        restarted = False
        fresh = False
        more = 0
        asked = 0
        i = 0
        while i < len(parts) or (job.role == "first" and more < MORE_TURNS
                                 and len(self.store.variants(job.key)) < MIN_POOL):
            if i == len(parts):
                # Short of MIN_POOL after its planned turns (repeats, drops): one more turn, a few times.
                more += 1
                n = max(n, len(out) + TURN)
                extra = draw_seeds(random.Random(f"{job.key}|{base}|more{more}"), seeds, TURN, job.slot.words, cores)
                parts = parts + [extra]
            part = parts[i]
            async with self._turn(job, i):
                if not self._room(job, out, n):
                    break
                if job.role == "top_up" and not job.pins and i > 0 and \
                        len(self.store.variants(job.key)) - len(have) - len(out) >= n - len(out):
                    break   # More like these went ahead and wrote at least what this top-up had left
                session = Session() if fresh else Session.of(self.store.session(job.key))
                removed = self.store.removed(job.key)
                pool = self.store.variants(job.key)
                seen = {_norm(v["text"]) for v in pool} | set(removed)
                a = len(session.texts) + 1
                if session.open:
                    user = {"role": "user", "content": more_turn(part, a, seeds, unseeded_start=not session.seeded)}
                    sent = session.sent(user["content"], removed)
                else:   # a session's opening, or a fresh one over a pool that has variants already
                    a = 1
                    sent = first_turn(job.slot, part, seeds, have=[v["text"] for v in pool][-HAVE_SHOWN:])
                    user = sent[1]
                batch = base + asked   # one label per turn asked, restarts and extra turns too
                asked += 1

                def landed(v: Dict[str, Any], batch: int = batch) -> bool:
                    if not self._room(job, out, n):
                        return False
                    self.store.append(job.key, self._record(job, batch, turn=i, variants=[v]))
                    out.append(v["text"])
                    return True
                turn = await write_turn(job.slot, part, sent, ask=self.ask, a=a, project_id=job.project_id,
                                        seen=seen, landed=landed)
                self.calls += 1
                logged = turn.passed
                if logged:
                    if not session.open:
                        session = Session(messages=[dict(sent[0])], seeded=job.role != "early",
                                          restarts=session.restarts + int(restarted))
                    session.log(dict(user), reply_text(turn.variants, a, turn.rejected), turn.texts())
                    if job.role != "early":
                        session.seeded = True   # what an unseeded opening lacked has been shown now
                    self.store.save_session(job.key, session.to_dict())
                    fresh = False
                self.store.append(job.key, self._tally(job, batch, turn, logged=logged, restarted=restarted))
            if not logged:
                if restarted or job.role == "early":   # an unseeded opening is asked once; the first write follows
                    if job.role == "early":
                        log.info(f"[variants] an early turn for {job.slot.words!r} kept {len(turn.variants)}")
                        break
                    log.info(f"[variants] {job.slot.words!r}: a second turn kept under half; it stands as it is")
                    break
                # Not appended. Once more from a fresh first turn with fresh seeds for what is left.
                restarted, fresh = True, True
                left = sum(len(p.specs) for p in parts[i:])
                again = draw_seeds(random.Random(f"{job.key}|{base}|again"), seeds, left, job.slot.words, cores)
                parts = parts[:i] + split(again, TURN)
                log.info(f"[variants] {job.slot.words!r}: a turn kept {len(turn.variants)} of {turn.asked} "
                         f"({turn.error or dict(turn.dropped)}); starting its session again")
                continue
            i += 1
        if job.role == "first" and not self.first_written(job.key):
            why = "nothing usable"
            last = [b for b in self.store.batches(job.key) if "asked" in b][-2:]
            if last:
                why = "; ".join(dict.fromkeys(str(b.get("error") or ", ".join(b.get("dropped") or {}) or "nothing usable")
                                              for b in last))
            if not self.store.variants(job.key):
                self._failed[job.key] = (why[:200], time.time())
                log.info(f"[variants] {job.slot.words!r} stands as written: {why[:200]}")
            else:   # short: it draws from what it has and is asked again after RETRY_AFTER (submit)
                self._failed[job.key] = (f"thin: {why}"[:200], time.time())
                log.info(f"[variants] {job.slot.words!r} kept only {len(self.store.variants(job.key))}; "
                         f"asked again later: {why[:200]}")
        return out

    async def more(self, job: Job) -> List[str]:
        """More like these: TOPUP more, awaited. Its turns go next in the pool's session, ahead of
        any background turn, so it is told everything the session wrote."""
        job.role = "more"
        while True:
            with self._lock:
                held = job.lane in self._inflight
                running = self._inflight.get(job.lane)
            if not held:
                break
            if running is None:   # queued, not started yet
                await asyncio.sleep(0)
                continue
            with contextlib.suppress(Exception):
                return await asyncio.shield(running)   # the same More, asked twice: one batch
        fut = asyncio.ensure_future(self.run(job))
        with self._lock:
            self._inflight[job.lane] = fut
        fut.add_done_callback(lambda f, k=job.lane: self._done(k, f))
        return await fut

    def picked(self, job: Job, choice: Choice) -> bool:
        """Seeds the user just picked that fewer than MIN_MATCH variants match: write a batch with
        them now, at high priority (meanwhile the draws take the few matches, or stand as the words
        with a single picked descent). Call it when a choice arrives (/pools, a generation).
        Returns whether a batch was queued."""
        if not choice.pins or choice.values or choice.off or choice.as_written:
            return False
        pool = self.store.variants(job.key)
        if not pool or len(drawable(pool, choice)) >= MIN_MATCH or len(pool) >= MAX_POOL:
            return False   # no pool yet (its first write is coming), enough match already, or full
        job.role, job.pins = "top_up", choice.pins
        return self.submit(job)

    def drew(self, job: Job, pick: Pick, variants: Optional[Sequence[Dict[str, Any]]] = None,
             choice: Optional[Choice] = None) -> bool:
        """Count a shipped draw and start a top-up when one is due (`job` says how to write it).
        Returns whether a top-up was queued. Never raises."""
        try:
            choice = choice or Choice()
            uses = self.store.mark_used(job.key, [pick.text]) if pick.counted and pick.text else self.store.uses(job.key)
            pool = list(variants) if variants is not None else self.store.variants(job.key)
            if not pool or not due(pool, uses, choice):
                return False
            job.role, job.pins = "top_up", choice.pins
            return self.submit(job)
        except Exception as e:
            log.warning(f"[variants] counting a draw of {job.key} failed: {e}")
            return False

    async def drain(self) -> None:
        """Wait for every queued and running write (tests, scripts)."""
        if self.loop is None:
            self.attach()
        while True:
            with self._lock:
                held = list(self._inflight.values())
            if not held:
                return
            running = [f for f in held if f is not None]
            if running:
                await asyncio.gather(*running, return_exceptions=True)
            await asyncio.sleep(0)


# --------------------------------------------------------------------------- per profile

_stores: Dict[str, VariantStore] = {}
_writers: Dict[str, PoolWriter] = {}
# What a profile's writer asks: the app's chat model (tests replace it, so no write reaches a model).
ASK: Ask = ask_writer


class _Ask:
    """The profile writers' `ask`: whatever ASK is now, streamed where it can stream."""

    async def __call__(self, *args: Any, **kwargs: Any) -> str:
        return await ASK(*args, **kwargs)

    def stream(self, *args: Any, **kwargs: Any) -> Any:
        stream = getattr(ASK, "stream", None)
        if stream is None:
            from llm_http import StreamUnsupported
            raise StreamUnsupported("whole replies only")
        return stream(*args, **kwargs)


_ask = _Ask()


def store_for(profile_id: Optional[str]) -> VariantStore:
    import app_dirs
    from core.profile_context import get_current_profile
    root = app_dirs.get_profile_dir(profile_id or get_current_profile()) / "prompt_programs" / "variants"
    s = _stores.get(str(root))
    if s is None:
        s = _stores[str(root)] = VariantStore(root)
    return s


def writer_for(profile_id: Optional[str]) -> PoolWriter:
    store = store_for(profile_id)
    w = _writers.get(str(store.root))
    if w is None:
        from prompt_programs.slots import preparing
        w = _writers[str(store.root)] = PoolWriter(store, ask=_ask, paused=preparing)
    try:
        w.attach()
    except RuntimeError:
        pass   # no running loop here: writes wait until an async caller attaches one
    return w


__all__ = ["STREAMS", "CallGate", "Choice", "Job", "MAX_POOL", "MIN_MATCH", "RETRY_AFTER", "POOL_VERSION", "Pick", "PoolWriter", "TOPUP_AT", "VariantStore", "drawable",
           "due", "in_pool", "in_pool_years", "matches", "person_pickers", "pick", "pool_key", "store_for", "writer_for"]
