"""What a prompt's picks draw from: their options service.

realize() asks `runtime_for()` for the options a prepared prompt's picks draw from: the
vocabulary lists, and options written for the prompt, from the profile's cache and filling
in the background. A recorded revision replays the pools it drew from.

When a reading lands, `start_options()` queues the writing of every pool the prompt's picks
reach. It returns at once; the writing runs in the background at low priority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logging import get_logger
from prompt_programs.additions import profile_additions
from prompt_programs.compact import is_pool_ref
from prompt_programs.fill import CONTEXT_VERSION, ProgramError, fill
from prompt_programs.judge import FluentSettings, settings
from prompt_programs.reach import reach_of
from prompt_programs.options import (
    FIRST_OPTIONS_VERSION, OPTIONS_VERSIONS, GeneratedOptions, OptionFiller, OptionStore, ProgramContext, filler_for,
    store_for,
)
from prompt_programs.vocab import vocabulary

log = get_logger(__name__)

WARM_DRAWS = 8         # draws at prepare that find the pools to fill
# A revision records the judge it drew with. Drawing judged nothing, so only a revision
# drawn that way (or recording none) replays exactly.
UNJUDGED = (None, "null")


CONTEXT_VERSIONS = ("ctx-1", CONTEXT_VERSION)   # what a replay can read


def _drawn(entry: Dict[str, Any], seed: int, pins: Optional[Dict[str, Any]], options: Any,
           edits: Optional[Dict[str, Dict[str, Any]]] = None) -> Any:
    return fill(entry, seed, pins, None, edits, options=options)


def has_draws(entry: Dict[str, Any]) -> bool:
    """Whether a prepared prompt has anything to draw (a slot read, or a list)."""
    return bool(entry.get("picks"))


@dataclass
class Runtime:
    options: GeneratedOptions


def program_context(entry: Dict[str, Any]) -> ProgramContext:
    return ProgramContext.of(entry)


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
                cfg: Optional[FluentSettings] = None, mine: Optional[Dict[str, List[str]]] = None,
                zones: Optional[Dict[str, List[str]]] = None) -> Runtime:
    """What realize() draws a prepared prompt's picks with. Passing a recorded
    `revision` replays its pools at their recorded lengths. `mine`: the user's options kept
    per vocabulary list (additions.py); the profile's, unless a caller brings its own store.
    `zones`: the zones chosen per slot pick (options.GeneratedOptions)."""
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
                               generate=cfg.generate_options, version=version, context=context, mine=mine,
                               zones=zones)
    if rev.get("context"):   # a replay records the context version it was drawn with
        options.context_version = str(rev["context"])
    return Runtime(options)


def attach_filler(entry: Dict[str, Any], profile_id: Optional[str] = None) -> None:
    """Call from async code before realize() runs in a worker thread, so background
    option generation has the event loop to run on."""
    if not has_draws(entry) or not settings().generate_options:
        return
    try:
        filler_for(profile_id)
    except Exception as e:
        log.debug(f"[fluent] no option filler: {e}")


# --------------------------------------------------------------------------- prepare hook

def start_options(entry: Dict[str, Any], *, profile_id: Optional[str] = None, project_id: Optional[int] = None,
                  store: Optional[OptionStore] = None, filler: Optional[OptionFiller] = None,
                  cfg: Optional[FluentSettings] = None) -> List[str]:
    """Queue background option generation for a prepared prompt. Returns the
    storage keys queued. Never calls a model itself and never raises: a prompt whose
    pools can't fill still draws from its seeds."""
    if not has_draws(entry):
        return []
    try:
        rt = runtime_for(entry, profile_id=profile_id, project_id=project_id, store=store, filler=filler, cfg=cfg)
        # A few cheap draws visit the pools this prompt uses (dependent pools included,
        # for the upstream values they draw); each unseen pool queues a fill.
        for seed in range(WARM_DRAWS):
            try:
                _drawn(entry, 7919 * seed + 1, None, rt.options)
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


def list_groups(leaf: Any, options: List[str]) -> Dict[str, Dict[str, List[str]]]:
    """A list's groups for the picker's chips: {facet: {part: [options]}} for each of its local
    facets, an option in every part it is tagged with, and the list's declared groups (descent's
    heritages) as facet "group". Parts in the list's order, options in the order given; parts
    no option is in are left out, and so is a part holding only the list's plain value (a face
    part's "nothing notable" is an option, not a group). Empty for a list with more than
    PARTS_MAX options."""
    from prompt_programs.choices import GROUP, _tags
    if len(options) > PARTS_MAX:
        return {}
    out: Dict[str, Dict[str, List[str]]] = {}
    facets = [*leaf.local_facets.items(), *([(GROUP, tuple(leaf.groups))] if leaf.groups else [])]
    for facet, names in facets:
        parts = {str(n): [o for o in options if str(n) in _tags(leaf, o, facet)] for n in names}
        parts = {n: os for n, os in parts.items() if os and not (leaf.plain and os == [leaf.plain])}
        if parts:
            out[facet] = parts
    return out


