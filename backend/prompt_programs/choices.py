"""What the user chose in a slot program's chooser, as the draw engine takes it.

The editor sends one object per choice (`promptOptions.program.choices`, and /pools and
/preview the same):

    {"elderly_african_man.age": {"values": ["70-year-old"]},
     "elderly_african_man.hair_color": {"groups": {"color_family": ["gray"]}},
     "pet": {"zones": ["kinds", "instead"]},
     "list1": {"off": true},
     "pet#add": ["three-legged greyhound"]}

`expand` turns it into the pins, edits and zones realize() and pool_options() read:

- `values`: option texts, pinned.
- `groups`: {facet: [parts]} on the choice's list: the list's values tagged with one of the
  parts on every facet named (the facet "group" names the list's declared groups), pinned
  beside any values.
- `zones`: a free slot's zones are drawn from together (options.GeneratedOptions); a bound
  pick narrowed by the slot's words has two zones of its list, `kinds` (the narrowed subset)
  and `instead` (the rest, values drawn only when picked one by one left out), and choosing
  `instead` pins the values of the zones chosen.
- `off`: the choice is left out (with its lead). `add` (or `<id>#add`): the user's own options.

"Any" (`{"any": true}`) and `zones == ["kinds"]` alone are the default draw, so they are
stored as no choice: a pin draws differently from the default (no context weighting).
Choices the program doesn't have (a choice from before an edit) are passed by.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prompt_programs.vocab import Leaf, vocabulary

PARTS_MAX = 400   # a longer list has no zones or groups on the wire (fluent.PARTS_MAX)
GROUP = "group"   # the facet name for a list's declared groups


class UnknownChoiceError(ValueError):
    """keep_choices named a choice the prepared prompt doesn't have."""


def _choice(entry: Dict[str, Any], cid: str) -> Optional[Dict[str, Any]]:
    return next((c for c in entry.get("choices") or [] if c.get("id") == cid), None)


def free_zones(entry: Dict[str, Any], cid: str) -> Optional[Dict[str, List[str]]]:
    """A free slot's zones and their seeds, as its reading gave them."""
    return next((s["zones"] for s in entry.get("slots") or [] if s.get("id") == cid and s.get("zones")), None)


def bound_zones(entry: Dict[str, Any], cid: str) -> Optional[Tuple[List[str], List[str]]]:
    """(kinds, instead) for a bound pick narrowed by its slot's words, from its list: the
    narrowed subset, and the rest of the list but the values drawn only when picked one by
    one. None for a pick its slot's words didn't narrow, or a long list."""
    c = _choice(entry, cid)
    leaf = vocabulary().get((c or {}).get("cls"))
    kinds = list((entry.get("filters") or {}).get(cid) or [])
    if leaf is None or not kinds or not str((entry.get("slot_words") or {}).get(cid) or "").strip() \
            or len(leaf.values) > PARTS_MAX:
        return None
    keep = set(kinds)
    instead = [v.text for v in leaf.eligible() if v.text not in keep and not v.opt_in]
    return (kinds, instead) if instead else None


def zone_titles(entry: Dict[str, Any], cid: str) -> Optional[List[Dict[str, str]]]:
    """A choice's zones as the chooser names them, or None for a choice with one zone."""
    words = str((entry.get("slot_words") or {}).get(cid) or "").strip()
    if free_zones(entry, cid) is not None:
        return [{"id": "kinds", "title": f"Kinds of {words}"}, {"id": "instead", "title": f"Instead of {words}"}]
    if bound_zones(entry, cid) is not None:
        return [{"id": "kinds", "title": words[:1].upper() + words[1:]}, {"id": "instead", "title": f"Instead of {words}"}]
    return None


def _tags(leaf: Leaf, text: str, facet: str) -> set:
    v = leaf.value(text)
    if v is None:
        return set()
    if facet == GROUP:
        return {v.group} if v.group else set()
    t = v.tags.get(facet)
    return {str(x) for x in (t if isinstance(t, (list, tuple)) else [t])} if t not in (None, "any") else set()


