"""Where a person is from: their descent seed's mix, given where the picture is set.

A person's descent seed (variants.Seeds.descent) is drawn from

    P(heritage) = w * local(place) + (1 - w) * global

- `global`: an equal share for each world region of the descent list (its `region` facet),
  split among the heritages in it by their tier weights (vocab.TIER_WEIGHTS: a small people is
  `plausible`, drawn about a third as often as a large one beside it), so how many values a
  region lists is not its weight.
- `local(place)`: the place's own shares (vocab/places.json: the heritages common there), with
  whatever they leave of 1 spread by the global prior.
- `place` is a country, from the first that applies: the prompt's setting, which the slot's
  reading names (reader.py, `person.place`: "a market in Lagos" gives "Nigeria"; w =
  FROM_PROMPT); the user's default place, the `fluent.people_from` setting (w = FROM_DEFAULT);
  or none, which is the global prior alone.

A reading's place counts only when it is exactly a name or alias in the table, case aside: code
matches no near names and reads nothing else. A descent the words state narrows the list first,
and the mix is renormalized within what is left (with no local mass there, that is the global
prior within it); a descent the user picks restricts it the same way (variants.Seeds.pinned).
The mix holds the tier weights already, so it replaces a descent bank's own weights (weigh).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

FROM_PROMPT = 0.8      # w when the prompt says where the picture is set
FROM_DEFAULT = 0.5     # w when only the user's default place applies
ANYWHERE = "anywhere"  # the default place's value for none: the global prior alone
DESCENT = "person.ethnicity"
REGION = "region"

WEIGHTS = {"prompt": FROM_PROMPT, "default": FROM_DEFAULT}


def global_prior() -> Dict[str, float]:
    """Each heritage's share with no place: every region equal, split within it by tier weight."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(DESCENT)
    if leaf is None:
        return {}
    by: Dict[str, list] = {}
    for v in leaf.values:
        region = (v.tags.get(REGION) or ("",))[0]
        by.setdefault(str(region), []).append((v.text, v.weight))
    out: Dict[str, float] = {}
    for vs in by.values():
        mass = sum(w for _, w in vs) or 1.0
        out.update({t: w / mass / len(by) for t, w in vs})
    return out


def local(code: str) -> Dict[str, float]:
    """A place's mix: its shares, and what they leave spread by the global prior. {} for a code
    the table doesn't have."""
    from prompt_programs.vocab import vocabulary
    place = vocabulary().places.get(code)
    if place is None:
        return {}
    g = global_prior()
    named = dict(place.shares)
    rest = max(0.0, 1.0 - sum(named.values()))
    return {t: named.get(t, 0.0) + rest * p for t, p in g.items()}


def mix(place: Optional[Dict[str, Any]] = None) -> Dict[str, float]:
    """P(heritage) for a place context ({"code", "from"}: from "prompt" or "default"), or the
    global prior for none. Sums to 1 over the whole descent list."""
    g = global_prior()
    code = str((place or {}).get("code") or "")
    w = WEIGHTS.get(str((place or {}).get("from") or ""), 0.0)
    loc = local(code) if code and w else {}
    if not loc:
        return g
    return {t: w * loc.get(t, 0.0) + (1 - w) * p for t, p in g.items()}


def weigh(pairs: Sequence[Tuple[str, float]], place: Optional[Dict[str, Any]] = None) -> Tuple[Tuple[str, float], ...]:
    """A descent bank's (heritage, weight) pairs weighted by their share of the mix instead, so a
    narrowed or picked subset draws the mix renormalized within it. The bank's own weights are the
    tier weights, which the mix already holds: multiplying would count the tier twice, so a pair
    keeps its weight only to say whether it is drawn at all. A heritage the mix gives nothing
    (none should) keeps a trace, so a subset is never emptied."""
    m = mix(place)
    out = tuple((t, m.get(t, 0.0) if w > 0 else 0.0) for t, w in pairs)
    return out if any(w > 0 for _, w in out) else tuple(pairs)


def default_place() -> Optional[str]:
    """The user's default place as a table code; None when it is unset, "anywhere", or no longer
    a place the table has."""
    from prompt_programs.judge import settings
    from prompt_programs.vocab import vocabulary
    got = str(settings().people_from or "").strip()
    if not got or got.lower() == ANYWHERE:
        return None
    return got.upper() if got.upper() in vocabulary().places else None


def place_for(said: Any, default: Optional[str] = None) -> Optional[Dict[str, str]]:
    """A person's place context: the reading's place when it names one exactly ({"code", "from":
    "prompt"}), else the default place ({"code", "from": "default"}), else None."""
    from prompt_programs.vocab import vocabulary
    p = vocabulary().place_named(said) if isinstance(said, str) else None
    if p is not None:
        return {"code": p.code, "from": "prompt"}
    return {"code": default, "from": "default"} if default else None


def mark(place: Optional[Dict[str, Any]]) -> str:
    """A place context as part of a pool key ("JP@prompt"); "" for none."""
    return f"{place['code']}@{place['from']}" if place and place.get("code") else ""


def choices() -> list:
    """The places a user may pick as their default, by name: [{"code", "name"}]."""
    from prompt_programs.vocab import vocabulary
    return sorted(({"code": p.code, "name": p.name} for p in vocabulary().places.values()), key=lambda x: x["name"])


__all__ = ["ANYWHERE", "FROM_DEFAULT", "FROM_PROMPT", "choices", "default_place", "global_prior", "local", "mark", "mix",
           "place_for", "weigh"]
