"""What a slot's variants are seeded with: its reading's lists, narrowed by the slot's words.

A slot's reading (reader.py) says what it is; `plan` turns that into the vocabulary lists that
seed its writes (variants.Seeds), each with the words that narrow it, by its kind's draw rules
(vocab/kinds/<kind>.json `draws`, kinds.DrawRule): which list plays which role (heritage, who,
age, core, each, idea), chosen by which answers of the reading, narrowed by which words. A person,
an animal, a camera and a light are kinds written that way; a pack adds others. The engine's own
two kinds stay here:

- a slot bound to one list (`list`): that list, narrowed by its words, one value per variant as
  its core;
- a free slot: the lists the reader names for it, as ideas.

`narrow_seeds` answers every plan's narrowing with the words-only question (narrow.subset:
shared across prompts, cached once), reads what the prompt states of the scene for lists held
for a setting (a light that places the scene outdoors), the heritage's place context (the
context table that weights its list, places.py), and whether the person may be under 18 (their
age, a user list's ages on their line, the age of whoever a list slot is about). The answers are
kept in the entry (`entry["seeds"][slot id]`); `seeds_of` builds the writer's Seeds from them. A
narrowing not asked yet holds that slot's first write (`entry["seeds_pending"]`; a slot that
can't be about a person's age shows one unseeded turn meanwhile, fluent.early_job); one that
failed or keeps nothing drops that list's seeds, never the slot.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs import variants as V

log = get_logger(__name__)

SEEDS_VERSION = "seeds-3"   # seeds-3: kinds and their draw rules are vocabulary data; a heritage's place is its table's. seeds-2: groups, heritage, scene-narrowed clothes, hairstyle and light

# A draw rule's role as the bank records it (the roles' older names, which stored records and the picker use).
BANK_ROLE = {"heritage": "descent", "who": "gender", "age": "age", "core": "core", "each": "each", "idea": "idea"}


class ReadingError(ValueError):
    """A reading its seeds can't be planned from (the reader checks for these before it caches)."""


def _leaf(lid: Any) -> Any:
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(lid) if isinstance(lid, str) else None
    if leaf is None:
        raise ReadingError(f"{lid!r} is not a list")
    return leaf


def _answer(got: Dict[str, Any], kind: Any, key: str) -> Any:
    """A reading's answer to one of its kind's questions, its default when it gives none."""
    q = kind.question(key) if kind is not None else None
    v = got.get(key)
    if q is not None and q.type == "choice":
        return v if isinstance(v, str) and v else q.default
    return v if v is not None else ""


def _holds(got: Dict[str, Any], kind: Any, cond: Dict[str, Any], every: bool) -> bool:
    """Whether a rule's when (every condition) or unless (any) holds for a reading. A condition is
    {key: [answers]} (a list answer: any of its items) or {key: "answered"}. Structure only: the
    reading's answers, never the slot's words."""
    def one(key: str, want: Any) -> bool:
        v = _answer(got, kind, key)
        if want == "answered":
            from prompt_programs.variants import _answered
            return _answered(v)
        wants = {str(x) for x in (want if isinstance(want, (list, tuple)) else [want])}
        items = v if isinstance(v, (list, tuple)) else [v]
        return bool(wants & {str(x) for x in items})
    if not cond:
        return every
    got_ = [one(str(k), w) for k, w in cond.items()]
    return all(got_) if every else any(got_)


def _phrase(spec: Any, stated: Dict[str, str], words: str) -> str:
    if spec == "words":
        return words
    if not isinstance(spec, dict):
        return ""
    said = stated.get(str(spec.get("stated") or ""), "")
    if spec.get("or") == "words":
        return said or words
    if spec.get("join") == "words":
        # the stated words read with the slot's words, unless they are in them already ("young woman")
        return words if not said or said.lower() in words.lower() else f"{said}, {words}"
    return said