def pool_options(entry: Dict[str, Any], pins: Optional[Dict[str, Any]] = None, *, profile_id: Optional[str] = None,
                 project_id: Optional[int] = None, store: Optional[OptionStore] = None,
                 cfg: Optional[FluentSettings] = None, mine: Optional[Dict[str, List[str]]] = None,
                 edits: Optional[Dict[str, Dict[str, Any]]] = None,
                 zones: Optional[Dict[str, List[str]]] = None) -> Dict[str, Any]:
    """The options each generated pick draws from now: its seeds plus whatever has been
    generated, for the upstream values pinned (or drawn, when nothing upstream is pinned).
    A pick's own pins don't narrow what it shows. Never calls a model (an unseen pool is
    queued to fill, like any draw); `more` lists picks whose pools are still filling.
    `zones` (choices.expand) are the zones chosen per slot pick: its options are theirs, and
    `zones` in the answer holds every zone's options, for a free slot and for a bound pick
    its slot's words narrowed (choices.bound_zones)."""
    from prompt_programs.choices import bound_zones, free_zones
    out: Dict[str, List[str]] = {}
    more: List[str] = []
    vocab: Dict[str, Dict[str, Any]] = {}
    by_zone: Dict[str, Dict[str, List[str]]] = {}
    if not has_draws(entry):
        return {"options": out, "more": more, "vocab": vocab, "zones": by_zone}
    rt = runtime_for(entry, profile_id=profile_id, project_id=project_id, store=store, cfg=cfg, mine=mine,
                     edits=edits, zones=zones)
    chosen = dict(rt.options.zones)
    pins = {k: v for k, v in (pins or {}).items() if v}
    generated = [c["id"] for c in entry.get("choices") or [] if c.get("kind") == "pick" and c.get("source") != "list"]
    bound_cls = {c["id"]: c.get("cls") for c in entry.get("choices") or [] if c.get("cls")}
    listed = {c["id"]: c.get("options") for c in entry.get("choices") or [] if c.get("cls")}
    # A detail that starts left out (a hairstyle, a face's part) is drawn turned on to see its
    # options. A face shows its parts' options, not a list of its own.
    wholes = {str(c["part_of"]) for c in entry.get("choices") or [] if c.get("part_of")}
    quiet = {c["id"] for c in entry.get("choices") or [] if c.get("starts_off") and c["id"] not in wholes}

    def own_adds(cid: str) -> List[str]:   # options the user added in this choice's card
        return [str(x) for x in ((rt.options.edits.get(cid) or {}).get("add") or [])]
    def options_of(cid: str, others: Dict[str, Any], contexts: Optional[List[Any]] = None) -> List[str]:
        seen: List[str] = []
        for seed in range(POOL_DRAWS):
            try:
                res = _drawn(entry, 7919 * seed + 3, others, rt.options, {cid: {"on": True}} if cid in quiet else None)
            except ProgramError:
                continue
            if cid in (res.more_coming or []) and cid not in more:
                more.append(cid)
            for d in res.draws:
                if d.id == cid:
                    seen.extend(o for o in d.options if o not in seen)
            if contexts is not None:
                contexts.extend(rt.options.drawn_context(cid))
            rt.options.reset()
        return seen

    for cid in generated:
        others = {k: v for k, v in pins.items() if k != cid}
        contexts: List[Any] = []   # the context the pick's pool was drawn in, per draw (reach.py)
        seen = options_of(cid, others, contexts)
        free = free_zones(entry, cid)
        # Each zone's pool on its own, then back to the zones chosen. A slot with its kinds alone
        # has one zone, which the chooser doesn't name (choices.zone_titles): its options are its pool.
        if free is not None and len(free) > 1:
            for z in free:
                rt.options.zones = {**chosen, cid: [z]}
                by_zone.setdefault(cid, {})[z] = options_of(cid, others)[:60]
            rt.options.zones = chosen
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
            groups = list_groups(leaf, seen)
            if groups:
                vocab[cid]["groups"] = groups
            short = {o: leaf.short(o) for o in out[cid] if leaf.short(o) != o}
            if short:
                vocab[cid]["short"] = short
            looks = {o: leaf.look(o) for o in out[cid] if leaf.look(o)}
            if looks:
                vocab[cid]["looks"] = looks
            if bound_zones(entry, cid) is not None:
                # Kinds: what the slot's words narrowed the list to; instead: the rest, as reach's "any".
                keep = set(narrowed)
                by_zone[cid] = {"kinds": [o for o in seen if o in keep and o not in mine_here],
                                "instead": [o for o in seen if o not in keep and o not in mine_here
                                            and (leaf.value(o) is None or not leaf.value(o).opt_in)]}
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
    return {"options": out, "more": more, "vocab": vocab, "zones": by_zone}


__all__ = ["Runtime", "attach_filler", "list_groups", "pool_options", "program_context", "runtime_for", "start_options"]
