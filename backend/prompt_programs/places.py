"""Where a person is from: a heritage seed's mix, given where the picture is set. Generic over
context tables (vocab/contexts/*.json, kinds.Table): a table weights one list, and the countries
table weights the human descent list; a pack's realms table may weight its elves' clans.

A heritage seed (variants.Seeds.descent) is drawn from

    P(value) = w * local(entry) + (1 - w) * global

- `global`: the list's own weights, normalized. For descent those are each world region's
  authored share (person/ethnicity.json `shares.region`: about the square root of its population)
  split among its heritages by tier weight (vocab.TIER_WEIGHTS), which the loader folds into the
  values' weights (vocab._shared); so how many values a region lists is not its weight.
- `local(entry)`: the entry's own shares (a country's heritages common there), with whatever they
  leave of 1 spread by the global prior.
- the entry is, of the table that weights the list (vocab.table_for), the first that applies: the
  one the slot's reading names (reader.py's place answer, an exact name or alias; w = the table's
  weight.prompt), the user's default place when the table is the user-default one (the
  `fluent.people_from` setting; w = weight.default), or none: the global prior alone.

A descent the words state narrows the list first, and the mix is renormalized within what is
left (with no local mass there, that is the global prior within it); a value the user picks
restricts it the same way (variants.Seeds.pinned). The mix holds the list's weights already, so it
replaces a heritage bank's own weights (weigh): multiplying would count them twice.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence, Tuple

FROM_PROMPT = 0.9      # the countries table's weight.prompt (vocab/contexts/countries.json), for reference
FROM_DEFAULT = 0.8     # its weight.default
ANYWHERE = "anywhere"  # the default place's value for none: the global prior alone
DESCENT = "person.ethnicity"


def _table(place: Optional[Dict[str, Any]] = None, list_id: str = DESCENT) -> Any:
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    tid = str((place or {}).get("table") or "")
    return vocab.tables.get(tid) if tid else (vocab.table_for(list_id) or vocab.user_table)


def global_prior(list_id: str = DESCENT) -> Dict[str, float]:
    """Each value's share with no place: the list's own weights, normalized (for descent: its
    region's share, split within it by tier weight)."""
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(list_id)
    if leaf is None:
        return {}
    mass = sum(v.weight for v in leaf.values) or 1.0
    return {v.text: v.weight / mass for v in leaf.values}


def local(code: str, table: Any = None) -> Dict[str, float]:
    """An entry's mix: its shares, and what they leave spread by the global prior. {} for a code
    the table doesn't have."""
    table = table if table is not None else _table()
    entry = table.entries.get(code) if table is not None else None
    if entry is None:
        return {}
    g = global_prior(table.weights)
    named = dict(entry.shares)
    rest = max(0.0, 1.0 - sum(named.values()))
    return {t: named.get(t, 0.0) + rest * p for t, p in g.items()}


def mix(place: Optional[Dict[str, Any]] = None, list_id: str = DESCENT) -> Dict[str, float]:
    """P(value) of a list for a place context ({"code", "from": "prompt" | "default", "table"?}),
    or the global prior for none. Sums to 1 over the whole list."""
    table = _table(place, list_id)
    lid = table.weights if table is not None and place else list_id
    g = global_prior(lid)
    code = str((place or {}).get("code") or "")
    src = str((place or {}).get("from") or "")
    w = (table.weight_prompt if src == "prompt" else table.weight_default if src == "default" else 0.0) if table else 0.0
    loc = local(code, table) if code and w else {}
    if not loc:
        return g
    return {t: w * loc.get(t, 0.0) + (1 - w) * p for t, p in g.items()}


def weigh(pairs: Sequence[Tuple[str, float]], place: Optional[Dict[str, Any]] = None,
          list_id: str = DESCENT) -> Tuple[Tuple[str, float], ...]:
    """A heritage bank's (value, weight) pairs weighted by their share of the mix instead, so a
    narrowed or picked subset draws the mix renormalized within it. The bank's own weights are the
    global prior's, which the mix already holds: multiplying would count them twice, so a pair
    keeps its weight only to say whether it is drawn at all. A value the mix gives nothing (none
    should) keeps a trace, so a subset is never emptied."""
    m = mix(place, list_id)
    out = tuple((t, m.get(t, 0.0) if w > 0 else 0.0) for t, w in pairs)
    return out if any(w > 0 for _, w in out) else tuple(pairs)


def default_place() -> Optional[str]:
    """The user's default place as a code of the user-default table; None when it is unset,
    "anywhere", or no longer a place the table has."""
    from prompt_programs.judge import settings
    from prompt_programs.vocab import vocabulary
    got = str(settings().people_from or "").strip()
    if not got or got.lower() == ANYWHERE:
        return None
    return got.upper() if got.upper() in vocabulary().places else None


def place_for(said: Any, default: Optional[str] = None, list_id: str = DESCENT) -> Optional[Dict[str, str]]:
    """A heritage list's place context: the entry the reading names exactly in the table that
    weights the list ({"code", "from": "prompt"}, with "table" when that isn't the user-default
    table), else the user's default place when that table is the user-default one ({"code",
    "from": "default"}), else None."""
    from prompt_programs.vocab import vocabulary
    table = vocabulary().table_for(list_id)
    if table is None:
        return None
    e = table.named(said) if isinstance(said, str) else None
    if e is not None:
        return {"code": e.code, "from": "prompt", **({} if table.user_default else {"table": table.id})}
    return {"code": default, "from": "default"} if default and table.user_default else None


def mark(place: Optional[Dict[str, Any]]) -> str:
    """A place context as part of a pool key ("JP@prompt", a pack table's "realms:thornmere@prompt");
    "" for none."""
    if not place or not place.get("code"):
        return ""
    return (f"{place['table']}:" if place.get("table") else "") + f"{place['code']}@{place['from']}"


def choices() -> list:
    """The places a user may pick as their default, by name: [{"code", "name"}]."""
    from prompt_programs.vocab import vocabulary
    return sorted(({"code": p.code, "name": p.name} for p in vocabulary().places.values()), key=lambda x: x["name"])


__all__ = ["ANYWHERE", "FROM_DEFAULT", "FROM_PROMPT", "choices", "default_place", "global_prior", "local", "mark", "mix",
           "place_for", "weigh"]
