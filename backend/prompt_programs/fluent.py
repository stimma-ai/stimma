"""The draw runtime for programs with pick specs: options service, judge, knobs.

realize() asks `runtime_for()` what to draw a new-format program with: generated
options from the profile's cache (filling in the background), the configured judge
(the null judge when none is configured or it can't load), and the rarity knob and
wrong cut from config.

Prepare calls `start_options()` once a new-format program is stored. It returns at
once; option generation for every generated pick runs in the background at low
priority, and each pool's first batch is checked against the prompt's fixed text (the
bad-pool check) when a judge is configured.
"""

from __future__ import annotations

import asyncio
import dataclasses
import random
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from prompt_programs.draws import (
    DEFAULT_RARITY, WRONG_CUT, NullJudge, PickSpec, Question, draw, fixed_text, keep_rate, uses_draws,
)
from prompt_programs.judge import FluentSettings, configured_judge, settings
from prompt_programs.options import (
    GeneratedOptions, OptionFiller, OptionJob, OptionStore, ProgramContext, filler_for, generated_pick, store_for,
)
from prompt_programs.runtime import LoraInfo, ProgramError

log = get_logger(__name__)

PREFILL_DRAWS = 8      # draws per prefill: each one judges the pools in the states it reaches
PREFILL_POOL = 48      # pool options judged per pick and state when prefilling
CHECK_PROPOSALS = 20   # proposals judged per generated pool at the bad-pool check
CHECK_MIN_OK = 5       # fewer non-wrong proposals than this: ask for options written for this prompt
WARM_DRAWS = 8         # null-judge draws at prepare that find the pools to fill


@dataclass
class Runtime:
    options: GeneratedOptions
    judge: Any
    rarity: float
    wrong_cut: float
    keep: str = "cut"


def program_context(entry: Dict[str, Any]) -> ProgramContext:
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    try:
        template = entry.get("template") or fixed_text(entry["program"], loras, set(entry.get("params") or {}) or None)
    except ProgramError:
        template = str(entry.get("example") or "")
    return ProgramContext.of({**entry, "template": template})


def _profile_store(profile_id: Optional[str]) -> Optional[OptionStore]:
    try:
        return store_for(profile_id)
    except Exception as e:  # no profile (scripts): draws keep working on seeds alone
        log.debug(f"[fluent] no option store: {e}")
        return None


