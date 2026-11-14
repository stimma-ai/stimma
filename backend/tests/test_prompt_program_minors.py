"""The minors rules (stimma-plans MINORS_POLICY.md), as seeding.narrow_seeds applies them from the
reading of ages.py: each person is pinned a child, a teenager or an adult once per prompt by the
natural reading of the whole prompt (an adult when vague or with no answer), and anyone in the
prompt is read too. When anyone reads child or teenager, every slot of the prompt, on any line,
drops adult-only values and its writer is told; a child or a teenager draws their stage's ages,
child words and no build. The model is faked; the narrowing and the reading run as in the product."""

from __future__ import annotations

import asyncio
import json
import random
from typing import Any, Dict, List, Optional

from prompt_programs import ages, seeding
from prompt_programs import variants as V
from prompt_programs.narrow import NarrowCache
from prompt_programs.vocab import AGE_LIST, vocabulary


def _ages() -> List[str]:
    return [v.text for v in vocabulary().get(AGE_LIST).values]


def _young() -> set:
    return {v.text for v in vocabulary().get(AGE_LIST).values if v.minor}


def _person(n: int, words: str, people: str = "one") -> Dict[str, Any]:
    return {"n": n, "kind": "person", "label": words, "lead": "a", "category": "",
            "person": {"noun": words.split()[-1], "presentation": "", "stated": {}, "people": people,
                       "vary": ["age", "descent", "build", "hair"], "outfit": "person.outfit.casual"}}


def _list(n: int, lid: str, about: str) -> Dict[str, Any]:
    return {"n": n, "kind": "list", "label": about, "lead": "", "category": "", "list": {"list": lid, "about": about}}


class Model:
    """The age narrowing keeps `keep` (every age by default), other narrowings everything; the
    reading by the person asked about (`stage`, default adult; anyone in the prompt: `anyone`)."""

    def __init__(self, stage: Optional[Dict[str, Any]] = None, anyone: Any = "adult", keep: Optional[List[str]] = None):
        self.stage, self.anyone, self.keep = stage or {}, anyone, keep
        self.asked: List[tuple] = []

    async def __call__(self, messages, project_id, tokens):
        system, user = messages[0]["content"], messages[1]["content"]
        if system == ages.READING_SYSTEM:
            person = user.split('"')[1]
            self.asked.append(("reading", person))
            got = self.anyone if person == ages.ANYONE else self.stage.get(person, "adult")
            if isinstance(got, Exception):
                raise got
            return got if got.startswith(("{", "!")) or got in ("", "maybe") else json.dumps({"age": got})
        self.asked.append(("narrow", ""))
        if '"Age"' in user:
            return json.dumps(self.keep if self.keep is not None else _ages())
        return '["ALL"]'


def settle(model, prompt: str, readings: List[Dict[str, Any]], words: List[str], cache=None) -> Dict[str, Any]:
    slots = [{"id": f"s{r['n']}", "n": r["n"], "words": w, "state": "ready", "line": 1} for r, w in zip(readings, words)]
    entry = {"prompt": prompt, "segments": [], "slots": slots, "readings": {"slots": readings}, "lists": []}
    asyncio.run(seeding.narrow_seeds(entry, cache, model, seconds=30))
    return entry


def _age_bank(record):
    return next((b for b in record["banks"] if b["role"] == "age"), None)


def _texts(seeds) -> set:
    return {t for b in [seeds.core, seeds.spread, *seeds.ideas] if b for t in b.texts()}


def test_a_prompt_with_only_adults_is_not_limited():
    m = Model()
    e = settle(m, "a <farmer> in rural Vietnam, <camera>", [_person(1, "farmer"), _list(2, "camera.genre", "the genre")],
               ["farmer", "camera"])
    assert e["ages"]["young"] is False
    farmer, camera = e["seeds"]["s1"], e["seeds"]["s2"]
    assert not set(_age_bank(farmer)["narrowed"]) & _young()   # adult ages, though the narrowing kept every age
    assert "young" not in camera and seeding.young_marks(camera) == ()
    adult_genres = {v.text for v in vocabulary().get("camera.genre").values if v.adult_only}
    assert adult_genres <= _texts(seeding.seeds_of(camera))


