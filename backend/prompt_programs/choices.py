"""What the user chose in the chooser, as the draw takes it.

The editor sends one object per choice (`promptOptions.program.choices`, and /pools and
/preview the same; stimma-plans VARIANTS_IMPL.md section 4):

    {"young_woman": {"values": ["freckled young woman with a short black bob"]},
     "young_woman#add": ["a young woman of my own"],
     "lighting": {"as_written": true},
     "camera": {"off": true},
     "person": {"seeds": {"descent": {"values": ["Korean"], "groups": {"region": ["East Asia"]}},
                          "gender": {"values": ["trans woman"]}}},
     "list1": {"values": ["autumn"]}}

`expand` turns it into what realize() and the pools read: for a slot, a variant_pools.Choice
(pinned variants, the user's own, as written, left out, picked seeds); for a user list, pins
(its ticked items) and edits (`off`, `add`). `{"any": true}` and `{}` are no choice. Choices the
prompt doesn't have (one from before an edit, an old detail id like `young_man.age`) are passed by.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from prompt_programs.variant_pools import Choice


class UnknownChoiceError(ValueError):
    """keep_choices named a choice the prepared prompt doesn't have."""


def _strings(v: Any) -> List[str]:
    return [str(x) for x in (v if isinstance(v, (list, tuple)) else [v]) if x is not None and str(x).strip()]


def expand(entry: Dict[str, Any], choices: Optional[Dict[str, Any]]
           ) -> Tuple[Dict[str, List[str]], Dict[str, Dict[str, Any]], Dict[str, Choice]]:
    """(pins, edits, chosen) for the chooser's choices on a prepared prompt: pins and edits for
    its user lists, a Choice per slot."""
    slots = {str(s.get("id")) for s in entry.get("slots") or []}
    lists = {str(p.get("id")) for p in entry.get("picks") or [] if p.get("source") == "list"}
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
    chosen: Dict[str, Choice] = {}
    for cid, ch in per.items():
        if cid in slots:
            c = Choice.of(ch)
            if c.to_dict() is not None or c.add:
                chosen[cid] = c
            continue
        if cid not in lists:
            continue
        if ch.get("add"):
            edits.setdefault(cid, {})["add"] = list(dict.fromkeys(ch["add"]))
        if ch.get("off"):
            edits.setdefault(cid, {})["off"] = True
            continue
        if ch.get("any"):
            continue
        values = _strings(ch.get("values") or [])
        if values:
            pins[cid] = list(dict.fromkeys(values))
    return pins, edits, chosen


def kept(entry: Dict[str, Any], keep: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """An agent's keep_choices ({choice: value or [values]}) as choices of values. A choice is
    named by its id (as results report it) or its label; UnknownChoiceError for one the
    prompt doesn't have."""
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
        cid = by_name.get(str(name)) or by_name.get(str(name).strip().lower())
        if cid is None:
            names = ", ".join(str(c.get("id")) for c in visible) or "none"
            raise UnknownChoiceError(f'"{name}" isn\'t a choice in this prompt. Its choices are: {names}.')
        values = [str(v) for v in (value if isinstance(value, (list, tuple)) else [value]) if v is not None and str(v) != ""]
        if values:
            out[cid] = {"values": values}
    return out


__all__ = ["UnknownChoiceError", "expand", "kept"]
