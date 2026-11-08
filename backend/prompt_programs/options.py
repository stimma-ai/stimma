"""Options for picks with specs: user lists as written, writer seeds, generated options.

A pick with `about=` that isn't a user list draws from a pool that grows. The pool is
the writer's seeds (and any literal options on its branch), then options an LLM wrote
for the pick's spec in a short context ("hairstyles for a 1920s jazz club"). Those are
cached on disk in the profile, append-only and keyed by their inputs, so another prompt
with the same spec and context reuses them and no call is ever made twice.

    service = GeneratedOptions(store, program=ProgramContext.of(entry), filler=filler)
    pool = service.get(spec, {"era": "1920s"})      # seeds + whatever has been generated
    service.request_more(spec, {"era": "1920s"}, "high")

Generation never runs inside a draw. `get()` queues a low-priority fill for a pool that
has never been generated and a high-priority one for a pool that has run thin; the
filler works through the queue on the event loop, high priority first. A pool with a
fill queued or running says `more_coming`, so the UI can show it.

User lists (`source="list"`) and LoRA picks are never expanded: their options are the
user's, exactly, with uniform weights.
"""

from __future__ import annotations

import asyncio
import hashlib
import heapq
import itertools
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs.draws import LiteralOptions, PickSpec, Pool, pool_key
from prompt_programs.resolver import ClassResolver, NoVocabulary
from prompt_programs.runtime import RANK_DECAY

log = get_logger(__name__)

OPTIONS_VERSION = "opts-1"     # bump to invalidate every generated pool on purpose
BATCH_SIZE = 12                # options asked for per generation call
GEN_DECAY = 0.96               # rank decay across generated options (gentler than the writer's lists)
THIN = 6                       # a generated pool with fewer usable options asks for more, high priority
MAX_ROUNDS = 8                 # generation calls per pool, at most
PRIORITY = {"high": 0, "low": 1}


def generated_pick(spec: PickSpec) -> bool:
    """Whether a pick's pool grows: it has a spec and isn't the user's list or a LoRA."""
    return spec.kind == "pick" and spec.source != "list" and bool(spec.about.strip())


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", str(s).strip().lower())


# --------------------------------------------------------------------------- program context

@dataclass(frozen=True)
class ProgramContext:
    """What generation needs to know about the prompt a pick sits in.

    signature: the short context that keys the cross-prompt cache. The writer may give
      one (entry["context"], e.g. "a 1920s jazz club portrait"); without it, the prompt
      template is the signature, which only matches the same template.
    template: the prompt with every pick masked as [Label], shown to the generator.
    """
    key: str = ""
    signature: str = ""
    template: str = ""
    mode: str = "prose"
    elaborate: bool = True

    @classmethod
    def of(cls, entry: Dict[str, Any]) -> "ProgramContext":
        from prompt_programs.draws import fixed_text
        template = entry.get("template") or fixed_text(entry["program"])
        signature = str(entry.get("context") or "").strip() or template
        return cls(str(entry.get("key") or ""), signature, template, str(entry.get("mode") or "prose"),
                   entry.get("elaborate") is not False)


# --------------------------------------------------------------------------- the on-disk cache

