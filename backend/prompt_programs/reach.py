"""How far a list-bound choice reaches: what the user said, what fits their prompt, and the
rest of the list, for the picker's three settings ("Just Irish · Similar · Any").

Worked out from what the program and the vocabulary already hold, never from the words of
the values, and never with a model (the picker asks for it on every open):

- A choice set to a value the user stated (said=): their value; "similar" is the values the
  list itself groups with it (`similar_values`).
- A choice narrowed by the user's words (where=, narrowing): the narrowed subset fits; the
  rest of the list is beyond.
- A wide-open choice: what the context its pool is drawn in (vocab.py: descent, era, ...)
  leaves at full weight fits; the values it makes rare or leaves out are beyond. Only when
  that context is the same for every image: a context that moves with another choice's draw
  says nothing about the choice as a whole.

Each setting is a set of the options the picker shows, so the picker's ticks for it are
exactly what a run draws from. "Any" never holds the values drawn only when ticked one by
one (opt-in values, such as ages under 18), nor the user's own options (they stay as the
user left them, whatever the setting).
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from prompt_programs.vocab import Leaf

WORDS_MAX = 18   # longer narrowing words don't name a setting ("What fits" does)

# The grouping a list's "similar" values share, where its named parts together aren't one: a
# facet of the list, or None for a list whose parts say nothing about likeness (a room's size).
SIMILAR_BY: Dict[str, Optional[str]] = {
    "person.outfit.period": "period",
    "interior_space.any_room": None,
    "interior_space.bar": None,
    "interior_space.bathroom": None,
    "interior_space.bedroom": None,
    "interior_space.cafe_restaurant": None,
    "interior_space.kitchen": None,
    "interior_space.library_study": None,
    "interior_space.living_room": None,
    "interior_space.office": None,
    "interior_space.shop": None,
    "interior_space.workshop_studio": None,
}

# Declared groups for lists whose values carry none: (group, values). Kept here, not in the
# list's file, so declaring them changes no prepared program (the list files' bytes key them).
SIMILAR_GROUPS: Dict[str, Tuple[Tuple[str, Tuple[str, ...]], ...]] = {
    "person.build": (
        ("slight", ("slender", "petite", "lanky", "small-framed", "narrow-shouldered", "narrow-hipped",
                    "long-limbed")),
        ("heavy", ("stocky", "plus-size", "round-bellied", "broad-hipped", "large-framed", "barrel-chested")),
        ("strong", ("athletic", "muscular", "broad-shouldered", "broad-chested", "powerfully built")),
        ("height", ("tall", "short", "medium-height")),
        ("torso", ("long-waisted", "short-waisted", "straight-waisted")),
    ),
}


def _tags(leaf: Leaf, text: str, facet: str) -> Set[str]:
    v = leaf.value(text)
    t = v.tags.get(facet) if v is not None else None
    if t is None or t == "any":
        return set()
    return {str(x) for x in (t if isinstance(t, (list, tuple)) else [t])}


def similar_values(leaf: Leaf, said: str, options: Sequence[str]) -> List[str]:
    """The options the list groups with a stated value, the value first: those in its declared
    group (descent's groups, SIMILAR_GROUPS), else those sharing one of its parts on each of
    the list's named parts that tag it (hair color's shade, age's life stage, an outfit's style
    and coverage, a light's mood and source; SIMILAR_BY names the one to use instead, where
    those say little about likeness). Empty when the value isn't one of the list's, the list
    has no grouping, or the group is the value alone or most of the list (that isn't "similar")."""
    if leaf.value(said) is None:
        return []
    declared = dict(SIMILAR_GROUPS.get(leaf.id, ()))
    if declared:
        mine = {g for g, vals in declared.items() if said in vals}
        near = [o for o in options if any(o in declared[g] for g in mine)]
    elif any(v.group for v in leaf.values):
        g = leaf.value(said).group
        near = [o for o in options if g and getattr(leaf.value(o), "group", "") == g]
    else:
        facets = ([SIMILAR_BY[leaf.id]] if SIMILAR_BY[leaf.id] else []) if leaf.id in SIMILAR_BY else list(leaf.local_facets)
        want = {f: t for f in facets if (t := _tags(leaf, said, f))}
        near = [o for o in options if want and all(_tags(leaf, o, f) & t for f, t in want.items())]
    listed = [o for o in options if leaf.value(o) is not None]
    if len(near) < 2 or len(near) * 2 > len(listed):
        return []
    return [said, *[o for o in near if o != said]]


def reach_of(leaf: Leaf, options: Sequence[str], standby: Iterable[str], own: Iterable[str], *,
             said: str = "", narrowed: Optional[Sequence[str]] = None, words: str = "",
             contexts: Sequence[Tuple[Tuple[str, Tuple[str, ...]], ...]] = ()) -> Optional[Dict[str, Any]]:
    """A bound choice's settings for the picker, or None when it has only one (everything
    fits: the picker keeps its plain All row).

    `options`: what the picker lists, in order; `standby`: those drawn only once ticked one by
    one; `own`: the user's own options. `said`: their stated value; `narrowed`: the subset their
    words narrowed the list to; `contexts`: the context the choice's pool was drawn in, once per
    sample draw; `words`: the user's words the list was narrowed by, to name the setting.
    Returns {"said": [value]?, "fits": [...]?, "any": [...], "words"?}, each list in the
    options' order; "fits" holds the stated value too."""
    mine, held = set(own), set(standby)
    regular = [o for o in options if o not in mine and o not in held]
    if said and said in options:
        any_ = [o for o in options if o not in mine and (o not in held or o == said)]
        fits = [o for o in similar_values(leaf, said, regular) if o in any_]
        out: Dict[str, Any] = {"said": [said], "any": any_}
        if fits and len(fits) < len(any_):
            out["fits"] = fits
        return out if len(any_) > 1 else None
    if narrowed:
        keep = set(narrowed)
        fits = [o for o in options if o in keep and o not in mine]
        # What a tick on "Any" draws: the list's values, those drawn only one by one left out.
        any_ = [o for o in options if o not in mine and (o in keep or leaf.value(o) is None or not leaf.value(o).opt_in)]
        if not fits or len(fits) >= len(any_):
            return None
        short = " ".join(words.split())
        return {"fits": fits, "any": any_, **({"words": short} if 0 < len(short) <= WORDS_MAX else {})}
    distinct = {c for c in contexts}
    if len(distinct) != 1 or not next(iter(distinct)):
        return None
    low = leaf.reduced(regular, next(iter(distinct)))
    fits = [o for o in regular if o not in low]
    return {"fits": fits, "any": regular} if fits and len(fits) < len(regular) else None


__all__ = ["SIMILAR_BY", "SIMILAR_GROUPS", "reach_of", "similar_values"]
