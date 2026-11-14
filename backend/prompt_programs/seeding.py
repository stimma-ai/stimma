"""What a slot's variants are seeded with: its reading's lists, narrowed by the slot's words.

A slot's reading (reader.py) says what it is; `plan` turns that into the vocabulary lists that
seed its writes (variants.Seeds), each with the words that narrow it:

- a person: descent (by the words that state one), gender and age (by the person's own words,
  the age with the minors rules, narrow.py), and ideas from build, hair and their outfit list
  (none when the prompt says what they wear or another slot is their clothes);
- an animal: its kind, breed and life stage, as ideas;
- a camera: its lists, as ideas;
- a slot bound to one list (a list slot, a light with a list): that list, narrowed by its words,
  one value per variant as its core;
- a free slot: the lists the reader names for it, as ideas.

`narrow_seeds` answers every plan's narrowing with the words-only question (narrow.subset:
shared across prompts, cached once), reads what the prompt states of the scene for lists held
for a setting (a light that places the scene outdoors), and whether the person may be under 18
(their age, a user list's ages on their line, the age of whoever a list slot is about). The
answers are kept in the entry (`entry["seeds"][slot id]`); `seeds_of` builds the writer's
Seeds from them. A narrowing not asked yet holds that slot's first write (`entry["seeds_pending"]`;
a slot that can't be about a person's age shows one unseeded turn meanwhile, fluent.early_job);
one that failed or keeps nothing drops that list's seeds, never the slot.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional, Sequence, Tuple

from core.logging import get_logger
from prompt_programs import variants as V

log = get_logger(__name__)

SEEDS_VERSION = "seeds-2"   # seeds-2: groups, heritage, scene-narrowed clothes, hairstyle and light

# A person's look: detail -> list (fill.DETAILS' names, which the reader's `stated` uses).
PERSON_IDEAS = (("build", "person.build"), ("hair", "person.hair_length"), ("hair_texture", "person.hair_texture"),
                ("hair_color", "person.hair_color"), ("hairstyle", "person.hairstyle"),
                ("facial_hair", "person.facial_hair"))
ANIMAL_LISTS = {"species": "animal.species", "life_stage": "animal.life_stage"}
COUPLE = "person.couple"        # who a couple is: a man and a woman, two women, two men
SCENE_LIGHT = "lighting.scene"  # a light slot's list when its reading names none
PEOPLE = ("one", "couple", "family", "group")   # reader.PEOPLE


class ReadingError(ValueError):
    """A reading its seeds can't be planned from (the reader checks for these before it caches)."""


def _leaf(lid: Any) -> Any:
    from prompt_programs.vocab import vocabulary
    leaf = vocabulary().get(lid) if isinstance(lid, str) else None
    if leaf is None:
        raise ReadingError(f"{lid!r} is not a list")
    return leaf