def test_a_vague_person_is_an_adult_with_adult_vocabulary():
    m = Model({"girl": "adult"}, anyone="adult")
    e = settle(m, "a <girl> lying on the bed, <expression>", [_person(1, "girl"), _list(2, "person.expression", "her look")],
               ["girl", "expression"])
    girl, expr = e["seeds"]["s1"], e["seeds"]["s2"]
    assert "minor" not in girl and "young" not in expr
    flirty = {v.text for v in vocabulary().get("person.expression").values if v.adult_only}
    assert flirty <= _texts(seeding.seeds_of(expr))


def test_a_child_makes_every_slot_young_and_is_written_as_a_child():
    m = Model({"girl": "child"}, anyone="child")
    e = settle(m, "a <girl> on a swing, <camera>", [_person(1, "girl"), _list(2, "camera.genre", "the genre")],
               ["girl", "camera"])
    girl, camera = e["seeds"]["s1"], e["seeds"]["s2"]
    assert girl["minor"] and all(V.age_years(a) < 13 for a in girl["minor"])
    assert camera["young"] == "child" and "minor" not in camera
    seeds = seeding.seeds_of(girl)
    assert seeds.age is not None and seeds.gender.list_id == "person.gender_child"
    assert set(seeds.gender.texts()) <= {"girl", "boy", "trans girl", "trans boy", "non-binary child"}
    assert not any(b.list_id == "person.build" for b in seeds.ideas)   # no build for a child
    adult_genres = {v.text for v in vocabulary().get("camera.genre").values if v.adult_only}
    cam = seeding.seeds_of(camera)
    assert not _texts(cam) & adult_genres
    msg = V.messages(V.Slot("camera", "a girl on a swing, ⟦camera⟧", (19, 27), "list"),
                     V.draw_seeds(random.Random(1), cam, 4), cam)
    assert V.young_line("child") in msg[1]["content"]
    assert seeding.young_marks(camera) == ("~child",) and seeding.young_marks(girl) != seeding.young_marks(camera)


def test_a_teenager_on_another_line_makes_a_line_two_slot_young():
    m = Model(anyone="teenager")
    e = settle(m, "a teenage boy at the lake\n<expression>", [_list(1, "person.expression", "his look")], ["expression"])
    rec = e["seeds"]["s1"]
    assert rec["young"] == "teenager"
    flirty = {v.text for v in vocabulary().get("person.expression").values if v.adult_only}
    assert flirty and not _texts(seeding.seeds_of(rec)) & flirty
    assert ("reading", ages.ANYONE) in m.asked


def test_a_teenager_is_a_teenage_girl_or_boy():
    m = Model({"teenage skater": "teenager"}, anyone="teenager")
    rec = settle(m, "a <teenage skater> doing a kickflip", [_person(1, "teenage skater")], ["teenage skater"])["seeds"]["s1"]
    assert all(13 <= V.age_years(a) <= 17 for a in rec["minor"])
    assert seeding.seeds_of(rec).gender.list_id == "person.gender_teen"


def test_a_family_reads_for_its_youngest_and_its_outfit_ideas_are_filtered():
    m = Model({"family": "child"}, anyone="child")
    rec = settle(m, "a <family> at the beach", [_person(1, "family", "family")], ["family"])["seeds"]["s1"]
    assert rec["young"] == "child" and rec["stage"] == "child"
    casual = {v.text for v in vocabulary().get("person.outfit.casual").values if v.adult_only}
    assert not _texts(seeding.seeds_of(rec)) & casual
    note = vocabulary().kind("person").question("people").option("family").note
    assert "children among its members" in note


