"""A slot's pool of variants: stored per profile, drawn least-used first, topped up in the background.

The writer (variants.py) writes a slot's variants; this module keeps them and draws from them
with no model call:

- The store. One append-only JSONL file per pool, one line per writer call that kept anything
  (`{"batch", "role", "variants": [{"text", "seeds"}], ...}`), and the pool's use counts beside
  it. A pool is keyed by the model, the slot's words, the line its reading was made in and the
  prompt's notes (pool_key): the context the quiet re-read uses, never the whole prompt.
- Drawing. Per image, per slot: left out, as written, a fixed (replayed) text, the variants the
  user pinned, the variants whose seeds match the seeds the user picked, else any variant; each
  time the least-used one, ties broken by the draw's seeded RNG. A slot with no pool yet goes in
  as its own words. Never an error and never nothing to draw.
- Writing. The first pool and every top-up run in the background (PoolWriter), never on a draw's
  path. After a counted draw, when 80% of what the slot draws from has been drawn this round, a
  top-up of 20 starts. "More like these" is the same call, awaited. A batch someone waits for (More
  like these, seeds the user picked) is written as chunks of PICK_CHUNK side by side, each stored
  as it lands, in a lane of its own: the picker sees matches in about 4 s, not 11-14 s. A first
  write is chunked the same way, under a cap of CALLS calls in flight per profile (CallGate), so a
  new slot shows variants in about 4-6 s rather than 15-40 s.

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
    AGE, DESCENT, GENDER, STAGE, TOPUP, VARIANTS_VERSION, Ask, Batch, Pins, Seeds, Slot, age_stages, age_years,
    N_OTHER, N_PERSON, PICK_CHUNK, ask_writer, stages_of, top_up, write_chunks, write_first, year_ages,
)

log = get_logger(__name__)

POOL_VERSION = "pool-1"
TOPUP_AT = 0.8      # share of what a slot draws from drawn this round that starts a top-up
MAX_POOL = 300      # a pool this big stops topping up and cycles least-used
RETRY_AFTER = 120.0 # seconds a failed first write stands as written before a prepare or poll asks again
MIN_MATCH = 8       # picked seeds that match fewer variants than this write more that match, at once
WORKERS = 4         # writes in flight per profile (each may be several calls; CALLS caps those)
CALLS = 6           # writer calls in flight per profile. Measured on a local ~70 tok/s model, a prompt
                    # of four new slots (28 chunks of 5): a cap of 4 shows every slot's first variants
                    # in 3-5 s but takes 30 s for all; 6, 4-6 s and 24 s; 8, 4.5-7 s and 21 s (each
                    # stream slows to ~35 tok/s at 8). Every slot's first chunks go first.
URGENT_CALLS = 4    # calls a pick or More like these may run beyond CALLS, so it never queues behind first writes
GATE_SETTLE = 0.01  # seconds calls arriving together are gathered before any is granted, so the first
                    # chunks of every slot a prepare starts go ahead of any one slot's later chunks
YIELD_POLL = 0.25   # seconds between looks while a background top-up gives way to a prepare
SEEDS_KEPT = 500    # draws with an explicit draw seed remembered per prompt


def pool_key(model: Optional[str], words: str, marked: str, notes: Sequence[str], minor: Sequence[str] = ()) -> str:
    """A pool's key: the model, the slot's words, the line its reading was made in (marked) and
    the prompt's notes; a person who may be under 18 has a pool of their own."""
    parts: Dict[str, Any] = {"v": POOL_VERSION, "writer": VARIANTS_VERSION, "model": model, "words": words,
                             "marked": marked, "notes": list(notes)}
    if minor:
        parts["minor"] = sorted(minor)
    blob = json.dumps(parts, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


def _norm(text: str) -> str:
    return " ".join(str(text).split()).lower()


# --------------------------------------------------------------------------- the store

class VariantStore:
    """Pools on disk: `<key[:2]>/<key>.jsonl`, one line per batch, and `<key>.uses.json`."""

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
        case and spacing wins."""
        seen: set = set()
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
                   ages: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """A person slot's descent, gender and age pickers for /pools (VARIANTS_IMPL.md section 4):
    descent browsed by its list's browse facet (Region > heritage), what the words allow of it
    (`fits`), what is picked and how many variants carry each value; the same for gender, a short
    list shown whole (`gender_fits`: what the words allow of it); age by life stage, only the
    stages the person may be (`ages`: variants.age_stages, their narrowed ages and the minors
    rules; None: every adult stage), each with the span of years it holds for them."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    out: Dict[str, Any] = {}
    d = vocab.get(DESCENT)
    if d is not None:
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
    g = vocab.get(GENDER)
    if g is not None:
        out["gender"] = {"list": g.id, "label": g.label, "options": [v.text for v in g.values],
                         "fits": list(gender_fits) if gender_fits else [v.text for v in g.values],
                         "picked": {"values": list(choice.pins.gender)}, "in_pool": in_pool(variants, "gender")}
    a = vocab.get(AGE)
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


# --------------------------------------------------------------------------- the cap on calls in flight

class CallGate:
    """At most `limit` writer calls in flight, granted in priority order (lowest first; ties in
    arrival order). Calls arriving within `settle` seconds of each other are weighed together. An
    urgent call (a pick, More like these) may run `extra` beyond the limit."""

    def __init__(self, limit: int = CALLS, extra: int = URGENT_CALLS, settle: float = GATE_SETTLE):
        self.limit, self.extra, self.settle = limit, extra, settle
        self._pending: Optional[asyncio.TimerHandle] = None
        self.running = 0
        self._waiting: List[Tuple[Tuple[int, ...], int, bool, "asyncio.Future[None]"]] = []
        self._seq = itertools.count()

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
        self.running -= 1
        self._pump()

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
    """One write for one pool."""
    key: str
    slot: Slot
    seeds: Seeds
    role: str = "first"                # first, top_up, more
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
        """Someone is waiting to see it: More like these, or a batch for seeds the user picked.
        Written in chunks side by side, each stored as it lands, in a lane of its own so it never
        queues behind a background write."""
        return self.role == "more" or (self.role == "top_up" and bool(self.pins))

    @property
    def lane(self) -> str:
        """What one write at a time is held to: the pool, or for a pick the pool's pick lane, so a
        pick never waits for (or is refused by) a background write of the same pool."""
        return f"{self.key}|pick" if self.role == "top_up" and self.pins else self.key


class PoolWriter:
    """A profile's pool writes, run on the event loop, at most one per pool at a time and WORKERS
    at once. `submit()` is safe from any thread (a draw may run in a worker thread). A background
    top-up gives way while `paused()` (a prepare is reading on the same chat model). A write that
    keeps nothing is never stored: `failed(key)` says why until the next first write is asked."""

    def __init__(self, store: VariantStore, ask: Ask = ask_writer, workers: int = WORKERS,
                 paused: Optional[Callable[[], bool]] = None):
        self.store, self.ask = store, ask
        self.paused = paused or (lambda: False)
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._inflight: Dict[str, "asyncio.Future[List[str]]"] = {}
        self._queued: List[Job] = []
        self._failed: Dict[str, Tuple[str, float]] = {}   # key -> (why, when)
        self._sem: Optional[asyncio.Semaphore] = None
        self._urgent_sem: Optional[asyncio.Semaphore] = None
        self._gate: Optional[CallGate] = None
        self._workers = workers
        self.calls = 0

    # -- state
    def busy(self, key: str) -> bool:
        with self._lock:
            return any(k in self._inflight for k in (key, f"{key}|pick")) or any(j.key == key for j in self._queued)

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
            self._sem = self._urgent_sem = self._gate = None
        with self._lock:
            queued, self._queued = self._queued, []
        for job in queued:
            with self._lock:
                self._inflight[job.lane] = None
            loop.call_soon_threadsafe(self._start, job)

    def submit(self, job: Job, retry: bool = False) -> bool:
        """Queue a write unless one for its pool is queued or running (a first write for a pool
        that has variants is skipped, and so is one that failed less than RETRY_AFTER ago unless
        `retry`: a picker polling /pools never asks a failing model again and again). Returns
        whether it was queued."""
        if job.role == "first" and self.store.has(job.key):
            return False
        with self._lock:
            if job.lane in self._inflight or any(j.lane == job.lane for j in self._queued):
                return False
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

    async def _guarded(self, job: Job) -> List[str]:
        if self._sem is None:
            self._sem = asyncio.Semaphore(self._workers)
        if self._urgent_sem is None:
            self._urgent_sem = asyncio.Semaphore(self._workers)
        while not job.high and self._paused():
            await asyncio.sleep(YIELD_POLL)
        async with (self._urgent_sem if job.urgent else self._sem):
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
    def _record(self, job: Job, batch: Batch, n: int, kept: List[Dict[str, Any]]) -> Dict[str, Any]:
        return {"batch": n, "role": job.role, "version": VARIANTS_VERSION, "at": time.time(), "model": job.model,
                "seconds": batch.seconds, "words": job.slot.words, "category": job.slot.category,
                "keep": job.slot.keep(), "pinned": job.pins.to_dict(), "variants": kept,
                "dropped": dict(batch.dropped), "repairs": batch.repairs, "ideas": batch.ideas}

    def gate(self, job: Job) -> Callable[[int], Any]:
        """The call cap a job's chunks run in: urgent ones first, then every pool's first chunks
        ahead of their later ones (so four new slots each show variants in the first wave),
        then background top-ups."""
        if self._gate is None:
            self._gate = CallGate()
        g = self._gate
        rank = 0 if job.urgent else 1 if job.role == "first" else 2
        return lambda i: g.slot((rank, i), urgent=job.urgent)

    async def run(self, job: Job) -> List[str]:
        """One write for one pool, stored as it lands. Returns the new variants' texts."""
        seeds = job.seeds.pinned(job.pins)
        have = self.store.variants(job.key)
        done = len(self.store.batches(job.key))
        if job.role == "first":
            if have:
                return []
            out: List[str] = []
            seen: set = set()

            def landed_first(b: Batch) -> None:
                kept = [v for v in b.variants if _norm(v["text"]) not in seen]
                seen.update(_norm(v["text"]) for v in kept)
                if kept:
                    self.store.append(job.key, self._record(job, b, len(self.store.batches(job.key)), kept))
                    out.extend(v["text"] for v in kept)
            batches = await write_first(job.slot, seeds, ask=self.ask, project_id=job.project_id, key=job.key,
                                        landed=landed_first, gate=self.gate(job))
            self.calls += len(batches)
            if not out:
                why = "; ".join(dict.fromkeys(b.error or ", ".join(b.dropped) or "nothing usable" for b in batches))
                self._failed[job.key] = (why[:200], time.time())
                log.info(f"[variants] {job.slot.words!r} stands as written: {why[:200]}")
            return out
        # A background top-up fills only the room left under MAX_POOL. More like these, which the
        # user asked for, may pass the cap by its own one batch.
        n = TOPUP if job.role == "more" else min(TOPUP, MAX_POOL - len(have))
        if n <= 0:
            return []
        cores = [str(v["seeds"]["core"]) for v in have if (v.get("seeds") or {}).get("core")]
        rng = random.Random(f"{job.key}|{done}")
        seen = {_norm(v["text"]) for v in have}
        if job.urgent:
            # Picked seeds: the writer is told only what already matches them (the rest can't be
            # repeated: a variant carries its descent), so a pick's prompt stays short.
            shown = [v["text"] for v in have if matches(v.get("seeds") or {}, job.pins)] if job.pins \
                else [v["text"] for v in have]
            out: List[str] = []

            def landed(b: Batch) -> None:
                kept = [v for v in b.variants if _norm(v["text"]) not in seen][:n - len(out)]
                seen.update(_norm(v["text"]) for v in kept)
                if kept:
                    self.store.append(job.key, self._record(job, b, len(self.store.batches(job.key)), kept))
                    out.extend(v["text"] for v in kept)
            batches = await write_chunks(job.slot, seeds, n, ask=self.ask, project_id=job.project_id, have=shown,
                                         rng=rng, used_cores=cores, landed=landed, gate=self.gate(job))
            self.calls += len(batches)
            return out
        async with self.gate(job)(0):
            b = await top_up(job.slot, seeds, [v["text"] for v in have], ask=self.ask, project_id=job.project_id,
                             n=n, rng=rng, used_cores=cores)
        self.calls += 1
        kept = [v for v in b.variants if _norm(v["text"]) not in seen][:n]
        if kept:
            self.store.append(job.key, self._record(job, b, done, kept))
        return [v["text"] for v in kept]

    async def more(self, job: Job) -> List[str]:
        """More like these: one batch of TOPUP, awaited. A write already in flight for the pool
        is waited for first, so the new batch is told what it wrote."""
        job.role = "more"
        while True:
            with self._lock:
                held = job.key in self._inflight
                running = self._inflight.get(job.key)
            if not held:
                break
            if running is None:   # queued, not started yet
                await asyncio.sleep(0)
                continue
            try:
                await asyncio.shield(running)
            except Exception:
                pass
        fut = asyncio.ensure_future(self.run(job))
        with self._lock:
            self._inflight[job.key] = fut
        fut.add_done_callback(lambda f, k=job.key: self._done(k, f))
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


async def _ask(*args: Any, **kwargs: Any) -> str:
    return await ASK(*args, **kwargs)


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


__all__ = ["CALLS", "CallGate", "Choice", "Job", "MAX_POOL", "MIN_MATCH", "RETRY_AFTER", "POOL_VERSION", "Pick", "PoolWriter", "TOPUP_AT", "VariantStore", "drawable",
           "due", "in_pool", "in_pool_years", "matches", "person_pickers", "pick", "pool_key", "store_for", "writer_for"]
