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
from prompt_programs.additions import profile_additions
from prompt_programs.compact import is_pool_ref
from prompt_programs.draws import CONTEXT_VERSIONS, draw, fixed_text, uses_draws
from prompt_programs.judge import FluentSettings, settings
from prompt_programs.reach import reach_of
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
                cfg: Optional[FluentSettings] = None, mine: Optional[Dict[str, List[str]]] = None) -> Runtime:
    """What realize() draws a program with pick specs with. Passing a recorded
    `revision` replays its pools at their recorded lengths. `mine`: the user's options kept
    per vocabulary list (additions.py); the profile's, unless a caller brings its own store."""
    cfg = cfg or settings()
    if mine is None:
        mine = profile_additions(profile_id) if store is None else {}
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
    # A revision drawn before context (vocab.py) replays without it; one drawn with it records its version.
    if rev.get("context") not in (None, *CONTEXT_VERSIONS):
        raise ProgramError(f"This prompt was drawn with context rules {rev.get('context')}, which this version of "
                           "Stimma doesn't have, so it can't be replayed exactly.")
    context = not rev or rev.get("context") in CONTEXT_VERSIONS
    pools = rev.get("pools")
    if isinstance(pools, dict) and any(is_pool_ref(v) for v in pools.values()):
        # Vocabulary pools recorded by reference (compact.py): read back whole, as they were drawn from.
        kept = getattr(store, "pools", None)
        read = {k: (kept.get(v) if kept is not None else None) if is_pool_ref(v) else v for k, v in pools.items()}
        if any(v is None for v in read.values()):
            raise ProgramError("The choices this prompt was drawn from aren't stored on this device any more, "
                               "so it can't be replayed exactly.")
        pools = read
    # A pool's recorded length, or a vocabulary list's whole pool ([[value, weight], ...]).
    limits = ({str(k): (int(v) if not isinstance(v, list) else v) for k, v in pools.items()
               if (isinstance(v, (int, float)) and not isinstance(v, bool)) or isinstance(v, list)}
              if isinstance(pools, dict) else None)
    options = GeneratedOptions(store, program_context(entry), edits=edits, filler=filler,
                               limits=limits, project_id=project_id,
                               generate=cfg.generate_options, version=version, context=context, mine=mine)
    if rev.get("context"):   # a replay records the context version it was drawn with
        options.context_version = str(rev["context"])
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
PARTS_MAX = 400  # a longer list sends no parts: the option-to-part map would be large


def list_parts(leaf: Any, options: List[str]) -> Optional[Dict[str, Any]]:
    """A list's named parts for the picker's chips: its first local facet that sorts the
    options ({"name": facet, "values": the parts in use, in the list's order, "of": {option:
    its part}}). An option tagged with several parts, or none, is left out of `of`. None for
    a list with no such facet, or with more than PARTS_MAX options."""
    if len(options) > PARTS_MAX:
        return None
    for facet, names in leaf.local_facets.items():
        of: Dict[str, str] = {}
        for o in options:
            v = leaf.value(o)
            tagged = v.tags.get(facet) if v is not None else None
            if isinstance(tagged, (list, tuple)) and len(tagged) == 1 and str(tagged[0]) in names:
                of[o] = str(tagged[0])
        if of:
            used = set(of.values())
            return {"name": facet, "values": [n for n in names if n in used], "of": of}
    return None