def _rule_lists(rule: Any, kind: Any, got: Dict[str, Any], vary: Sequence[str]) -> List[str]:
    """The lists a draw rule names for a reading: an id; the list an answer names (or its
    default); a field of the chosen option (a sort of being's heritage list); a detail's list (only
    when it varies, or nothing is said to vary); each varied detail's list, in the reading's order."""
    lst = rule.list
    if isinstance(lst, str):
        return [lst]
    if "answer" in lst:
        q = kind.question(str(lst["answer"]))
        v = str(got.get(lst["answer"]) or "")
        if q is not None and v in q.also:
            return []
        v = v or str(lst.get("default") or "")
        return [v] if v else []
    if "option" in lst:
        q = kind.question(str(lst["option"]))
        o = q.option(str(_answer(got, kind, q.key))) if q is not None else None
        v = getattr(o, str(lst.get("field") or "heritage"), "") if o is not None else ""
        return [v] if v else []
    if "detail" in lst:
        d = kind.details.get(str(lst["detail"]))
        if d is None or (vary and d.name not in vary):
            return []
        return [d.list]
    if lst.get("varied"):
        return [kind.details[d].list for d in vary if d in kind.details]
    return []


def kind_plan(kind: Any, reading: Dict[str, Any], words: str) -> Dict[str, Any]:
    """A reading of a declared kind as banks, by the kind's draw rules in order."""
    got = reading.get(kind.id) if isinstance(reading.get(kind.id), dict) else {}
    noun = str(got.get("noun") or kind.noun_default or words)
    stated = {str(k): str(v) for k, v in (got.get("stated") or {}).items() if str(v).strip()}
    vary = [str(d) for d in got.get("vary") or []]
    banks: List[Dict[str, Any]] = []
    heritage_key = ""
    for rule in kind.draws:
        if not _holds(got, kind, rule.when, True) or _holds(got, kind, rule.unless, False):
            continue
        for lid in _rule_lists(rule, kind, got, vary):
            if any(b["role"] == BANK_ROLE[rule.role] and b["list"] == lid for b in banks):
                continue   # one bank per list and role: a pack's rule and the reader's choice may name the same list
            where = {}
            for f, w in rule.where.items():
                v = _answer(got, kind, str(w["answer"])) if isinstance(w, dict) else w
                if v:
                    where[f] = v
            about = rule.about.replace("{noun}", noun).replace("{words}", words)
            extra = {k: v for k, v in (("label", rule.label), ("say", rule.say), ("show", rule.show))
                     if rule.role in ("who", "each") and v}
            _add(banks, BANK_ROLE[rule.role], lid, _phrase(rule.phrase, stated, words), about, where or None,
                 age=rule.role == "age", scene=rule.scene, extra=extra)
            if rule.role == "heritage" and isinstance(rule.phrase, dict):
                heritage_key = str(rule.phrase.get("stated") or "")
    said = {q.key: str(got.get(q.key) or "").strip() for q in kind.questions if q.type == "context"}
    answers = {q.key: got[q.key] for q in kind.questions if q.key in got and q.type in ("choice", "words", "part", "list")}
    return {"kind": kind.id, "banks": banks, "stated_descent": bool(heritage_key and stated.get(heritage_key)),
            "answers": answers, **({"said": {k: v for k, v in said.items() if v}} if any(said.values()) else {}),
            **({"people": answers["people"]} if str(answers.get("people") or "") not in ("", "one") else {})}


def _add(banks: List[Dict[str, Any]], role: str, lid: str, phrase: str = "", about: str = "",
         where: Optional[Dict[str, str]] = None, age: bool = False, scene: bool = False,
         extra: Optional[Dict[str, Any]] = None) -> None:
    leaf = _leaf(lid)
    if where:
        where = {f: p for f, p in where.items() if p in leaf.local_facets.get(f, ()) or f in leaf.facets}
    banks.append({"role": role, "list": leaf.id, "phrase": phrase.strip(), "about": about,
                  **({"where": where} if where else {}), **({"age": True} if age else {}),
                  **({"scene": True} if scene else {}), **(extra or {})})


