"""The draw runtime for programs with pick specs: their options service.

realize() asks `runtime_for()` what to draw a program with pick specs from: generated
options from the profile's cache, filling in the background. A recorded revision replays
the pools it drew from.

Prepare calls `start_options()` once such a program is stored. It returns at once;
option generation for every generated pick runs in the background at low priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from prompt_programs.draws import draw, fixed_text, uses_draws
from prompt_programs.judge import FluentSettings, settings
from prompt_programs.options import (
    FIRST_OPTIONS_VERSION, OPTIONS_VERSIONS, GeneratedOptions, OptionFiller, OptionStore, ProgramContext, filler_for,
    store_for,
)
from prompt_programs.runtime import LoraInfo, ProgramError
from prompt_programs.vocab import vocabulary

log = get_logger(__name__)

WARM_DRAWS = 8         # draws at prepare that find the pools to fill
# A revision records the judge it drew with. Drawing judged nothing, so only a revision
# drawn that way (or recording none) replays exactly.
UNJUDGED = (None, "null")


@dataclass
class Runtime:
    options: GeneratedOptions


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
                revision: Optional[Dict[str, Any]] = None,
                store: Optional[OptionStore] = None, filler: Optional[OptionFiller] = None,
                cfg: Optional[FluentSettings] = None) -> Runtime:
    """What realize() draws a program with pick specs with. Passing a recorded
    `revision` replays its pools at their recorded lengths."""
    cfg = cfg or settings()
    store = store if store is not None else _profile_store(profile_id)
    if filler is None and store is not None and cfg.generate_options:
        try:
            filler = filler_for(profile_id)
        except Exception as e:
            log.debug(f"[fluent] no option filler: {e}")
    rev = revision if isinstance(revision, dict) else {}
    if rev.get("judge") not in UNJUDGED:
        raise ProgramError(f"This prompt was drawn with judge {rev.get('judge')}, which this version of Stimma doesn't "
                           "have, so it can't be replayed exactly.")
    version = str(rev.get("options") or FIRST_OPTIONS_VERSION) if rev else None  # none recorded: drew before opts-2
    if version is not None and version not in OPTIONS_VERSIONS:
        raise ProgramError(f"This prompt was drawn from options version {version}, which this version of Stimma "
                           "can't read, so it can't be replayed exactly.")
    pools = rev.get("pools")
    # A pool's recorded length, or a vocabulary list's whole pool ([[value, weight], ...]).
    limits = ({str(k): (int(v) if not isinstance(v, list) else v) for k, v in pools.items()
               if (isinstance(v, (int, float)) and not isinstance(v, bool)) or isinstance(v, list)}
              if isinstance(pools, dict) else None)
    options = GeneratedOptions(store, program_context(entry), edits=edits, filler=filler,
                               limits=limits, project_id=project_id,
                               generate=cfg.generate_options, version=version)
    return Runtime(options)


def attach_filler(entry: Dict[str, Any], profile_id: Optional[str] = None) -> None:
    """Call from async code before realize() runs in a worker thread, so background
    option generation for a new-format program has the event loop to run on."""
    if not uses_draws(entry.get("program") or "") or not settings().generate_options:
        return
    try:
        filler_for(profile_id)
    except Exception as e:
        log.debug(f"[fluent] no option filler: {e}")


# --------------------------------------------------------------------------- prepare hook

def start_options(entry: Dict[str, Any], *, profile_id: Optional[str] = None, project_id: Optional[int] = None,
                  store: Optional[OptionStore] = None, filler: Optional[OptionFiller] = None,
                  cfg: Optional[FluentSettings] = None) -> List[str]:
    """Queue background option generation for a just-prepared program. Returns the
    storage keys queued. Never calls a model itself and never raises: a program whose
    pools can't fill still draws from its seeds."""
    if not uses_draws(entry.get("program") or ""):
        return []
    from prompt_programs.fix import kick_judge
    kick_judge(cfg)  # the pinned judge's first-use download starts now, before the first image
    try:
        rt = runtime_for(entry, profile_id=profile_id, project_id=project_id, store=store, filler=filler, cfg=cfg)
        loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
        params = set(entry.get("params") or {}) or None
        # A few cheap draws visit the pools this program uses (dependent pools included,
        # for the upstream values they draw); each unseen pool queues a fill.
        for seed in range(WARM_DRAWS):
            try:
                draw(entry["program"], 7919 * seed + 1, None, loras, params, None, None, options=rt.options)
            except ProgramError:
                continue
            rt.options.reset()
        return rt.options.queued
    except Exception as e:
        log.warning(f"[fluent] couldn't start option generation: {e}")
        return []


# --------------------------------------------------------------------------- what a picker shows

POOL_DRAWS = 4  # draws per pick: enough to visit the pool its upstream picks key


def pool_options(entry: Dict[str, Any], pins: Optional[Dict[str, Any]] = None, *, profile_id: Optional[str] = None,
                 project_id: Optional[int] = None, store: Optional[OptionStore] = None,
                 cfg: Optional[FluentSettings] = None) -> Dict[str, Any]:
    """The options each generated pick draws from now: its seeds plus whatever has been
    generated, for the upstream values pinned (or drawn, when nothing upstream is pinned).
    A pick's own pins don't narrow what it shows. Never calls a model (an unseen pool is
    queued to fill, like any draw); `more` lists picks whose pools are still filling."""
    out: Dict[str, List[str]] = {}
    more: List[str] = []
    vocab: Dict[str, Dict[str, Any]] = {}
    if not uses_draws(entry.get("program") or ""):
        return {"options": out, "more": more, "vocab": vocab}
    rt = runtime_for(entry, profile_id=profile_id, project_id=project_id, store=store, cfg=cfg)
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    params = set(entry.get("params") or {}) or None
    pins = {k: v for k, v in (pins or {}).items() if v}
    generated = [c["id"] for c in entry.get("choices") or [] if c.get("kind") == "pick" and c.get("source") != "list"]
    bound_cls = {c["id"]: c.get("cls") for c in entry.get("choices") or [] if c.get("cls")}
    for cid in generated:
        others = {k: v for k, v in pins.items() if k != cid}
        seen: List[str] = []
        for seed in range(POOL_DRAWS):
            try:
                res = draw(entry["program"], 7919 * seed + 3, others, loras, params, None, None, options=rt.options)
            except ProgramError:
                continue
            if cid in (res.more_coming or []) and cid not in more:
                more.append(cid)
            for d in res.draws:
                if d.id == cid:
                    seen.extend(o for o in d.options if o not in seen)
            rt.options.reset()
        leaf = vocabulary().get(bound_cls.get(cid))
        if leaf is not None and seen:
            # A bound pick shows its whole list (the picker searches and groups it), each
            # value's tier, and which values were generated to extend an open list.
            tiers = {v.text: v.tier for v in leaf.values}
            out[cid] = seen
            vocab[cid] = {"cls": leaf.id, "label": leaf.label, "closed": leaf.closed,
                          "tiers": {o: tiers.get(o, "generated") for o in seen}}
        elif seen:
            out[cid] = seen[:60]
    return {"options": out, "more": more, "vocab": vocab}


__all__ = ["Runtime", "attach_filler", "pool_options", "program_context", "runtime_for", "start_options"]
