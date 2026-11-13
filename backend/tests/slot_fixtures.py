"""Fixture entries for tests, written in a short form:

    age = pick("age", cls="person.age_band", about="her age", label="Age")
    emit("A", age, "person at the beach", opt(", lit by", light))

Each `pick(...)` is one pick of a slot named by its id (its keyword arguments read as literals,
never run), and the `emit(...)` gives the prompt's order: text, picks, and opt(lead, pick) for
a pick whose lead goes with it. `entry_of(src)` is the prepared entry fill.py draws from;
`draw` and `discover` read it the way the tests did before the fill."""

from __future__ import annotations

import ast
import functools
from typing import Any, Dict, List, Optional

_ARGS = ("id", "options", "label")
_KEYS = {"label", "about", "phase", "source", "cls", "seed", "where", "said", "zones", "line", "added", "options",
         "shared"}


def _lit(node: ast.AST) -> Any:
    return ast.literal_eval(node)


@functools.lru_cache(maxsize=256)
def _parse(src: str) -> Dict[str, Any]:
    tree = ast.parse(src)
    picks: Dict[str, Dict[str, Any]] = {}
    var: Dict[str, str] = {}
    order: List[Any] = []
    for st in tree.body:
        if isinstance(st, ast.Assign) and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", "") == "pick":
            call = st.value
            kw = {k.arg: _lit(k.value) for k in call.keywords if k.arg in _KEYS}
            for name, a in zip(_ARGS, call.args):
                kw[name] = _lit(a)
            cid = str(kw.pop("id"))
            source = "added" if kw.pop("added", False) else kw.get("source") or ("text" if kw.get("said") else "added")
            p: Dict[str, Any] = {"id": cid, "kind": "pick", "label": kw.get("label") or cid.split(".")[-1].capitalize(),
                                 "about": str(kw.get("about") or ""), "phase": int(kw.get("phase") or 1), "source": source}
            if kw.get("options"):
                p["items"] = [str(o) for o in kw["options"]]
            for k in ("cls", "seed", "where", "said", "zones", "line"):
                if kw.get(k) not in (None, "", [], {}):
                    p[k] = kw[k]
            picks[cid] = p
            var[st.targets[0].id] = cid
        elif isinstance(st, ast.Expr) and isinstance(st.value, ast.Call) and getattr(st.value.func, "id", "") == "emit":
            for a in st.value.args:
                if isinstance(a, ast.Name):
                    order.append(("pick", var[a.id], ""))
                elif isinstance(a, ast.Call) and getattr(a.func, "id", "") == "opt":
                    lead = "".join(_lit(x) for x in a.args if not isinstance(x, ast.Name))
                    names = [x.id for x in a.args if isinstance(x, ast.Name)]
                    order.append(("pick", var[names[0]], lead))
                else:
                    order.append(("text", str(_lit(a)), ""))
        else:
            raise ValueError(f"not a fixture statement: {ast.unparse(st)}")
    return {"picks": picks, "order": order}


def entry_of(src: str, prompt: str = "", **extra: Any) -> Dict[str, Any]:
    """The entry a fixture program stands for: one slot per pick, in the emit's order."""
    from prompt_programs.fill import COLORS, choice_options, template_text
    from prompt_programs.vocab import vocabulary
    got = _parse(src)
    segments: List[Dict[str, Any]] = []
    slots: List[Dict[str, Any]] = []
    picks: List[Dict[str, Any]] = []
    for kind, value, lead in got["order"]:
        if kind == "text":
            segments.append({"kind": "text", "text": f" {value} ", "span": [0, 0], "line": 1})
            continue
        p = dict(got["picks"][value])
        if lead:
            segments.append({"kind": "text", "text": f" {lead}", "span": [0, 0], "line": 1})
        segments.append({"kind": "slot", "text": f"<{value}>", "words": value, "span": [0, 0], "line": 1})
        p["slot"] = value
        made = [p]
        leaf = vocabulary().resolve(p.get("cls")) if p.get("cls") and p.get("source") != "list" else None
        if leaf is not None and leaf.slots and vocabulary().get(leaf.slots) is not None:
            made.append({"id": value + COLORS, "kind": "pick", "label": "Colors", "phase": p["phase"],
                         "source": p["source"], "cls": leaf.slots, "slot": value, "follows": value,
                         "about": f"the colours of {p['about'] or p['label']}"})
        slots.append({"id": value, "n": len(slots) + 1, "kind": "one", "label": p["label"], "words": value,
                      "state": "ready", "lead": lead, "details": [m["id"] for m in made],
                      "form": {"kind": "one", "id": value}, **({"zones": p["zones"]} if p.get("zones") else {})})
        picks += made
    choices = []
    for p in picks:
        c = {k: v for k, v in p.items() if k not in ("items",)}
        c["options"] = choice_options(p)
        choices.append(c)
    entry = {"key": "k", "prompt": prompt, "mode": "prose", "segments": segments, "slots": slots, "lists": [],
             "picks": picks, "choices": choices}
    entry["template"] = template_text(entry)
    entry["program"] = src   # the fixture it was made from: draw(entry["program"]) draws this entry
    entry.update(extra)
    _made[src] = entry
    return entry


_made: Dict[str, Dict[str, Any]] = {}


def discover(src: str) -> Dict[str, Any]:
    e = entry_of(src)
    return {"choices": e["choices"], "example": None, "groups": []}


def draw(src_or_entry: Any, seed: int, pins: Optional[Dict[str, Any]] = None, loras: Any = None, params: Any = None,
         fixed: Optional[Dict[str, Any]] = None, edits: Optional[Dict[str, Any]] = None, *, options: Any = None):
    from prompt_programs.fill import fill
    if isinstance(src_or_entry, str):
        entry = _made.get(src_or_entry) or entry_of(src_or_entry)
    else:
        entry = src_or_entry
    return fill(entry, seed, pins, fixed, edits, options=options)


def run(src: str, seed: int, *a: Any, **kw: Any):
    """A draw from the lists themselves, with no option store."""
    from prompt_programs.fluent import runtime_for
    entry = _made.get(src) or entry_of(src)
    return draw(entry, seed, options=runtime_for(entry, store=None, mine={}).options)


def expand_people(src: str) -> str:
    """Fixtures have no person(): a person is a reading (test_slots_fill)."""
    return src


def analyze(src: str, *a: Any, **kw: Any) -> Any:
    raise NotImplementedError("fixtures have no program analysis")