def test_no_answer_is_an_adult_and_never_cached(tmp_path):
    cache = NarrowCache(tmp_path)
    for i, reply in enumerate(("maybe", '{"age": "open"}', "")):   # unreadable twice: an adult, pinned
        m = Model({"toddler": reply}, anyone="adult", keep=sorted(_young()))
        rec = settle(m, f"a <toddler> playing in the sand {i}", [_person(1, "toddler")], ["toddler"], cache=cache)["seeds"]["s1"]
        assert "minor" not in rec and "young" not in rec, reply
        assert not set(_age_bank(rec)["narrowed"] or ()) & _young()
    m = Model({"toddler": RuntimeError("down")}, anyone="adult", keep=sorted(_young()))
    rec = settle(m, "a <toddler> playing in the sand", [_person(1, "toddler")], ["toddler"], cache=cache)["seeds"]["s1"]
    assert "minor" not in rec and not set(_age_bank(rec)["narrowed"] or ()) & _young()
    m = Model({"toddler": "child"}, anyone="child")
    assert settle(m, "a <toddler> playing in the sand", [_person(1, "toddler")], ["toddler"], cache=cache)["seeds"]["s1"]["minor"]
    m2 = Model({}, anyone="adult")   # pinned: the cached answer stands, asked no more
    rec = settle(m2, "a <toddler> playing in the sand", [_person(1, "toddler")], ["toddler"], cache=cache)["seeds"]["s1"]
    assert rec["minor"] and not any(k == "reading" for k, _ in m2.asked)


def test_the_reading_is_asked_beside_the_narrowing_not_after_it():
    started = asyncio.Event()

    class Slow(Model):
        async def __call__(self, messages, project_id, tokens):
            if messages[0]["content"] == ages.READING_SYSTEM:
                started.set()
            else:
                await asyncio.wait_for(started.wait(), 5)   # a narrowing waits for the reading to be asked
            return await super().__call__(messages, project_id, tokens)
    e = settle(Slow({"chef": "adult"}), "a <chef> in a kitchen", [_person(1, "chef")], ["chef"])
    assert e["seeds"]["s1"] and not e["seeds_pending"]


def test_a_cache_only_pass_keeps_every_slot_waiting_for_the_reading(tmp_path):
    slots = [{"id": "s1", "n": 1, "words": "camera", "state": "ready", "line": 1}]
    entry = {"prompt": "a girl, <camera>", "segments": [], "slots": slots,
             "readings": {"slots": [_list(1, "camera.genre", "the genre")]}, "lists": []}
    asyncio.run(seeding.narrow_seeds(entry, NarrowCache(tmp_path), None))
    assert entry["seeds_pending"] == ["s1"] and entry["ages"] is None


def test_the_reply_is_read_by_its_value_and_retried_once():
    assert ages.parse_reading('{"age": "child"}') == "child"
    assert ages.parse_reading('{" age": "teenager"}') == "teenager"
    assert ages.parse_reading('{"age": "none"}') is None and ages.parse_reading('{"age": "none"}', anyone=True) == "none"
    for bad in ("", "maybe", '{"age": "open"}', '{"age": "child", "also": "adult"}', None):
        assert ages.parse_reading(bad) is None
    sent: List[str] = []

    async def ask(messages, project_id, tokens):
        sent.append(messages[1]["content"])
        return "!!!!!!!!" if len(sent) == 1 else '{"age": "child"}'
    assert asyncio.run(ages.reading("girl", "a girl on a swing", None, ask)) == "child"
    assert sent[1] == ages.RETRY_LEAD + sent[0]


def test_vague_words_are_said_to_be_adults():
    assert 'said of "a girl": adult' in ages.READING_SYSTEM and '"open"' not in ages.READING_SYSTEM


def test_every_value_tagged_lingerie_corset_or_flirtatious_is_adult_only():
    found = 0
    for leaf in vocabulary().leaves.values():
        for v in leaf.values:
            if {"lingerie", "corset_bustier"} & set(v.tags.get("kind") or ()) or "flirtatious" in (v.tags.get("mood") or ()):
                found += 1
                assert v.adult_only, (leaf.id, v.text)
    assert found >= 17


def test_the_improve_guides_and_the_judge_say_the_rule():
    from pathlib import Path

    import yaml

    from prompt_programs.llm_judge import RULES
    from prompts import get_prompt
    keys = [k for k in yaml.safe_load((Path(__file__).resolve().parents[2] / "prompts.yaml").read_text())["prompt_enhancement"]
            if k.startswith(("improve_", "fill_")) and k != "improve_audio_system_prompt"]
    assert len(keys) >= 14
    for k in keys:
        assert "Never add sexualized dress, pose or expression for a child or a teenager." in get_prompt("prompt_enhancement", k), k
    assert "sexualizes a child or a teenager" in RULES