def group_values(leaf: Leaf, groups: Dict[str, Any]) -> List[str]:
    """The list's values in one of the parts named on every facet named."""
    want = {str(f): {str(p) for p in (ps if isinstance(ps, list) else [ps])} for f, ps in (groups or {}).items()}
    want = {f: ps for f, ps in want.items() if ps}
    if not want:
        return []
    return [v.text for v in leaf.values if all(_tags(leaf, v.text, f) & ps for f, ps in want.items())]


def _strings(v: Any) -> List[str]:
    return [str(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if x is not None and str(x).strip()]


def expand(entry: Dict[str, Any], choices: Optional[Dict[str, Any]]
           ) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Any]], Dict[str, List[str]]]:
    """(pins, edits, zones) for the chooser's choices on a prepared slot program."""
    known = {str(c.get("id")) for c in entry.get("choices") or []}
    per: Dict[str, Dict[str, Any]] = {}
    for key, value in (choices or {}).items():
        key = str(key)
        if key.endswith("#add"):
            per.setdefault(key[:-4], {}).setdefault("add", []).extend(_strings(value))
        elif isinstance(value, dict):
            got = per.setdefault(key, {})
            got.update({k: v for k, v in value.items() if k != "add"})
            got.setdefault("add", []).extend(_strings(value.get("add") or []))
    pins: Dict[str, List[str]] = {}
    edits: Dict[str, Dict[str, Any]] = {}
    zones: Dict[str, List[str]] = {}
    vocab = vocabulary()
    for cid, ch in per.items():
        if cid not in known:
            continue
        if ch.get("add"):
            edits.setdefault(cid, {})["add"] = list(dict.fromkeys(ch["add"]))
        if ch.get("off"):
            edits.setdefault(cid, {})["off"] = True
            continue
        if ch.get("any"):
            continue
        values = _strings(ch.get("values") or [])
        leaf = vocab.get((_choice(entry, cid) or {}).get("cls"))
        if leaf is not None and isinstance(ch.get("groups"), dict):
            values += group_values(leaf, ch["groups"])
        chosen = list(dict.fromkeys(_strings(ch.get("zones") or [])))
        free, bound = free_zones(entry, cid), bound_zones(entry, cid)
        if free is not None:
            chosen = [z for z in chosen if z in free]
            if chosen and chosen != ["kinds"]:
                zones[cid] = chosen
        elif bound is not None and "instead" in chosen:
            values += (bound[0] if "kinds" in chosen else []) + bound[1]
        if values:
            pins[cid] = list(dict.fromkeys(values))
    return pins, edits, zones


def kept(entry: Dict[str, Any], keep: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """An agent's keep_choices ({choice: value or [values]}) as choices of values. A choice is
    named by its id (as results report it) or its label; UnknownChoiceError for one the
    prompt doesn't have."""
    from prompt_programs.runtime import current_id
    visible = [c for c in entry.get("choices") or [] if not c.get("hidden")]
    by_name: Dict[str, str] = {}
    for c in visible:
        by_name.setdefault(str(c.get("id")), str(c.get("id")))
    for c in visible:
        by_name.setdefault(str(c.get("id")).lower(), str(c.get("id")))
        if c.get("label"):
            by_name.setdefault(str(c["label"]).strip().lower(), str(c.get("id")))
    out: Dict[str, Any] = {}
    for name, value in (keep or {}).items():
        cid = by_name.get(str(name)) or by_name.get(str(name).strip().lower()) or by_name.get(current_id(name))
        if cid is None:
            names = ", ".join(str(c.get("id")) for c in visible) or "none"
            raise UnknownChoiceError(f'"{name}" isn\'t a choice in this prompt. Its choices are: {names}.')
        values = [str(v) for v in (value if isinstance(value, (list, tuple)) else [value]) if v is not None and str(v) != ""]
        if values:
            out[cid] = {"values": values}
    return out


__all__ = ["GROUP", "UnknownChoiceError", "bound_zones", "expand", "free_zones", "group_values", "kept", "zone_titles"]