def plan(reading: Dict[str, Any], words: str = "") -> Dict[str, Any]:
    """The lists a reading seeds from: {"kind", "banks": [{"role", "list", "phrase", "about",
    "where", "age"}], "stated_descent"}. role: descent, gender or age (a person's), core (a slot
    bound to one list) or idea. phrase: the words that narrow it ("" for the whole list). where:
    a facet filter ({"presentation": "feminine"}). age: read with the minors rules in its line.
    ReadingError for a reading that names a list there isn't. Plain data, no model."""
    from prompt_programs.fill import CAMERA, KINDS
    kind = reading.get("kind")
    if kind not in KINDS:
        raise ReadingError(f"kind {kind!r} is not one of {KINDS}")
    got = reading.get(kind) if isinstance(reading.get(kind), dict) else {}
    words = words or str(reading.get("words") or "")
    banks: List[Dict[str, Any]] = []

    def add(role: str, lid: str, phrase: str = "", about: str = "", where: Optional[Dict[str, str]] = None,
            age: bool = False, scene: bool = False) -> None:
        leaf = _leaf(lid)
        if where:
            where = {f: p for f, p in where.items() if p in leaf.local_facets.get(f, ()) or f in leaf.facets}
        banks.append({"role": role, "list": leaf.id, "phrase": phrase.strip(), "about": about,
                      **({"where": where} if where else {}), **({"age": True} if age else {}),
                      **({"scene": True} if scene else {})})

    if kind == "person":
        noun = str(got.get("noun") or "person")
        stated = {str(k): str(v) for k, v in (got.get("stated") or {}).items() if str(v).strip()}
        presentation = got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else ""
        people = got.get("people") if got.get("people") in PEOPLE else "one"
        vary = set(got.get("vary") or ())
        # A real people's heritage applies only to a real-world human (the reading's `heritage`:
        # an elf has none), and an unrelated group shares none: no descent seed then. A couple and
        # a family share one heritage, drawn as for one person.
        if got.get("heritage") is not False and people != "group":
            add("descent", V.DESCENT, stated.get("descent", ""), f"the {noun}'s descent")
        if people == "one":
            add("gender", V.GENDER, words, f"the {noun}'s gender")
        elif people == "couple":   # who the two are, one value per variant (vocab person.couple's shares)
            add("gender", COUPLE, words, f"who the {noun} are")
        if people in ("one", "couple"):   # a family's or a group's ages follow each member's role
            age_words = stated.get("age", "")
            phrase = words if not age_words or age_words.lower() in words.lower() else f"{age_words}, {words}"
            add("age", V.AGE, phrase, f"the {noun}'s age", age=True)
            for detail, lid in PERSON_IDEAS:
                if detail == "facial_hair" and presentation != "masculine" or vary and detail not in vary:
                    continue   # the details the reading varies (hairstyle only when the prompt asks)
                # a hairstyle suits who they are and where (a farmer's isn't a salon cut): read in the scene
                add("idea", lid, stated.get(detail, "") or (words if detail == "hairstyle" else ""),
                    f"the {noun}'s {detail.replace('_', ' ')}",
                    {"presentation": presentation} if presentation and detail == "build" else None,
                    scene=detail == "hairstyle")
        outfit = str(got.get("outfit") or "")
        if outfit and outfit != "written" and not got.get("clothes_part") and not str(got.get("clothes") or "").strip():
            # What they wear is narrowed by who they are and the scene ("farmer" in rural Vietnam
            # keeps work clothes, not a neon jersey top), like any list a slot's words narrow.
            add("idea", outfit, words, f"what the {noun} wears", {"presentation": presentation} if presentation else None,
                scene=True)
        owned = bool(got.get("clothes_part")) or bool(str(got.get("clothes") or "").strip())
        return {"kind": kind, "banks": banks, "stated_descent": bool(stated.get("descent")), "clothes_owned": owned,
                "said_place": str(got.get("place") or "").strip(), **({"people": people} if people != "one" else {})}
    if kind == "animal":
        noun = str(got.get("noun") or words)
        stated = {str(k): str(v) for k, v in (got.get("stated") or {}).items() if str(v).strip()}
        vary = [d for d in got.get("vary") or [] if d in ("species", "breed", "life_stage")]
        if "species" in vary:
            sort = str(got.get("type") or "")
            add("idea", ANIMAL_LISTS["species"], words, f"what kind of animal the {noun} is", {"kind": sort} if sort else None)
        if "breed" in vary and got.get("breed"):
            add("idea", str(got["breed"]), stated.get("breed", words), f"the {noun}'s breed")
        if "life_stage" in vary:
            add("idea", ANIMAL_LISTS["life_stage"], stated.get("life_stage", ""), f"the {noun}'s life stage")
        return {"kind": kind, "banks": banks}
    if kind == "camera":
        for d in got.get("vary") or []:
            if d in CAMERA:
                add("idea", f"camera.{d}")
        return {"kind": kind, "banks": banks}
    if kind == "light":
        # Ideas, not cores: one random look per variant pushed sources the place doesn't have
        # (stage footlights, a vending machine in a living room); the writer rejects ideas that don't fit.
        # The scene list by default: light described as light, narrowed by the whole scene, so a
        # restaurant keeps evening and candle light, not track lights or a TV's glow.
        add("idea", str(got.get("list") or SCENE_LIGHT), words, "the light in this picture", scene=True)
        return {"kind": kind, "banks": banks}
    if kind == "list":
        p = got.get("presentation") if got.get("presentation") in ("feminine", "masculine") else ""
        add("core", str(got.get("list")), words, str(got.get("about") or words), {"presentation": p} if p else None)
        return {"kind": kind, "banks": banks}
    # Narrowed by the words like any other list: "sports car" keeps the kinds of sports car of a
    # road vehicle list, not a tractor or a city bus (a seed that contradicts the words sends the
    # writer arguing with itself). A list the words say nothing about keeps every value.
    about = str(got.get("about") or words)
    for lid in (got.get("lists") or [])[:3]:
        try:
            add("idea", str(lid), words, about)
        except ReadingError:
            continue   # a list the vocabulary no longer has
    return {"kind": kind, "banks": banks}


def seeds_of(record: Dict[str, Any]) -> V.Seeds:
    """The writer's seeds from a slot's narrowed plan (entry["seeds"][slot id])."""
    banks = record.get("banks") or []
    stated = record.get("stated") or None
    minor = tuple(record.get("minor") or ())

    def narrowed(b: Dict[str, Any]) -> Optional[List[str]]:
        n = b.get("narrowed")
        return list(n) if isinstance(n, list) else None
    if record.get("kind") == "person":
        by = {b["role"]: b for b in banks if b["role"] in ("descent", "gender", "age")}
        age = by.get("age")
        return V.person_seeds(
            descent=narrowed(by["descent"]) if "descent" in by else None,
            stated_descent=bool(record.get("stated_descent")),
            gender=narrowed(by["gender"]) if "gender" in by else None,
            ages=narrowed(age) if age is not None and age.get("narrowed") is not None else None,
            ideas=[(b["list"], narrowed(b)) for b in banks if b["role"] == "idea"],
            stated=stated, minor=minor, clothes_owned=bool(record.get("clothes_owned")),
            people=str(record.get("people") or ""), gender_list=by["gender"]["list"] if "gender" in by else "",
            heritage="descent" in by,
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
        if p["kind"] == "person":
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
        place = place_for(p.get("said_place"), home) if p["kind"] == "person" else None
        out[sid] = {"v": SEEDS_VERSION, "kind": p["kind"], "banks": banks, "stated_descent": p.get("stated_descent", False),
                    **({"people": p["people"]} if p.get("people") else {}),
                    **({"place": place} if place else {}),
                    "clothes_owned": p.get("clothes_owned", False),
                    **({"stated": stated} if stated else {}), **({"minor": list(dict.fromkeys(minor))} if minor else {})}
        if waiting:
            pending.append(sid)
    entry["seeds"], entry["seeds_pending"] = out, pending


__all__ = ["COUPLE", "PEOPLE", "PERSON_IDEAS", "SCENE_LIGHT", "ReadingError", "SEEDS_VERSION", "age_basis", "age_choices", "narrow_seeds", "plan", "seeds_of"]