def plan(reading: Dict[str, Any], words: str = "") -> Dict[str, Any]:
    """The lists a reading seeds from: {"kind", "banks": [{"role", "list", "phrase", "about",
    "where", "age"}], "stated_descent", "answers"}. role: descent (the heritage role), gender (who),
    age, core, each or idea. phrase: the words that narrow it ("" for the whole list). where: a
    facet filter ({"presentation": "feminine"}). age: read with the minors rules in its line.
    ReadingError for a reading that names a list there isn't. Plain data, no model."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    kind = reading.get("kind")
    if kind not in vocab.kind_names():
        raise ReadingError(f"kind {kind!r} is not one of {vocab.kind_names()}")
    got = reading.get(kind) if isinstance(reading.get(kind), dict) else {}
    words = words or str(reading.get("words") or "")
    if vocab.kind(kind) is not None:
        return kind_plan(vocab.kind(kind), reading, words)
    banks: List[Dict[str, Any]] = []
    if kind == "list":
        p = got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else ""
        _add(banks, "core", str(got.get("list")), words, str(got.get("about") or words), {"presentation": p} if p else None)
        return {"kind": kind, "banks": banks}
    # Narrowed by the words like any other list: "sports car" keeps the kinds of sports car of a
    # road vehicle list, not a tractor or a city bus (a seed that contradicts the words sends the
    # writer arguing with itself). A list the words say nothing about keeps every value.
    about = str(got.get("about") or words)
    for lid in (got.get("lists") or [])[:3]:
        try:
            _add(banks, "idea", str(lid), words, about)
        except ReadingError:
            continue   # a list the vocabulary no longer has
    return {"kind": kind, "banks": banks}


def seeds_of(record: Dict[str, Any]) -> V.Seeds:
    """The writer's seeds from a slot's narrowed plan (entry["seeds"][slot id])."""
    from prompt_programs.vocab import vocabulary
    banks = record.get("banks") or []
    stated = record.get("stated") or None
    minor = tuple(record.get("minor") or ())

    def narrowed(b: Dict[str, Any]) -> Optional[List[str]]:
        n = b.get("narrowed")
        return list(n) if isinstance(n, list) else None
    kind = vocabulary().kind(record.get("kind"))
    if kind is not None:
        by = {b["role"]: b for b in banks if b["role"] in ("descent", "gender", "age")}
        age = by.get("age")
        return V.kind_seeds(
            kind, heritage=(by["descent"]["list"], narrowed(by["descent"])) if "descent" in by else None,
            stated_descent=bool(record.get("stated_descent")),
            who=(by["gender"]["list"], narrowed(by["gender"])) if "gender" in by else None,
            ages=narrowed(age) if age is not None and age.get("narrowed") is not None else None, age_role=age is not None,
            ideas=[(b["list"], narrowed(b)) for b in banks if b["role"] == "idea"],
            cores=[(b["list"], narrowed(b)) for b in banks if b["role"] == "core"],
            each=[(b, narrowed(b)) for b in banks if b["role"] == "each"],
            stated=stated, minor=minor,
            answers=record.get("answers") or ({"people": record["people"]} if record.get("people") else {}),
            place=record.get("place") if isinstance(record.get("place"), dict) else None)
    cores = [b for b in banks if b["role"] == "core"]
    lists = [(b["list"], narrowed(b)) for b in (cores or banks)]
    return V.list_seeds(lists, single=bool(cores) and len(lists) == 1, minor=minor, stated=stated)


def age_basis(record: Optional[Dict[str, Any]]) -> Tuple[Optional[List[str]], Tuple[str, ...]]:
    """(fits, minor) of a person's age from their narrowed plan: what their age narrowing kept
    (None while it isn't there or when it failed: every adult age) and the ages under 18 the
    minors rules already allow them (record["minor"]). The same ages seeds_of gives the writer,
    so a picked stage or year always has ages to seed."""
    record = record if isinstance(record, dict) else {}
    age = next((b for b in record.get("banks") or [] if b.get("role") == "age"), None)
    fits = age.get("narrowed") if age is not None and isinstance(age.get("narrowed"), list) else None
    return fits, tuple(record.get("minor") or ())


def age_choices(record: Optional[Dict[str, Any]]) -> Dict[str, List[str]]:
    """The life stages a person's age may be picked from, with their ages (variants.age_stages)."""
    return V.age_stages(*age_basis(record))


# --------------------------------------------------------------------------- narrowing, in the background

def _people_like(kind: Any) -> bool:
    """A kind seeded with a heritage, a who value or an age (a person): its age is read with the
    minors rules (kinds.Kind.people_like)."""
    from prompt_programs.vocab import vocabulary
    k = vocabulary().kind(kind)
    return bool(k is not None and k.people_like)


def _contexts(entry: Dict[str, Any]) -> Dict[str, str]:
    """Per slot (by id), its line with the prompt's comment lines: what an age or a setting said
    there is read in. A reading kept through an edit is read in what it was read in (its seen)."""
    lines = str(entry.get("prompt") or "").split("\n")
    notes = [str(sg.get("text") or "").strip() for sg in entry.get("segments") or [] if sg.get("kind") == "comment"]
    out: Dict[str, str] = {}
    for s in entry.get("slots") or []:
        seen = s.get("seen")
        if isinstance(seen, dict):
            out[s["id"]] = "\n".join(dict.fromkeys([*(str(t).strip() for t in seen.get("notes") or []),
                                                    str(seen.get("line") or "").strip()]))
        elif isinstance(s.get("line"), int) and 0 < s["line"] <= len(lines):
            out[s["id"]] = "\n".join(dict.fromkeys([*notes, lines[s["line"] - 1].strip()]))
    return out


def _scene_givers(leaves: Sequence[Any]) -> List[Any]:
    """The lists that read what a prompt states of the scene for the facets these lists take."""
    from prompt_programs.vocab import vocabulary
    vocab = vocabulary()
    takes = {f for lf in leaves for f in lf.takes if vocab.scope(f) == "scene"}
    return sorted((g for g in vocab.leaves.values() if g.stated and set(g.gives) & takes), key=lambda g: g.id)


async def narrow_seeds(entry: Dict[str, Any], cache: Any, ask: Any, project_id: Optional[int] = None,
                       seconds: float = 180.0) -> None:
    """Narrow every ready slot's seed lists (plan) into entry["seeds"], and list the slots whose
    narrowing isn't all in yet in entry["seeds_pending"]. `ask=None` reads the cache only. A
    question asked and failed, or past `seconds`, drops that list's seeds (an age: no age seeds,
    adults), never the slot. Never raises."""
    from prompt_programs.narrow import subset
    from prompt_programs.places import default_place, place_for
    from prompt_programs.vocab import AGE_LIST, minor_ages, tags_match, vocabulary
    vocab = vocabulary()
    try:
        home = default_place()
    except Exception:   # no settings (scripts): no default place
        home = None
    readings = {r.get("n"): r for r in (entry.get("readings") or {}).get("slots") or [] if isinstance(r, dict)}
    contexts = _contexts(entry)
    jobs: Dict[Tuple[str, str, str, str], "asyncio.Future[Optional[List[str]]]"] = {}

    def job(lid: str, phrase: str, about: str = "", prompt: str = "") -> "asyncio.Future[Optional[List[str]]]":
        k = (lid, phrase.strip().lower(), about, prompt)
        if k not in jobs:
            jobs[k] = asyncio.ensure_future(subset(vocab.leaves[lid], phrase, cache, ask, project_id, about, k[3],
                                                   scene=bool(prompt) and lid != AGE_LIST))
        return jobs[k]

    plans: Dict[str, Dict[str, Any]] = {}
    asks: Dict[str, List[Tuple[Dict[str, Any], "asyncio.Future"]]] = {}
    scene: Dict[str, List[Tuple[Any, "asyncio.Future"]]] = {}
    list_ages: Dict[str, List["asyncio.Future"]] = {}
    about_ages: Dict[str, "asyncio.Future"] = {}
    for s in entry.get("slots") or []:
        r = readings.get(s.get("n"))
        if s.get("state") != "ready" or s.get("degraded") or r is None:
            continue
        try:
            p = plan(r, s["words"])
        except ReadingError as e:
            log.info(f"[seeds] {s['words']!r} has nothing to seed from: {e}")
            continue
        plans[s["id"]] = p
        ctx = contexts.get(s["id"], s["words"])
        asks[s["id"]] = [(b, job(b["list"], b["phrase"], b["about"], ctx if b.get("age") or b.get("scene") else ""))
                         for b in p["banks"] if b["phrase"]]
        givers = _scene_givers([vocab.leaves[b["list"]] for b in p["banks"]])
        scene[s["id"]] = [(g, job(g.id, ctx, f"the {g.label.lower()} of the scene")) for g in givers]
        if _people_like(p["kind"]):
            # A user list on the person's line that may hold an age under 18 ({8-year-old|30-year-old}):
            # the person may be under 18 (MINORS_POLICY.md); each value is read on the age list.
            for lst in entry.get("lists") or []:
                if lst.get("line") == s.get("line"):
                    list_ages.setdefault(s["id"], []).extend(
                        job(AGE_LIST, str(v), "the age of the person", ctx) for v in lst.get("items") or [] if str(v).strip())
        elif any(b["list"].startswith(("person.", "clothing.")) for b in p["banks"]):
            # A list slot about someone ("a little girl in <outfit>"): read whoever it is about's age.
            about_ages[s["id"]] = job(AGE_LIST, ctx, "the age of the person this part is about", ctx)
    if not plans:
        entry["seeds"], entry["seeds_pending"] = {}, []
        return
    if jobs:
        done, _ = await asyncio.wait(list(jobs.values()), timeout=seconds)
        for f in jobs.values():
            if f not in done:
                f.cancel()

    def answer(f: "asyncio.Future") -> Tuple[bool, Optional[List[str]]]:
        """(answered, subset): a cache-only miss isn't answered; a failure is, with nothing."""
        if not f.done() or f.cancelled():
            return ask is not None, None
        try:
            got = f.result()
        except Exception:
            return True, None
        return (got is not None or ask is not None), got

    out: Dict[str, Any] = {}
    pending: List[str] = []
    for sid, p in plans.items():
        waiting = False
        banks = []
        for b in p["banks"]:
            leaf = vocab.leaves[b["list"]]
            n: Optional[List[str]] = None
            if b["phrase"]:
                f = next(f for bb, f in asks[sid] if bb is b)
                answered, n = answer(f)
                if not answered:
                    waiting = True
                elif n is None:
                    n = None if b["role"] == "age" else []   # failed: an age seeds nothing, a list drops
                    if b["role"] == "age":
                        b = {**b, "failed": True}
            if b.get("where"):
                within = [v.text for v in leaf.values if tags_match(v.tags, b["where"])]
                n = [t for t in (n if n is not None else within) if t in set(within)] or (n if n is not None else None)
            banks.append({**b, "narrowed": n})
        stated: Dict[str, List[str]] = {}
        for g, f in scene.get(sid, []):
            answered, got = answer(f)
            if not answered:
                waiting = True
            elif got and set(got) != {v.text for v in g.eligible()}:
                for facet in g.gives:
                    fam = {x for t in got for x in (g.context_tags(t, facet) or ())}
                    if fam:
                        stated[facet] = sorted(fam)
        minor: List[str] = []
        age = next((b for b in banks if b["role"] == "age"), None)
        if age is not None and age.get("narrowed"):
            minor += minor_ages(age["narrowed"])
        for f in [*list_ages.get(sid, []), *([about_ages[sid]] if sid in about_ages else [])]:
            answered, got = answer(f)
            if not answered:
                waiting = True
            elif got:
                minor += minor_ages(got)
        heritage = next((b["list"] for b in banks if b["role"] == "descent"), "")
        said = next(iter((p.get("said") or {}).values()), "")
        place = place_for(said, home, heritage) if heritage else None
        out[sid] = {"v": SEEDS_VERSION, "kind": p["kind"], "banks": banks, "stated_descent": p.get("stated_descent", False),
                    **({"people": p["people"]} if p.get("people") else {}),
                    **({"answers": p["answers"]} if p.get("answers") else {}),
                    **({"place": place} if place else {}),
                    **({"stated": stated} if stated else {}), **({"minor": list(dict.fromkeys(minor))} if minor else {})}
        if waiting:
            pending.append(sid)
    entry["seeds"], entry["seeds_pending"] = out, pending


__all__ = ["BANK_ROLE", "ReadingError", "SEEDS_VERSION", "age_basis", "age_choices", "kind_plan", "narrow_seeds", "plan", "seeds_of"]