def gen_key(spec: PickSpec, context: Dict[str, Any], signature: str, mode: str, elaborate: bool) -> str:
    """The generated pool's identity across prompts: what the pick is, the values of the
    picks it depends on, the context signature, and the style options are written in."""
    blob = json.dumps({
        "v": OPTIONS_VERSION, "about": _norm(spec.about or spec.label), "deps": sorted((k, str(v)) for k, v in context.items()),
        "context": _norm(signature), "mode": mode, "elaborate": bool(elaborate),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]


class OptionStore:
    """Generated options, one append-only JSONL file per pool: one line per generation
    call, `{"round", "inputs", "options", "model", "at"}`. Nothing is rewritten or
    deleted; a pool is its lines' options in order, first occurrence wins."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._mem: Dict[str, Tuple[int, List[Dict[str, Any]]]] = {}

    def _path(self, key: str) -> Path:
        return self.root / key[:2] / f"{key}.jsonl"

    def records(self, key: str) -> List[Dict[str, Any]]:
        p = self._path(key)
        try:
            size = p.stat().st_size
        except OSError:
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
                continue  # a line another process is still writing
            if isinstance(rec, dict):
                out.append(rec)
        self._mem[key] = (size, out)
        return out

    def options(self, key: str) -> List[str]:
        seen, out = set(), []
        for rec in self.records(key):
            for o in rec.get("options") or []:
                if _norm(o) not in seen:
                    seen.add(_norm(o))
                    out.append(str(o))
        return out

    def rounds(self, key: str) -> int:
        return len(self.records(key))

    def has_round(self, key: str, round_: int) -> bool:
        return any(r.get("round") == round_ for r in self.records(key))

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

    # Per-program flags (a pick whose shared pool failed the bad-pool check gets options
    # written for this prompt's own text).
    def _flags_path(self, program_key: str) -> Path:
        return self.root / "programs" / f"{program_key}.json"

    def specific(self, program_key: str) -> List[str]:
        if not program_key:
            return []
        try:
            return list(json.loads(self._flags_path(program_key).read_text("utf-8")).get("specific") or [])
        except (OSError, ValueError):
            return []

    def mark_specific(self, program_key: str, pick_id: str) -> None:
        if not program_key:
            return
        with self._lock:
            have = self.specific(program_key)
            if pick_id in have:
                return
            p = self._flags_path(program_key)
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps({"specific": have + [pick_id]}), "utf-8")
            os.replace(tmp, p)


# --------------------------------------------------------------------------- generation

@dataclass
class OptionJob:
    key: str                       # gen_key: where the options are stored
    spec: PickSpec
    context: Dict[str, Any]
    program: ProgramContext
    signature: str
    round: int
    existing: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)   # options judged wrong here (bad-pool check)
    project_id: Optional[int] = None
    check: Optional[Callable[["OptionJob"], Awaitable[None]]] = None  # run after the fill lands


Generator = Callable[[OptionJob], Awaitable[Tuple[List[str], str]]]

_GEN_SYSTEM = """You write options for one detail of an image prompt. Each image draws one option and puts
it where the detail stands, so every option must fit the whole prompt.

Write {count} options for {what}. Order them from the most typical for this prompt to the least.
- The first ones are what you'd expect if the prompt didn't say; then common alternatives; the
  last two or three are unusual but real (rare, never impossible).
- Never contradict anything the prompt states{given}.
- Each is a concrete, visual phrase that reads naturally in place of [{label}]{style}.
- Each differs for real from the others and from the existing options (no synonyms).
- Say what to show, never what to leave out (no "no", "not", "without").

Reply with only a JSON list of strings."""


def generation_messages(job: OptionJob, count: int = BATCH_SIZE) -> List[Dict[str, str]]:
    spec, prog = job.spec, job.program
    what = f'"{spec.label}" ({spec.about})' if spec.about and _norm(spec.about) != _norm(spec.label) else f'"{spec.label}"'
    given = ""
    if job.context:
        given = " or these details already chosen: " + "; ".join(f"{k} = {v}" for k, v in job.context.items())
    style = "; tags, a few words each" if prog.mode == "keyword" else (
        "; short, a few words, like the user's own wording" if not prog.elaborate else "; match the examples' length and style")
    system = _GEN_SYSTEM.format(count=count, what=what, given=given, label=spec.label, style=style)
    lines = [f"The prompt, with the details that vary shown as [Label]:\n{prog.template or job.signature}"]
    if job.signature and job.signature != prog.template:
        lines += ["", f"In short: {job.signature}"]
    examples = list(dict.fromkeys([*spec.seeds, *spec.literal]))
    if examples:
        lines += ["", "Examples of the style (you may include them):", *[f"- {o}" for o in examples]]
    if job.existing:
        lines += ["", "Existing options (don't repeat these):", *[f"- {o}" for o in job.existing]]
    if job.avoid:
        lines += ["", "These were judged to contradict this prompt; write options that fit it instead:",
                  *[f"- {o}" for o in job.avoid]]
    return [{"role": "system", "content": system}, {"role": "user", "content": "\n".join(lines)}]


_META = re.compile(r"\b(wait|let's|let me|actually|options?|the prompt|instructions?|here is|here are|i need|json)\b", re.I)
_NOTE = re.compile(r"\s*\((?:[^()]*\b(?:expected|typical|default|common|unusual|rare|alternative)\b[^()]*)\)\s*$", re.I)


def parse_options(reply: str, limit: int = 2 * BATCH_SIZE) -> List[str]:
    """The options in a model's reply: the first JSON list of strings in it, else one
    per line. Reasoning the model leaked, notes like "(expected)", stray brackets and
    over-long lines are dropped, never kept as options."""
    text = reply or ""
    items: List[str] = []
    for m in re.finditer(r"\[[^\[\]]*\]", text, re.S):
        try:
            got = json.loads(m.group(0))
        except ValueError:
            continue
        if isinstance(got, list) and got and all(isinstance(x, str) for x in got):
            items = got
            break
    if not items:
        items = [re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s*", "", ln).strip().strip('",') for ln in text.splitlines()]
    return [o for o in (clean_option(x) for x in items) if o][:limit]


def clean_option(o: Any) -> Optional[str]:
    """One option as it goes in a pool, or None when it isn't one."""
    o = _NOTE.sub("", str(o)).strip().strip('"').strip()
    if (not o or len(o) > 120 or len(o.split()) > 16 or not re.search(r"[^\W\d_]", o)
            or _META.search(o) or o.startswith(("`", "[", "{")) or o.endswith((":", "?"))):
        return None
    return o


async def llm_generator(job: OptionJob) -> Tuple[List[str], str]:
    """Options from the configured chat model (the same role and plumbing as prepare)."""
    from prompt_programs.prepare import _ask_model
    reply = await _ask_model(generation_messages(job), job.project_id)
    return parse_options(reply), "tool_assistant"


class OptionFiller:
    """Background generation: a priority queue worked on the event loop, high first.
    `submit()` is safe from any thread (realize() may run in a worker thread). A pool
    has at most one job queued or running; asking again at high priority promotes it."""

    def __init__(self, store: OptionStore, generator: Generator = llm_generator, workers: int = 2):
        self.store, self.generator, self.workers = store, generator, workers
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self._heap: List[Tuple[int, int, str]] = []
        self._jobs: Dict[str, Tuple[int, OptionJob]] = {}
        self._running: Dict[str, OptionJob] = {}   # key -> the job holding it
        self._seq = itertools.count()
        self._lock = threading.Lock()
        self._wake: Optional[asyncio.Event] = None
        self._tasks: List[asyncio.Task] = []
        self.calls = 0
        self.failures = 0
        self.checks: List[Dict[str, Any]] = []   # bad-pool check results, newest last

    # -- state the options service reads
    def busy(self, key: str) -> bool:
        with self._lock:
            return key in self._jobs or key in self._running

    def _release(self, job: OptionJob) -> None:
        """Give up `job`'s hold on its pool (callers hold the lock). Only the job that
        took the pool can release it: a later round may already have taken it."""
        if self._running.get(job.key) is job:
            del self._running[job.key]

    # -- queueing
    def submit(self, job: OptionJob, priority: str = "low") -> bool:
        rank = PRIORITY.get(priority, 1)
        with self._lock:
            if job.key in self._running:
                return False
            have = self._jobs.get(job.key)
            if have is not None and have[0] <= rank:
                return False
            if have is not None and not job.avoid:
                job.avoid = have[1].avoid
            self._jobs[job.key] = (rank, job)
            heapq.heappush(self._heap, (rank, next(self._seq), job.key))
        self._poke()
        return True

    def attach(self, loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
        """Start working on `loop` (the running one by default). Jobs queued before a
        loop was attached start then."""
        loop = loop or asyncio.get_running_loop()
        if self.loop is loop and self._tasks and not all(t.done() for t in self._tasks):
            return
        self.loop = loop
        self._wake = asyncio.Event()
        self._tasks = [loop.create_task(self._worker()) for _ in range(self.workers)]
        self._wake.set()

    def _poke(self) -> None:
        loop, wake = self.loop, self._wake
        if loop is None or wake is None or loop.is_closed():
            return
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            wake.set()
        else:
            loop.call_soon_threadsafe(wake.set)

    def _next(self) -> Optional[OptionJob]:
        with self._lock:
            while self._heap:
                rank, _, key = heapq.heappop(self._heap)
                have = self._jobs.get(key)
                if have is None or have[0] != rank:
                    continue  # promoted or already taken
                del self._jobs[key]
                self._running[key] = have[1]
                return have[1]
        return None

    async def _worker(self) -> None:
        assert self._wake is not None
        while True:
            job = self._next()
            if job is None:
                self._wake.clear()
                if self._heap:
                    continue
                await self._wake.wait()
                continue
            try:
                await self.run(job)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # one pool failing never stops the queue
                self.failures += 1
                log.warning(f"[fluent-options] generating {job.spec.label!r} failed: {e}")
            finally:
                with self._lock:
                    self._release(job)

    async def run(self, job: OptionJob) -> List[str]:
        """Generate one round for a pool and append it (unless that round exists)."""
        if not self.store.has_round(job.key, job.round):
            started = time.monotonic()
            options, model = await self.generator(job)
            self.calls += 1
            have = {_norm(o) for o in job.existing}
            cleaned = [c for c in (clean_option(x) for x in options) if c]
            fresh = [o for o in dict.fromkeys(cleaned) if _norm(o) not in have]
            self.store.append(job.key, {
                "round": job.round, "options": fresh, "model": model, "at": time.time(),
                "seconds": round(time.monotonic() - started, 2),
                "inputs": {"about": job.spec.about, "label": job.spec.label, "context": job.context,
                           "signature": job.signature, "mode": job.program.mode, "elaborate": job.program.elaborate,
                           "seeds": job.spec.seeds, "avoid": job.avoid},
            })
        with self._lock:  # the pool is filled: a check may queue its next round
            self._release(job)
        if job.check is not None:
            result = await job.check(job)
            if result:
                self.checks.append(result)
        return self.store.options(job.key)

    async def drain(self) -> None:
        """Run every queued job now, in priority order (for evaluation and tests)."""
        while True:
            job = self._next()
            if job is None:
                return
            try:
                await self.run(job)
            except Exception as e:
                self.failures += 1
                log.warning(f"[fluent-options] generating {job.spec.label!r} failed: {e}")
            finally:
                with self._lock:
                    self._release(job)


# --------------------------------------------------------------------------- the options service

class GeneratedOptions:
    """The options service for realize(): user lists exactly, everything else seeds plus
    generated options. Each pool is read once per instance (one draw), so a fill landing
    mid-draw can't change it; `limits` truncates pools to a recorded revision's lengths."""

    def __init__(self, store: Optional[OptionStore], program: ProgramContext,
                 edits: Optional[Dict[str, Dict[str, Any]]] = None, filler: Optional[OptionFiller] = None,
                 resolver: Optional[ClassResolver] = None, limits: Optional[Dict[str, int]] = None,
                 project_id: Optional[int] = None, generate: bool = True,
                 checker: Optional[Callable[[OptionJob, "GeneratedOptions"], Awaitable[Any]]] = None):
        self.store, self.program, self.filler = store, program, filler
        self.edits = edits or {}
        self.literal = LiteralOptions(self.edits)
        self.resolver = resolver or NoVocabulary()
        self.limits = limits or {}
        self.project_id = project_id
        self.generate = generate and store is not None
        self.specific = set(store.specific(program.key)) if store is not None else set()
        self.checker = checker
        self._pools: Dict[str, Pool] = {}
        self.requests: List[Tuple[str, str]] = []
        self.queued: List[str] = []
        self._seen: Dict[str, Tuple[PickSpec, Dict[str, Any]]] = {}

    def seen_specs(self) -> List[Tuple[PickSpec, Dict[str, Any]]]:
        """Every generated pick and dependency context read through this service."""
        return list(self._seen.values())

    def reset(self) -> None:
        """Forget the pools read so far (the next get() reads the cache again)."""
        self._pools.clear()

    # -- identity
    def _where(self, spec: PickSpec, context: Dict[str, Any]) -> Tuple[str, str, str]:
        """(revision pool key, storage key, signature) for a generated pick."""
        specific = spec.id in self.specific and self.program.template != self.program.signature
        signature = self.program.template if specific else self.program.signature
        key = pool_key(spec, context) + (" | written for this prompt" if specific else "")
        return key, gen_key(spec, context, signature, self.program.mode, self.program.elaborate), signature

    def get(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        if not generated_pick(spec):
            return self.literal.get(spec, context)
        key, skey, signature = self._where(spec, context)
        if key in self._pools:
            return self._pools[key]
        self._seen.setdefault(key, (spec, dict(context)))
        pool, items, rounds = self._read(spec, context, key, skey)
        if self.generate and key not in self.limits and rounds < MAX_ROUNDS:
            if rounds == 0:
                self._submit(spec, context, skey, signature, "low", items)
            elif len(pool.items) < THIN:
                self._submit(spec, context, skey, signature, "high", items)
        pool.more_coming = bool(self.filler is not None and self.filler.busy(skey))
        self._pools[key] = pool
        return pool

    def fresh_pool(self, spec: PickSpec, context: Dict[str, Any]) -> Pool:
        """The pool as the cache holds it now (no memo, no requests)."""
        key, skey, _ = self._where(spec, context)
        return self._read(spec, context, key, skey)[0]

    def rewrite_for_prompt(self, spec: PickSpec, context: Dict[str, Any], avoid: Sequence[str]) -> None:
        """The bad-pool fix: options written for this prompt's own text, at high
        priority. A pool keyed by a shared signature switches this pick to a pool keyed
        by the prompt itself; a pool already keyed by the prompt gets a new round told
        which options didn't fit."""
        if self.program.template != self.program.signature and spec.id not in self.specific:
            if self.store is not None:
                self.store.mark_specific(self.program.key, spec.id)
            self.specific.add(spec.id)
            self._pools.clear()
            avoid = ()
        key, skey, signature = self._where(spec, context)
        existing = self.store.options(skey) if self.store is not None else []
        self._submit(spec, context, skey, signature, "high", existing, avoid)

    def _read(self, spec: PickSpec, context: Dict[str, Any], key: str, skey: str) -> Tuple[Pool, List[str], int]:
        self.resolver.resolve(spec)  # no vocabulary yet: every pick resolves to none
        written = list(dict.fromkeys([*spec.seeds, *spec.literal]))
        edit = self.edits.get(spec.id) or {}
        adds = [str(x) for x in edit.get("add") or [] if str(x).strip()]
        generated = self.store.options(skey) if self.store is not None else []
        items: List[str] = []
        seen = set()
        for o in [*written, *adds, *generated]:
            if _norm(o) not in seen:
                seen.add(_norm(o))
                items.append(o)
        weights = [_weight(i, len(written) + len(adds)) for i in range(len(items))]
        gone = {_norm(x) for x in edit.get("remove") or []}
        kept = [(o, w) for o, w in zip(items, weights) if _norm(o) not in gone]
        if key in self.limits:  # replaying a recorded revision
            kept = kept[: int(self.limits[key])]
        pool = Pool(key, [o for o, _ in kept], [w for _, w in kept], False)
        rounds = self.store.rounds(skey) if self.store is not None else 0
        return pool, items, rounds

    def request_more(self, spec: PickSpec, context: Dict[str, Any], priority: str) -> None:
        if not generated_pick(spec):
            return  # a user list is never expanded
        key, skey, signature = self._where(spec, context)
        self.requests.append((key, priority))
        if not self.generate or (self.store is not None and self.store.rounds(skey) >= MAX_ROUNDS):
            return
        have = self._pools.get(key)
        existing = have.items if have is not None else self.store.options(skey) if self.store is not None else []
        self._submit(spec, context, skey, signature, priority, existing)

    def _submit(self, spec: PickSpec, context: Dict[str, Any], skey: str, signature: str, priority: str,
                existing: Sequence[str], avoid: Sequence[str] = ()) -> None:
        if self.filler is None or self.store is None:
            return
        round_ = self.store.rounds(skey)
        job = OptionJob(skey, spec, dict(context), self.program, signature, round_,
                        list(existing), list(avoid), self.project_id)
        if self.checker is not None and round_ == 0:
            checker = self.checker
            job.check = lambda j, _self=self: checker(j, _self)
        if self.filler.submit(job, priority):
            self.queued.append(skey)


def _weight(i: int, written: int) -> float:
    """Rank order: the writer's options decay like its lists always have; generated
    options continue from there more gently, so a grown pool keeps its support."""
    if i < written:
        return RANK_DECAY ** i
    base = RANK_DECAY ** max(0, written - 1) if written else 1.0
    return base * GEN_DECAY ** (i - written + 1)


# --------------------------------------------------------------------------- per profile

_stores: Dict[str, OptionStore] = {}
_fillers: Dict[str, OptionFiller] = {}


def store_for(profile_id: Optional[str]) -> OptionStore:
    import app_dirs
    from core.profile_context import get_current_profile
    pid = profile_id or get_current_profile()
    root = app_dirs.get_profile_dir(pid) / "prompt_programs" / "options"
    s = _stores.get(str(root))
    if s is None:
        s = _stores[str(root)] = OptionStore(root)
    return s


def filler_for(profile_id: Optional[str]) -> OptionFiller:
    store = store_for(profile_id)
    f = _fillers.get(str(store.root))
    if f is None:
        f = _fillers[str(store.root)] = OptionFiller(store)
    try:
        f.attach()
    except RuntimeError:
        pass  # no running loop here: jobs wait until an async caller attaches one
    return f


__all__ = [
    "GeneratedOptions", "OptionFiller", "OptionJob", "OptionStore", "ProgramContext", "filler_for", "gen_key",
    "generated_pick", "generation_messages", "llm_generator", "parse_options", "store_for",
]