def pool_options(entry: Dict[str, Any], pins: Optional[Dict[str, Any]] = None, *, profile_id: Optional[str] = None,
                 project_id: Optional[int] = None, store: Optional[OptionStore] = None,
                 cfg: Optional[FluentSettings] = None, mine: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """The options each generated pick draws from now: its seeds plus whatever has been
    generated, for the upstream values pinned (or drawn, when nothing upstream is pinned).
    A pick's own pins don't narrow what it shows. Never calls a model (an unseen pool is
    queued to fill, like any draw); `more` lists picks whose pools are still filling."""
    out: Dict[str, List[str]] = {}
    more: List[str] = []
    vocab: Dict[str, Dict[str, Any]] = {}
    if not uses_draws(entry.get("program") or ""):
        return {"options": out, "more": more, "vocab": vocab}
    rt = runtime_for(entry, profile_id=profile_id, project_id=project_id, store=store, cfg=cfg, mine=mine)
    loras = [LoraInfo(**lo) for lo in entry.get("loras") or []]
    params = set(entry.get("params") or {}) or None
    pins = {k: v for k, v in (pins or {}).items() if v}
    generated = [c["id"] for c in entry.get("choices") or [] if c.get("kind") == "pick" and c.get("source") != "list"]
    bound_cls = {c["id"]: c.get("cls") for c in entry.get("choices") or [] if c.get("cls")}
    listed = {c["id"]: c.get("options") for c in entry.get("choices") or [] if c.get("cls")}

    def own_adds(cid: str) -> List[str]:   # options the user added in this choice's card
        return [str(x) for x in ((rt.options.edits.get(cid) or {}).get("add") or [])]
    for cid in generated:
        others = {k: v for k, v in pins.items() if k != cid}
        seen: List[str] = []
        contexts: List[Any] = []   # the context the pick's pool was drawn in, per draw (reach.py)
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
            contexts.extend(rt.options.drawn_context(cid))
            rt.options.reset()
        leaf = vocabulary().get(bound_cls.get(cid))
        if leaf is not None and seen:
            # A bound pick shows its whole list (the picker searches and groups it), each
            # value's tier, and which values were generated to extend an open list. Opt-in
            # values the user's words didn't ask for are drawn only when picked: their own group.
            narrowed = [str(x) for x in (entry.get("filters") or {}).get(cid) or ()]
            asked = set(narrowed)
            # A narrowed list's rest is drawn only once ticked too (vocab.Leaf.pool_values).
            tiers = {v.text: ("opt_in" if (v.opt_in or asked) and v.text not in asked else v.tier) for v in leaf.values}
            # The user's own options kept for this list (additions.py) sit with the usual values,
            # or with the values drawn only once picked where the choice's words decide.
            mine_here = {o: held for o, held in rt.options.mine_shown.get(cid, {}).items() if o in seen}
            tiers.update({o: "opt_in" if held else "typical" for o, held in mine_here.items()})
            out[cid] = seen
            vocab[cid] = {"cls": leaf.id, "label": leaf.label, "closed": leaf.closed,
                          "tiers": {o: tiers.get(o, "generated") for o in seen}}
            if len(leaf.values) > PARTS_MAX:
                # A long list (thousands of faces) came with the prepared program's choice already:
                # this answer is asked for again on every tick and while pools fill, so it carries
                # only what the choice doesn't have, and only the tiers the picker acts on.
                have = set(listed.get(cid) or ())
                out[cid] = [o for o in seen if o not in have]
                vocab[cid]["tiers"] = {o: t for o, t in vocab[cid]["tiers"].items() if t != "typical"}
            if mine_here:
                vocab[cid]["mine"] = list(mine_here)
            parts = list_parts(leaf, seen)
            if parts:
                vocab[cid]["parts"] = parts
            ch = next((c for c in entry.get("choices") or [] if c.get("id") == cid), {})
            said = str(ch.get("said") or "")
            where = ch.get("where")
            words = str(ch.get("where_words") or (where if isinstance(where, str) else "") or "")
            shown = vocab[cid]["tiers"]
            reach = reach_of(leaf, seen, [o for o in seen if shown.get(o) == "opt_in"], [*mine_here, *own_adds(cid)],
                             said=said, narrowed=narrowed, words=words, contexts=contexts)
            # A long list keeps its plain row: its settings would name (and "Any" would tick)
            # thousands of values.
            if reach and len(leaf.values) <= PARTS_MAX:
                vocab[cid]["reach"] = reach
        elif seen:
            out[cid] = seen[:60]
    return {"options": out, "more": more, "vocab": vocab}


__all__ = ["Runtime", "attach_filler", "pool_options", "program_context", "runtime_for", "start_options"]