def runtime_for(entry: Dict[str, Any], *, edits: Optional[Dict[str, Dict[str, Any]]] = None,
                profile_id: Optional[str] = None, project_id: Optional[int] = None,
                revision: Optional[Dict[str, Any]] = None, judge: Any = None,
                store: Optional[OptionStore] = None, filler: Optional[OptionFiller] = None,
                cfg: Optional[FluentSettings] = None) -> Runtime:
    """What realize() draws a new-format program with. Passing a recorded `revision`
    replays its pools at their recorded lengths, its knob and its wrong cut."""
    cfg = cfg or settings()
    store = store if store is not None else _profile_store(profile_id)
    if filler is None and store is not None and cfg.generate_options:
        try:
            filler = filler_for(profile_id)
        except Exception as e:
            log.debug(f"[fluent] no option filler: {e}")
    judge = judge if judge is not None else configured_judge(cfg)
    rev = revision if isinstance(revision, dict) else {}
    if rev:  # replay: the recorded judge and knobs, never today's
        recorded = rev.get("judge")
        if recorded in (None, NullJudge.version):
            judge = NullJudge()
        elif getattr(judge, "version", None) != recorded:
            raise ProgramError(f"This prompt was drawn with judge {recorded}, which isn't available now, "
                               "so it can't be replayed exactly.")
    rarity = _number(rev.get("rarity"), DEFAULT_RARITY if rev else cfg.rarity)
    wrong_cut = _number(rev.get("wrong_cut"), WRONG_CUT if rev else cfg.wrong_cut)
    keep = str(rev.get("keep", "tiers")) if rev else cfg.keep  # a revision without "keep" drew with tiers
    pools = rev.get("pools")
    limits = ({str(k): int(v) for k, v in pools.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
              if isinstance(pools, dict) else None)
    options = GeneratedOptions(store, program_context(entry), edits=edits, filler=filler,
                               limits=limits, project_id=project_id,
                               generate=cfg.generate_options,
                               checker=pool_checker(judge, wrong_cut) if not getattr(judge, "null", False) else None)
    return Runtime(options, judge, rarity, wrong_cut, keep)


def attach_filler(entry: Dict[str, Any], profile_id: Optional[str] = None) -> None:
    """Call from async code before realize() runs in a worker thread, so background
    option generation for a new-format program has the event loop to run on."""
    if not uses_draws(entry.get("program") or "") or not settings().generate_options:
        return
    try:
        filler_for(profile_id)
    except Exception as e:
        log.debug(f"[fluent] no option filler: {e}")


def _number(v: Any, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------- prepare hook

def start_options(entry: Dict[str, Any], *, profile_id: Optional[str] = None, project_id: Optional[int] = None,
                  store: Optional[OptionStore] = None, filler: Optional[OptionFiller] = None, judge: Any = None,
                  cfg: Optional[FluentSettings] = None, prefill: bool = True) -> List[str]:
    """Queue background option generation for a just-prepared program, and (with a
    judge configured) judgment prefill once those pools have filled. Returns the storage
    keys queued. Never calls a model itself and never raises: a program whose pools can't
    fill still draws from its seeds."""
    if not uses_draws(entry.get("program") or ""):
        return []
    try:
        rt = runtime_for(entry, profile_id=profile_id, project_id=project_id, store=store, filler=filler, judge=judge,
                         cfg=cfg)
        loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
        params = set(entry.get("params") or {}) or None
        # A few cheap null-judge draws visit the pools this program uses (dependent pools
        # included, for the upstream values they draw); each unseen pool queues a fill.
        from prompt_programs.draws import NullJudge
        for seed in range(WARM_DRAWS):
            try:
                draw(entry["program"], 7919 * seed + 1, None, loras, params, None, None,
                     options=rt.options, judge=NullJudge())
            except ProgramError:
                continue
            rt.options.reset()
        queued = rt.options.queued
        if prefill:
            schedule_prefill(entry, rt.judge, rt.options.filler, queued, profile_id=profile_id, store=rt.options.store)
        return queued
    except Exception as e:
        log.warning(f"[fluent] couldn't start option generation: {e}")
        return []


# --------------------------------------------------------------------------- judgment prefill

_prefill_lock = threading.Lock()


def prefill_judgments(entry: Dict[str, Any], judge: Any, *, store: Optional[OptionStore] = None,
                      profile_id: Optional[str] = None, draws: int = PREFILL_DRAWS, pool: int = PREFILL_POOL,
                      pins: Optional[Dict[str, Any]] = None, cfg: Optional[FluentSettings] = None) -> Dict[str, Any]:
    """Judge a program's pools ahead of its draws, so a judge too slow to run per image
    (a CPU) still serves them from the cache. Judgments are keyed by the judge state and
    the option, so they're exactly what later draws ask for. Phase 1's state is the
    prompt's fixed text (with any pins), the same for every draw; later phases' states
    depend on earlier values, so each prefill draw judges the pools in the states it
    reaches. Blocking: run it in a thread. Never generates options."""
    if getattr(judge, "null", False) or not uses_draws(entry.get("program") or ""):
        return {"draws": 0}
    cfg = cfg or settings()
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    params = set(entry.get("params") or {}) or None
    clean_pins = {str(k): [str(x) for x in (v if isinstance(v, list) else [v])] for k, v in (pins or {}).items() if v}
    done = 0
    with _prefill_lock:  # one prefill at a time: it's background work
        for seed in range(draws):
            rt = runtime_for(entry, profile_id=profile_id, store=store, judge=judge,
                             cfg=dataclasses.replace(cfg, generate_options=False))
            try:
                draw(entry["program"], 104729 * seed + 3, clean_pins, loras, params, None, None,
                     options=rt.options, judge=judge, rarity=rt.rarity, wrong_cut=rt.wrong_cut, keep=rt.keep,
                     prefetch=pool)
                done += 1
            except ProgramError:
                continue
    return {"draws": done, **(judge.stats() if hasattr(judge, "stats") else {})}


def schedule_prefill(entry: Dict[str, Any], judge: Any, filler: Optional[OptionFiller], keys: List[str], *,
                     profile_id: Optional[str] = None, store: Optional[OptionStore] = None,
                     wait_seconds: float = 300.0) -> Optional["asyncio.Future[Any]"]:
    """After the pools queued at prepare have filled (or `wait_seconds` pass), prefill
    judgments in a background thread. Returns the task, or None when there's no judge
    or no event loop."""
    if getattr(judge, "null", False):
        return None
    running = _running_loop()
    loop = running or (filler.loop if filler is not None else None)
    if loop is None or loop.is_closed():
        return None

    async def run():
        deadline = loop.time() + wait_seconds
        while filler is not None and any(filler.busy(k) for k in keys) and loop.time() < deadline:
            await asyncio.sleep(0.5)
        try:
            return await asyncio.to_thread(prefill_judgments, entry, judge, store=store, profile_id=profile_id)
        except Exception as e:
            log.warning(f"[fluent] judgment prefill failed: {e}")
            return None

    return loop.create_task(run()) if running is loop else asyncio.run_coroutine_threadsafe(run(), loop)


def _running_loop() -> Optional[asyncio.AbstractEventLoop]:
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


# --------------------------------------------------------------------------- bad-pool check

def pool_checker(judge: Any, wrong_cut: float):
    """After a pool's first batch lands: judge its first proposals against the prompt's
    fixed text. If fewer than CHECK_MIN_OK aren't wrong, the shared pool doesn't fit
    this prompt: ask, at high priority, for options written for this prompt."""

    async def check(job: OptionJob, options: GeneratedOptions) -> Optional[Dict[str, Any]]:
        if job.round != 0:
            return None
        store = options.store
        if store is None:
            return None
        pool = options.fresh_pool(job.spec, job.context)
        if not pool.items:
            return None
        rng = random.Random(f"check:{job.key}")
        proposals = rng.choices(pool.items, weights=pool.weights, k=CHECK_PROPOSALS)
        state = job.program.template
        if job.context:
            state += "\n(Given: " + "; ".join(f"{k}: {v}" for k, v in job.context.items()) + ")"
        distinct = list(dict.fromkeys(proposals))
        qs = [Question(job.spec.id, job.spec.label, job.spec.about, v) for v in distinct]
        tiers = await asyncio.to_thread(judge.judge, state, qs)
        wrong = {v for v, t in zip(distinct, tiers) if keep_rate(t, 1.0, wrong_cut) <= 0}
        ok = sum(1 for v in proposals if v not in wrong)
        result = {"key": job.key, "ok": ok, "of": len(proposals), "wrong": sorted(wrong)}
        if ok < CHECK_MIN_OK:
            log.info(f"[fluent] bad pool for {job.spec.label!r}: {ok}/{len(proposals)} fit; asking for options written for this prompt")
            options.rewrite_for_prompt(job.spec, job.context, sorted(wrong))
        return result

    return check


__all__ = ["Runtime", "attach_filler", "prefill_judgments", "schedule_prefill", "program_context", "pool_checker", "runtime_for", "start_options"]
